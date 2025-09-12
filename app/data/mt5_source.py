# app/data/mt5_source.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import MetaTrader5 as MT5
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer

from .models import Bar
from .resample import CandleAggregator

# ---------------------------
#  Constantes & Config MT5
# ---------------------------

TIMEFRAMES = {
    "M1": MT5.TIMEFRAME_M1,
    "M5": MT5.TIMEFRAME_M5,
    "M30": MT5.TIMEFRAME_M30,
}
TF_SECONDS = {"M1": 60, "M5": 300, "M30": 1800}

MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Debug console
DEBUG = True
def _dbg(*a):
    if DEBUG:
        print(*a)

# ---------------------------------------
#  Option "hist min bars" (désactivée)
# ---------------------------------------
# Tu ne veux PAS forcer un minimum en continu → laisse False.
ENFORCE_MIN_BARS = False
MIN_BARS = 50

# ---------------------------------------
#  First-load only (anti "une seule bougie")
# ---------------------------------------
# On bufferise uniquement au tout premier affichage.
FIRST_LOAD_MIN_BARS = 120      # seuil confortable pour l'échelle initiale
FIRST_LOAD_TIMEOUT_MS = 2500   # délai max d'attente avant d'envoyer quand même


class DataWorker(QObject):
    """
    Worker MT5:
      - historyReady(list[dict]): premier batch (setData côté chart)
      - barReady(dict): mise à jour live (update côté chart)

    Ajouts:
      - Buffer "first-load only": on accumule jusqu'à FIRST_LOAD_MIN_BARS
        ou jusqu'au FIRST_LOAD_TIMEOUT_MS puis on envoie une seule fois.
      - Ensuite, flux normal sans latence (emit direct).
    """

    historyReady = pyqtSignal(list)   # list[dict]
    barReady     = pyqtSignal(dict)   # dict
    finished     = pyqtSignal()       # signal d’arrêt propre

    def __init__(self, symbol: str, timeframe: str, depth: int = 5000):
        super().__init__()
        self.symbol = symbol
        self.tf     = timeframe
        self.depth  = depth

        self.days_back = 60
        self._running  = False

        self._tick_timer: QTimer | None = None
        self._agg = CandleAggregator(TF_SECONDS[self.tf])
        self._last_tick_time = 0

        self._history_retry = 0
        self._max_history_retries = 6

        self._seed_bar: dict | None = None
        self._debug_tick_count = 0

        # -------- First-load only --------
        self._first_load_done: bool = False
        self._first_buffer: list[dict] = []
        self._first_timer: QTimer | None = None

    # ---------- lifecycle ----------

    @pyqtSlot()
    def start(self):
        """Démarre depuis le thread du worker (connecté à QThread.started)."""
        if self._running:
            return
        self._running = True

        ok = MT5.initialize() or MT5.initialize(path=MT5_PATH)
        if not ok:
            print("❌ MT5 init failed:", MT5.last_error())
            self._running = False
            self.finished.emit()
            return

        self._ensure_symbol_selected(self.symbol)
        print(f"✅ MT5 initialized (worker) [{self.symbol} {self.tf}]")

        self._history_retry = 0

        # Démarre le timer "first-load only" (sécurité anti-blocage)
        if not self._first_load_done and FIRST_LOAD_TIMEOUT_MS > 0:
            self._first_timer = QTimer(self)
            self._first_timer.setSingleShot(True)
            self._first_timer.timeout.connect(self._flush_first_load_due_to_timeout)
            self._first_timer.start(FIRST_LOAD_TIMEOUT_MS)

        self._load_history()
        self.start_stream()

    @pyqtSlot()
    def shutdown(self):
        """Arrêt propre demandé par l’UI (QueuedConnection)."""
        self.stop_stream()
        MT5.shutdown()
        self._running = False
        self.finished.emit()

    # ---------- commandes UI ----------

    @pyqtSlot(str, str)
    def set_params(self, symbol: str, timeframe: str):
        """Changement fluide de symbole/timeframe sans tuer le thread."""
        if symbol == self.symbol and timeframe == self.tf:
            return

        self.stop_stream()

        self.symbol = symbol
        self.tf     = timeframe
        self._ensure_symbol_selected(self.symbol)

        self._last_tick_time = 0
        self._history_retry  = 0

        # IMPORTANT: on ne réactive pas le "first-load only" ici.
        # Il ne sert qu'au tout premier rendu de la session.
        self._load_history()
        self.start_stream()
        print(f"🔁 Params applied → {self.symbol} {self.tf}")

    @pyqtSlot()
    def start_stream(self):
        if self._tick_timer:
            return

        self._agg = CandleAggregator(TF_SECONDS[self.tf])
        if self._seed_bar:
            # Seed l’agrégateur avec la dernière barre (fermée ou stub courante)
            self._agg.seed(self._seed_bar)
            _dbg(f"[SEED] agg.slot={self._agg.slot} (from last history bar)")
            self._seed_bar = None

        self._last_tick_time = 0
        self._debug_tick_count = 0

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(100)  # 100ms: réactif sans spammer
        self._tick_timer.timeout.connect(self._poll_tick)
        self._tick_timer.start()

    def stop_stream(self):
        if self._tick_timer:
            self._tick_timer.stop()
            self._tick_timer.deleteLater()
            self._tick_timer = None

    # ---------- interne ----------

    def _ensure_symbol_selected(self, symbol: str):
        if not MT5.symbol_select(symbol, True):
            print(f"⚠️ symbol_select({symbol}) a échoué:", MT5.last_error())

    def _latest_tick(self) -> Optional[dict]:
        t = MT5.symbol_info_tick(self.symbol)
        if not t:
            return None
        price = t.last if t.last else ((t.bid or 0) + (t.ask or 0)) / 2.0
        return {"time": int(t.time), "price": float(price)}

    def _load_history(self):
        """Récupère l’historique, ajoute un stub live si nécessaire, seed l’agg."""
        tf_sec = TF_SECONDS[self.tf]

        # Slot courant basé sur le tick s’il existe, sinon sur l’horloge
        tick = self._latest_tick()
        if tick:
            current_slot = (tick["time"] // tf_sec) * tf_sec
        else:
            now = int(datetime.now(timezone.utc).timestamp())
            current_slot = (now // tf_sec) * tf_sec

        # 1) tentative par date (rapide quand le serveur est OK)
        utc = timezone.utc
        end = datetime.fromtimestamp(current_slot, tz=utc)
        start = end - timedelta(days=self.days_back)
        rates = MT5.copy_rates_range(self.symbol, TIMEFRAMES[self.tf], start, end)

        # 2) si vide → fallback direct (nombre estimé de barres sur days_back)
        if rates is None or len(rates) == 0:
            print(f"⚠️ copy_rates_range vide ({self.symbol} {self.tf}, {self.days_back}j). Fallback depth={self.depth}")
            est_needed = int(self.days_back * 86400 // tf_sec) + 500  # marge
            need = max(200, min(self.depth, est_needed))
            rates = MT5.copy_rates_from_pos(self.symbol, TIMEFRAMES[self.tf], 0, need)

        # 3) si pas vide mais TROP ANCIEN → re-fetch les N DERNIÈRES barres
        if rates is not None and len(rates) > 0:
            # sécurise l’accès au dernier time
            try:
                last_time = int(rates[-1]["time"])
            except Exception:
                df_tmp = pd.DataFrame(rates)
                last_time = int(df_tmp.iloc[-1]["time"])

            if current_slot - last_time > 3 * tf_sec:
                print(f"⚠️ Historique trop ancien ({self.symbol} {self.tf}): last={last_time}, cur_slot={current_slot} → re-fetch dernières barres")
                est_needed = int(self.days_back * 86400 // tf_sec) + 500
                need = max(200, min(self.depth, est_needed))
                rates = MT5.copy_rates_from_pos(self.symbol, TIMEFRAMES[self.tf], 0, need)

        # 4) toujours rien ? on retente un peu plus tard (début de session, etc.)
        if rates is None or len(rates) == 0:
            if self._history_retry < self._max_history_retries:
                self._history_retry += 1
                print(f"⏳ Historique indisponible ({self.symbol} {self.tf}), retry {self._history_retry}/{self._max_history_retries}")
                QTimer.singleShot(1200, self._load_history)
            else:
                print(f"⚠️ Historique toujours vide pour {self.symbol} {self.tf}")
            return

        # Construction des barres
        df = pd.DataFrame(rates)
        vol_col = (
            "real_volume"
            if "real_volume" in df.columns
            else ("tick_volume" if "tick_volume" in df.columns else None)
        )

        bars: list[dict] = []
        for r in df.itertuples(index=False):
            bars.append(
                Bar(
                    time=int(getattr(r, "time")),
                    open=float(getattr(r, "open")),
                    high=float(getattr(r, "high")),
                    low=float(getattr(r, "low")),
                    close=float(getattr(r, "close")),
                    volume=float(getattr(r, vol_col)) if vol_col and hasattr(r, vol_col) else 0.0,
                ).model_dump()
            )

        # Optionnel (désactivé) : attendre un minimum de barres en continu
        if ENFORCE_MIN_BARS and len(bars) < MIN_BARS:
            if self._history_retry < self._max_history_retries:
                self._history_retry += 1
                print(
                    f"⏳ Historique trop court ({len(bars)}<{MIN_BARS}) pour {self.symbol} {self.tf} — "
                    f"retry {self._history_retry}/{self._max_history_retries}"
                )
                QTimer.singleShot(1000, self._load_history)
                return
            else:
                print(f"⚠️ Historique court ({len(bars)} barres) — envoi quand même.")

        self._history_retry = 0
        last_time = bars[-1]["time"]

        # Stub si le tick est déjà dans le slot suivant
        if tick:
            if current_slot > last_time:
                p = tick["price"]
                bars.append(
                    Bar(
                        time=current_slot, open=p, high=p, low=p, close=p, volume=0.0
                    ).model_dump()
                )
                _dbg(f"[HIST] last={last_time}, tick_slot={current_slot} → add stub")
            else:
                _dbg(f"[HIST] last={last_time}, tick_slot={current_slot}")

        self._seed_bar = bars[-1]
        _dbg(f"📦 {self.symbol} {self.tf} history bars: {len(bars)}  (last={self._seed_bar['time']})")

        # ===== FIRST-LOAD ONLY =====
        if not self._first_load_done:
            # On empile le batch historique dans le buffer
            self._first_buffer.extend(bars)
            self._maybe_flush_first_load()
        else:
            # Après le premier rendu, on continue en comportement normal
            self.historyReady.emit(bars)

    def _poll_tick(self):
        """Boucle timer (100ms) — agrège les ticks en bougie courante + ferme la précédente."""
        tick = MT5.symbol_info_tick(self.symbol)
        if not tick:
            return

        tf_sec = TF_SECONDS[self.tf]
        slot = (int(tick.time) // tf_sec) * tf_sec

        # ignore tick en retard
        if self._agg.slot is not None and slot < self._agg.slot:
            if DEBUG and self._debug_tick_count < 6:
                _dbg(f"[TICK] skip late tick slot={slot} < agg.slot={self._agg.slot}")
                self._debug_tick_count += 1
            return

        if tick.time == self._last_tick_time:
            return
        self._last_tick_time = tick.time

        price = tick.last if tick.last else ((tick.bid or 0) + (tick.ask or 0)) / 2.0
        vol   = float(getattr(tick, "volume", 0.0) or 0.0)

        # [SPIKE_GUARD] ignore prix 0/négatif ou écart instantané >5% vs. close courant
        if not price or price <= 0:
            return
        prev_c = getattr(self._agg, "c", None)
        if prev_c and prev_c > 0 and abs(price - prev_c) / prev_c > 0.05:
            return

        # si on a sauté >1 slot (veille/réveil, pertes de ticks, etc.)
        if self._agg.slot is not None and slot > self._agg.slot + tf_sec:
            closed = Bar(
                time=self._agg.slot,
                open=self._agg.o,
                high=self._agg.h,
                low=self._agg.l,
                close=self._agg.c,
                volume=self._agg.v,
            )
            self._emit_or_buffer(closed)
            seed = Bar(time=slot, open=price, high=price, low=price, close=price, volume=vol)
            self._agg.seed(seed)
            self._emit_or_buffer(seed)
            if DEBUG and self._debug_tick_count < 6:
                _dbg(f"[TICK] jump → seed @ {slot}")
                self._debug_tick_count += 1
            return

        closed, cur = self._agg.push_tick(int(tick.time), float(price), vol)
        if closed:
            self._emit_or_buffer(closed)
        self._emit_or_buffer(cur)

        if DEBUG and self._debug_tick_count < 6:
            _dbg(f"[TICK] tick_slot={slot} agg.slot={self._agg.slot} price={price}")
            self._debug_tick_count += 1

    # ---------- helpers "first-load only" ----------

    def _emit_or_buffer(self, bar: Bar):
        """Pendant le first-load, on bufferise. Ensuite, on émet en direct."""
        if not self._first_load_done:
            self._first_buffer.append(bar.model_dump())
            self._maybe_flush_first_load()
        else:
            self.barReady.emit(bar.model_dump())

    def _maybe_flush_first_load(self):
        if self._first_load_done:
            return
        if len(self._first_buffer) >= FIRST_LOAD_MIN_BARS:
            self._flush_first_load()

    def _flush_first_load_due_to_timeout(self):
        if self._first_load_done:
            return
        if len(self._first_buffer) > 0:
            self._flush_first_load()
        else:
            # pas de data : on passe quand même en mode live pour ne pas bloquer
            self._first_load_done = True

    def _flush_first_load(self):
        batch = self._first_buffer
        self._first_buffer = []
        try:
            self.historyReady.emit(batch)
        finally:
            self._first_load_done = True
            if self._first_timer:
                self._first_timer.stop()
                self._first_timer = None

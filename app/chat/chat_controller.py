# app/chat/chat_controller.py
import json
from collections import deque
from statistics import mean, pstdev
from typing import Deque, List, Dict, Any
from PyQt6.QtCore import QObject, pyqtSlot, QTimer

from .chat_panel import ChatPanel
from .chat_service_groq import GroqChatService


def _last(seq, n):
    return list(seq)[-n:] if len(seq) > n else list(seq)


def compute_features(bars: List[Dict[str, float]]) -> Dict[str, Any]:
    if not bars:
        return {"note": "no_data"}
    closes = [b["close"] for b in bars]
    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]
    win = min(200, len(closes))
    sub = closes[-win:]
    slope = (sub[-1] - sub[0]) / max(1, win)
    ret   = [(sub[i]-sub[i-1])/sub[i-1] for i in range(1, len(sub)) if sub[i-1] != 0]
    vola  = pstdev(ret) if len(ret) > 2 else 0.0

    def sma(arr, p): 
        return mean(arr[-p:]) if len(arr) >= p else None

    sma20, sma50 = sma(closes, 20), sma(closes, 50)
    cross = "bull" if (sma20 and sma50 and sma20 > sma50) else "bear" if (sma20 and sma50 and sma20 < sma50) else "flat"

    return {
        "window": win,
        "slope_per_bar": slope,
        "volatility_stdev_returns": vola,
        "recent_high": max(highs[-win:]),
        "recent_low": min(lows[-win:]),
        "sma20": sma20,
        "sma50": sma50,
        "sma20_vs_50": cross,
    }


class ChatController(QObject):
    """Relie le worker marché et le panneau de chat + envoie au LLM Groq.
       Ajoute un espacement visuel entre les blocs Q/R sans modifier le ChatPanel."""
    def __init__(self, panel: ChatPanel):
        super().__init__()
        self.panel = panel
        self.service = GroqChatService()
        self.panel.sendRequested.connect(self.on_user_message)

        self.symbol = "EURUSD"
        self.timeframe = "M1"
        self._bars: Deque[Dict[str, float]] = deque(maxlen=5000)

        self.service.responseReady.connect(self._on_ai_reply)
        self.service.error.connect(self._on_ai_error)

        self._watchdog: QTimer | None = None
        self._ind_snapshot: Dict[str, Any] | None = None  # snapshot indicateurs courant

    # --- Alimenté par DataWorker/MainWindow ---
    @pyqtSlot(list)
    def on_history(self, bars: list[dict]):
        self._bars.clear()
        self._bars.extend(bars)

    @pyqtSlot(dict)
    def on_bar(self, bar: dict):
        self._bars.append(bar)

    def set_params(self, symbol: str, timeframe: str):
        self.symbol = symbol
        self.timeframe = timeframe

    def set_indicator_snapshot(self, snap: dict):
        """Reçu depuis MainWindow : {'rsi14':..., 'ema20':..., 'macd':..., 'macd_signal':..., 'macd_hist':...}"""
        self._ind_snapshot = snap

    # --- Chat ---
    @pyqtSlot(str)
    def on_user_message(self, user_text: str):
        # NOTE: le ChatPanel ajoute déjà le message utilisateur (append_user) avant ce slot.
        # On insère un petit espace visuel après le message user pour aérer le bloc Q → R.
        self._spacer()

        recent = _last(list(self._bars), 200)
        features = compute_features(recent)
        context = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "features": features,
            "indicators": (self._ind_snapshot or {}),
            "recent_bars": [
                {"time": b["time"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
                for b in recent
            ],
        }
        sys_prompt = (
            "You are a neutral market-structure explainer embedded in a desktop chart app. "
            "Do not give investment advice or trade instructions. "
            "Explain what price action and indicators suggest (momentum, trend, overbought/oversold, divergence) succinctly."
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Context JSON:\n```json\n{json.dumps(context, separators=(',',':'))}\n```"},
            {"role": "user", "content": user_text},
        ]
        self.panel.append_note("Envoi à l’IA…")
        self.panel.set_busy(True)

        # Watchdog local (60s)
        if self._watchdog:
            self._watchdog.stop(); self._watchdog.deleteLater()
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(60000)
        self._watchdog.timeout.connect(self._on_watchdog_timeout)
        self._watchdog.start()

        self.service.ask(messages)

    def _on_watchdog_timeout(self):
        self.panel.set_busy(False)
        self.panel.append_note("Temps d’attente dépassé (aucune réponse).")

    @pyqtSlot(str)
    def _on_ai_reply(self, text: str):
        if self._watchdog:
            self._watchdog.stop()
        self.panel.set_busy(False)
        self.panel.append_assistant(text)

        # Ajoute un espacement après la réponse IA pour séparer du prochain bloc Q
        self._spacer()

    @pyqtSlot(str)
    def _on_ai_error(self, msg: str):
        if self._watchdog:
            self._watchdog.stop()
        self.panel.set_busy(False)
        self.panel.append_note(f"Erreur Groq: {msg}")
        # Espace aussi après une erreur, pour rester cohérent visuellement
        self._spacer()

    # --- Utilitaire: insérer un espace visuel (ligne vide) ---
    def _spacer(self, height_px: int = 10):
        """Insère un espace vide entre deux blocs de conversation.
           On injecte un petit <div> dans le QTextBrowser du panel."""
        try:
            # On s'appuie volontairement sur l'API publique .view (QTextBrowser) exposée par ChatPanel.
            self.panel.view.append(f"<div style='height:{int(height_px)}px'></div>")
        except Exception:
            # S'il n'y a pas de .view ou si l'appel échoue, on ignore silencieusement.
            pass

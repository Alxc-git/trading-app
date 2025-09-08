# app/indicators/ta.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from math import isfinite

MAX_MARKERS = 600
BB_PERIOD = 20
BB_DEV = 2.0
TR_COOLDOWN = 20      # barres min entre deux signaux Trend Rider
VBO_COOLDOWN = 10     # barres min entre deux signaux VBO

# ----------------- helpers -----------------
def _ema_next(prev_ema: float, price: float, period: int) -> float:
    k = 2.0 / (period + 1.0)
    return price * k + prev_ema * (1.0 - k)

def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if n < period or period <= 0:
        return out
    sma = sum(values[:period]) / period
    out[period - 1] = sma
    ema = sma
    for i in range(period, n):
        ema = _ema_next(ema, values[i], period)
        out[i] = ema
    return out

def _sma_series(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if period <= 0 or n < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out

def _std_window(values: List[float], period: int) -> List[Optional[float]]:
    import math
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if period <= 1 or n < period:
        return out
    s = sum(values[:period]); s2 = sum(v*v for v in values[:period])
    for i in range(period-1, n):
        if i >= period:
            s  += values[i] - values[i-period]
            s2 += values[i]*values[i] - values[i-period]*values[i-period]
        mean = s / period
        var = max(0.0, (s2 / period) - mean*mean)
        out[i] = math.sqrt(var)
    return out

def _rsi_wilder(values: List[float], period: int = 14) -> List[Optional[float]]:
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
    out[period] = rsi
    for i in range(period + 1, n):
        ch = values[i] - values[i - 1]
        gain = max(ch, 0.0); loss = max(-ch, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
        out[i] = rsi
    return out

# ----------------- snapshot -----------------
@dataclass
class IndicatorSnapshot:
    rsi14: Optional[float]
    ema20: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]

# ----------------- moteur -----------------
class IndicatorEngine:
    """EMA20/100, RSI14, MACD(12,26,9) + signaux Trend Rider et Volatility Breakout."""
    def __init__(self,
                 ema_period: int = 20,
                 macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
                 rsi_period: int = 14):
        self._bars: List[Dict[str, Any]] = []
        self.ema_p = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_p = rsi_period

        self._ema20: List[Optional[float]] = []
        self._ema100: List[Optional[float]] = []
        self._rsi14: List[Optional[float]] = []
        self._macd:  List[Optional[float]] = []
        self._macd_sig: List[Optional[float]] = []
        self._macd_hist: List[Optional[float]] = []

        self._bb_mid: List[Optional[float]] = []
        self._bb_up:  List[Optional[float]] = []
        self._bb_dn:  List[Optional[float]] = []
        self._bb_width: List[Optional[float]] = []

        self._markers_trend: List[Dict[str, Any]] = []
        self._markers_vbo:   List[Dict[str, Any]] = []
        self._last_tr_index: Optional[int] = None
        self._last_vbo_index: Optional[int] = None

    # --------- utils ---------
    @staticmethod
    def _first_valid_index(vs: List[Optional[float]]) -> int:
        for i, v in enumerate(vs):
            if v is not None and isfinite(v):
                return i
        return len(vs)

    def _cap(self, L: List[Any], cap: int = MAX_MARKERS) -> List[Any]:
        return L[-cap:] if len(L) > cap else L

    # --------- batch ---------
    def set_history(self, bars: List[Dict[str, Any]]) -> None:
        self._bars = list(bars)
        closes = [float(b["close"]) for b in self._bars]

        self._ema20  = _ema_series(closes, 20)
        self._ema100 = _ema_series(closes, 100)
        ema_fast     = _ema_series(closes, self.macd_fast)
        ema_slow     = _ema_series(closes, self.macd_slow)
        self._rsi14  = _rsi_wilder(closes, self.rsi_p)

        self._macd = [None] * len(closes)
        for i in range(len(closes)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                self._macd[i] = ema_fast[i] - ema_slow[i]
        self._macd_sig  = _ema_series([m if m is not None else 0.0 for m in self._macd], self.macd_signal)
        self._macd_hist = [None] * len(closes)
        for i in range(len(closes)):
            if self._macd[i] is not None and self._macd_sig[i] is not None:
                self._macd_hist[i] = self._macd[i] - self._macd_sig[i]

        mid = _sma_series(closes, BB_PERIOD)
        std = _std_window(closes, BB_PERIOD)
        up, dn, width = [None]*len(closes), [None]*len(closes), [None]*len(closes)
        for i in range(len(closes)):
            if mid[i] is not None and std[i] is not None:
                up[i] = mid[i] + BB_DEV*std[i]
                dn[i] = mid[i] - BB_DEV*std[i]
                width[i] = (up[i] - dn[i]) / mid[i] if mid[i] else None
        self._bb_mid, self._bb_up, self._bb_dn, self._bb_width = mid, up, dn, width

        # Rebuild markers
        self._markers_trend.clear()
        self._markers_vbo.clear()
        self._last_tr_index = self._last_vbo_index = None
        for i in range(1, len(self._bars)):
            tr, vbo = self._signals_for_index(i)
            self._markers_trend.extend(tr)
            self._markers_vbo.extend(vbo)
        self._markers_trend = self._cap(self._markers_trend)
        self._markers_vbo   = self._cap(self._markers_vbo)

    # --------- tick ---------
    def on_bar(self, bar: Dict[str, Any]) -> Dict[str, Any]:
        if not self._bars:
            return {}
        if int(bar["time"]) == int(self._bars[-1]["time"]):
            self._bars[-1] = dict(bar)
        else:
            self._bars.append(dict(bar))

        closes = [float(b["close"]) for b in self._bars]
        t = int(self._bars[-1]["time"])

        self._ema20   = _ema_series(closes, 20)
        self._ema100  = _ema_series(closes, 100)
        ema_fast      = _ema_series(closes, self.macd_fast)
        ema_slow      = _ema_series(closes, self.macd_slow)
        self._rsi14   = _rsi_wilder(closes, self.rsi_p)

        macd_line = None
        if ema_fast[-1] is not None and ema_slow[-1] is not None:
            macd_line = ema_fast[-1] - ema_slow[-1]
        if len(self._macd) != len(self._bars):
            self._macd = [None] * len(self._bars)
        self._macd[-1] = macd_line
        self._macd_sig = _ema_series([m if m is not None else 0.0 for m in self._macd], self.macd_signal)
        macd_hist_v = None
        if macd_line is not None and self._macd_sig[-1] is not None:
            macd_hist_v = macd_line - self._macd_sig[-1]
        if len(self._macd_hist) != len(self._bars):
            self._macd_hist = [None] * len(self._bars)
        self._macd_hist[-1] = macd_hist_v

        mid = _sma_series(closes, BB_PERIOD)
        std = _std_window(closes, BB_PERIOD)
        up, dn, width = [None]*len(closes), [None]*len(closes), [None]*len(closes)
        for i in range(len(closes)):
            if mid[i] is not None and std[i] is not None:
                up[i] = mid[i] + BB_DEV*std[i]
                dn[i] = mid[i] - BB_DEV*std[i]
                width[i] = (up[i] - dn[i]) / mid[i] if mid[i] else None
        self._bb_mid, self._bb_up, self._bb_dn, self._bb_width = mid, up, dn, width

        # new signals for last index
        tr, vbo = self._signals_for_index(len(self._bars)-1)
        if tr:
            self._markers_trend.extend(tr)
            self._markers_trend = self._cap(self._markers_trend)
        if vbo:
            self._markers_vbo.extend(vbo)
            self._markers_vbo = self._cap(self._markers_vbo)

        return {
            "ema20": {"time": t, "value": self._ema20[-1]},
            "rsi14": {"time": t, "value": self._rsi14[-1]},
            "macd":  {"time": t, "macd": macd_line, "signal": self._macd_sig[-1], "hist": macd_hist_v},
            "markers": { "trendRider": tr, "volBreakout": vbo }
        }

    # --------- séries ---------
    def series_for_chart(self) -> Dict[str, Any]:
        times = [int(b["time"]) for b in self._bars]

        def line(vs: List[Optional[float]]) -> List[Dict[str, float]]:
            start = self._first_valid_index(vs)
            out: List[Dict[str, float]] = []
            for i in range(start, len(vs)):
                v = vs[i]
                if v is None or not isfinite(v): continue
                out.append({"time": times[i], "value": float(v)})
            return out

        def hist(vs: List[Optional[float]]) -> List[Dict[str, float]]:
            start = self._first_valid_index(vs)
            out: List[Dict[str, float]] = []
            for i in range(start, len(vs)):
                v = vs[i]
                if v is None or not isfinite(v): continue
                out.append({"time": times[i], "value": float(v),
                            "color": "#22c55e" if v >= 0 else "#ef4444"})
            return out

        return {
            "ema20": line(self._ema20),
            "rsi14": line(self._rsi14),
            "macd": { "line": line(self._macd), "signal": line(self._macd_sig), "hist": hist(self._macd_hist) },
            "markers": {
                "trendRider": self._cap(self._markers_trend[:]),
                "volBreakout": self._cap(self._markers_vbo[:])
            }
        }

    def latest_snapshot(self) -> IndicatorSnapshot:
        def last(vs):
            for v in reversed(vs):
                if v is not None and isfinite(v):
                    return float(v)
            return None
        return IndicatorSnapshot(
            rsi14=last(self._rsi14),
            ema20=last(self._ema20),
            macd=last(self._macd),
            macd_signal=last(self._macd_sig),
            macd_hist=last(self._macd_hist),
        )

    # ----------------- signaux -----------------
    def _marker(self, time: int, price: float, up: bool, label: str, color: str) -> Dict[str, Any]:
        return {
            "time": time,
            "position": "belowBar" if up else "aboveBar",
            "shape": "arrowUp" if up else "arrowDown",
            "color": color,
            "text": label,
            "price": price,
        }

    def _signals_for_index(self, i: int) -> Tuple[List[Dict[str,Any]], List[Dict[str,Any]]]:
        if i <= 0 or i >= len(self._bars):
            return [], []
        t = int(self._bars[i]["time"])
        c = float(self._bars[i]["close"])
        c_prev = float(self._bars[i-1]["close"])

        tr_m, vbo_m = [], []

        # ===== Trend Rider (raffiné) =====
        ema20 = self._ema20[i]; ema100 = self._ema100[i]
        macd_h = self._macd_hist[i]
        rsi = self._rsi14[i]; rsi_prev = self._rsi14[i-1] if i>0 else None

        def ema_slope_up(k=3):
            if i-k < 0: return False
            if self._ema20[i] is None or self._ema20[i-k] is None: return False
            return self._ema20[i] > self._ema20[i-k]
        def ema_slope_dn(k=3):
            if i-k < 0: return False
            if self._ema20[i] is None or self._ema20[i-k] is None: return False
            return self._ema20[i] < self._ema20[i-k]

        # Achat : close>ema20>ema100 & slope↑ & MACD hist>0 en hausse & RSI crosses 50 up (depuis <=48)
        cond_buy = (ema20 is not None and ema100 is not None and macd_h is not None
                    and rsi is not None and rsi_prev is not None and
                    c > ema20 > ema100 and ema_slope_up(3) and
                    macd_h > 0 and (self._macd_hist[i-1] is None or macd_h >= self._macd_hist[i-1]) and
                    rsi_prev <= 48 and rsi >= 52)

        # Vente : close<ema20<ema100 & slope↓ & MACD hist<0 en baisse & RSI crosses 50 down (depuis >=52)
        cond_sell = (ema20 is not None and ema100 is not None and macd_h is not None
                     and rsi is not None and rsi_prev is not None and
                     c < ema20 < ema100 and ema_slope_dn(3) and
                     macd_h < 0 and (self._macd_hist[i-1] is None or macd_h <= self._macd_hist[i-1]) and
                     rsi_prev >= 52 and rsi <= 48)

        if cond_buy:
            if self._last_tr_index is None or (i - self._last_tr_index) >= TR_COOLDOWN:
                tr_m.append(self._marker(t, c, True, "TR↑", "#16a34a"))
                self._last_tr_index = i
        elif cond_sell:
            if self._last_tr_index is None or (i - self._last_tr_index) >= TR_COOLDOWN:
                tr_m.append(self._marker(t, c, False, "TR↓", "#b91c1c"))
                self._last_tr_index = i

        # ===== Volatility Breakout (inchangé, avec cooldown) =====
        bb_up = self._bb_up[i]; bb_dn = self._bb_dn[i]; w = self._bb_width[i]
        if bb_up is not None and bb_dn is not None and w is not None:
            recent = [x for x in self._bb_width[max(0, i-50):i] if x is not None]
            thresh = (sum(recent)/len(recent))*0.6 if recent else w*0.9
            squeeze = w < thresh
            if squeeze:
                if c > bb_up and c_prev <= bb_up:
                    if self._last_vbo_index is None or (i - self._last_vbo_index) >= VBO_COOLDOWN:
                        vbo_m.append(self._marker(t, c, True, "VBO↑", "#f5e24f"))
                        self._last_vbo_index = i
                if c < bb_dn and c_prev >= bb_dn:
                    if self._last_vbo_index is None or (i - self._last_vbo_index) >= VBO_COOLDOWN:
                        vbo_m.append(self._marker(t, c, False, "VBO↓", "#f5e24f"))
                        self._last_vbo_index = i

        return tr_m, vbo_m

# app/indicators/ta.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from math import isfinite

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
        gain = max(ch, 0.0)
        loss = max(-ch, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))
        out[i] = rsi
    return out

@dataclass
class IndicatorSnapshot:
    rsi14: Optional[float]
    ema20: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]

class IndicatorEngine:
    """RSI14, EMA20, MACD(12,26,9) — séries + tick + snapshot."""
    def __init__(self, ema_period: int = 20, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9, rsi_period: int = 14):
        self.ema_p = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_p = rsi_period

        self._bars: List[Dict[str, Any]] = []
        self._ema20: List[Optional[float]] = []
        self._rsi14: List[Optional[float]] = []
        self._macd:  List[Optional[float]] = []
        self._macd_sig: List[Optional[float]] = []
        self._macd_hist: List[Optional[float]] = []

    # ---------- utils internes ----------
    @staticmethod
    def _first_valid_index(vs: List[Optional[float]]) -> int:
        for i, v in enumerate(vs):
            if v is not None and isfinite(v):
                return i
        return len(vs)

    # ---------- batch ----------
    def set_history(self, bars: List[Dict[str, Any]]) -> None:
        self._bars = list(bars)
        closes = [float(b["close"]) for b in self._bars]

        ema20 = _ema_series(closes, self.ema_p)
        ema_fast = _ema_series(closes, self.macd_fast)
        ema_slow = _ema_series(closes, self.macd_slow)
        rsi14 = _rsi_wilder(closes, self.rsi_p)

        macd = [None] * len(closes)
        for i in range(len(closes)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                macd[i] = ema_fast[i] - ema_slow[i]

        macd_sig = _ema_series([m if m is not None else 0.0 for m in macd], self.macd_signal)
        macd_hist = [None] * len(closes)
        for i in range(len(closes)):
            if macd[i] is not None and macd_sig[i] is not None:
                macd_hist[i] = macd[i] - macd_sig[i]

        self._ema20, self._rsi14, self._macd, self._macd_sig, self._macd_hist = ema20, rsi14, macd, macd_sig, macd_hist

    # ---------- tick ----------
    def on_bar(self, bar: Dict[str, Any]) -> Dict[str, Any]:
        if not self._bars:
            return {}
        if int(bar["time"]) == int(self._bars[-1]["time"]):
            self._bars[-1] = dict(bar)
        else:
            self._bars.append(dict(bar))

        closes = [float(b["close"]) for b in self._bars]
        t = int(self._bars[-1]["time"])

        self._ema20   = _ema_series(closes, self.ema_p)
        self._rsi14   = _rsi_wilder(closes, self.rsi_p)
        ema_fast      = _ema_series(closes, self.macd_fast)
        ema_slow      = _ema_series(closes, self.macd_slow)
        macd_line     = None
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

        return {
            "ema20": {"time": t, "value": self._ema20[-1]},
            "rsi14": {"time": t, "value": self._rsi14[-1]},
            "macd":  {"time": t, "macd": macd_line, "signal": self._macd_sig[-1], "hist": macd_hist_v}
        }

    # ---------- sorties pour le chart ----------
    def series_for_chart(self) -> Dict[str, Any]:
        times = [int(b["time"]) for b in self._bars]

        def line(vs: List[Optional[float]]) -> List[Dict[str, float]]:
            start = self._first_valid_index(vs)
            out: List[Dict[str, float]] = []
            for i in range(start, len(vs)):
                v = vs[i]
                if v is None or not isfinite(v):  # on saute les trous (pas de NaN envoyés)
                    continue
                out.append({"time": times[i], "value": float(v)})
            return out

        def hist(vs: List[Optional[float]]) -> List[Dict[str, float]]:
            start = self._first_valid_index(vs)
            out: List[Dict[str, float]] = []
            for i in range(start, len(vs)):
                v = vs[i]
                if v is None or not isfinite(v):
                    continue
                out.append({
                    "time": times[i],
                    "value": float(v),
                    "color": "#22c55e" if v >= 0 else "#ef4444"
                })
            return out

        return {
            "ema20": line(self._ema20),
            "rsi14": line(self._rsi14),
            "macd": {
                "line":   line(self._macd),
                "signal": line(self._macd_sig),
                "hist":   hist(self._macd_hist),
            }
        }

    # ---------- snapshot IA ----------
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

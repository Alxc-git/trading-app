# app/data/resample.py
from .models import Bar

class CandleAggregator:
    def __init__(self, tf_seconds: int):
        self.tf = tf_seconds
        self.slot: int | None = None
        self.o = self.h = self.l = self.c = None
        self.v = 0.0

    def seed(self, bar):  # bar: dict ou Bar
        if isinstance(bar, dict):
            t = int(bar["time"]); o=bar["open"]; h=bar["high"]; l=bar["low"]; c=bar["close"]; v=bar.get("volume", 0.0)
        else:
            t = int(bar.time);    o=bar.open;   h=bar.high;   l=bar.low;   c=bar.close;   v=getattr(bar, "volume", 0.0)
        self.slot = t
        self.o, self.h, self.l, self.c, self.v = float(o), float(h), float(l), float(c), float(v)

    def push_tick(self, ts_epoch: int, price: float, vol: float = 0.0):
        """Retourne (closed_bar | None, current_bar)."""
        slot = (ts_epoch // self.tf) * self.tf
        closed = None

        if self.slot is None:
            self.slot = slot
            p = float(price)
            self.o = self.h = self.l = self.c = p
            self.v = float(vol)
        elif slot > self.slot:
            closed = Bar(time=self.slot, open=self.o, high=self.h, low=self.l, close=self.c, volume=self.v)
            self.slot = slot
            p = float(price)
            self.o = self.h = self.l = self.c = p
            self.v = float(vol)
        else:
            p = float(price)
            self.h = max(self.h, p)
            self.l = min(self.l, p)
            self.c = p
            self.v += float(vol)

        cur = Bar(time=self.slot, open=self.o, high=self.h, low=self.l, close=self.c, volume=self.v)
        return closed, cur

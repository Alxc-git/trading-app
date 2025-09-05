# Pydantic types (Bar, Tick, etc.)

from pydantic import BaseModel
from typing import Optional

class Bar(BaseModel):
    time: int            # epoch seconds (UTC) ou ms (si tu préfères côté JS)
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

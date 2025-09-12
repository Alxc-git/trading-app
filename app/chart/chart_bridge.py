# app/ui/chart_bridge.py
from __future__ import annotations

import json
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class ChartBridge(QObject):
    """
    Bridge Qt <-> JS (QWebChannel).
    - Expose des **signaux** vers JS (seriesLoaded, barUpdated, etc.)
    - Fournit des **slots** côté Python pour faciliter l'émission depuis le code.
      (ex: call bridge.send_bars_batch(bars) → émet seriesLoaded(JSON))
    Côté JS, on se connecte à:
      bridge.seriesLoaded.connect(fn)
      bridge.barUpdated.connect(fn)
      bridge.indicatorsLoaded.connect(fn)
      bridge.indicatorUpdated.connect(fn)
      bridge.indicatorToggle.connect(fn)
      bridge.showLoading.connect(fn)
      bridge.hideLoading.connect(fn)
    """

    # ----- Signaux écoutés par chart.html -----
    seriesLoaded = pyqtSignal(str)       # JSON list[bar]
    barUpdated = pyqtSignal(str)         # JSON bar
    indicatorsLoaded = pyqtSignal(str)   # JSON dict
    indicatorUpdated = pyqtSignal(str)   # JSON dict
    indicatorToggle = pyqtSignal(str)    # JSON dict (toggles)

    showLoading = pyqtSignal()
    hideLoading = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

    # ---------- API Python (helpers) ----------
    @pyqtSlot(list)
    def send_bars_batch(self, bars: list):
        """Emet le batch initial d'un coup (seriesLoaded)."""
        payload = json.dumps(bars, separators=(",", ":"))
        self.seriesLoaded.emit(payload)

    @pyqtSlot(dict)
    def send_bar_update(self, bar: dict):
        """Emet un update (barUpdated)."""
        payload = json.dumps(bar, separators=(",", ":"))
        self.barUpdated.emit(payload)

    @pyqtSlot(dict)
    def send_indicators_all(self, indicators: dict):
        """Emet tout le paquet d'indicateurs (indicatorsLoaded)."""
        payload = json.dumps(indicators or {}, separators=(",", ":"))
        self.indicatorsLoaded.emit(payload)

    @pyqtSlot(dict)
    def send_indicator_update(self, patch: dict):
        """Emet un patch indicateur (indicatorUpdated)."""
        payload = json.dumps(patch or {}, separators=(",", ":"))
        self.indicatorUpdated.emit(payload)

    @pyqtSlot(dict)
    def send_indicator_toggle(self, toggles: dict):
        """Emet des toggles d'affichage (indicatorToggle)."""
        payload = json.dumps(toggles or {}, separators=(",", ":"))
        self.indicatorToggle.emit(payload)

    @pyqtSlot()
    def show_loader(self):
        self.showLoading.emit()

    @pyqtSlot()
    def hide_loader(self):
        self.hideLoading.emit()

    # ---------- API depuis JS -> Python (optionnel) ----------
    # chart.html appelle: bridge.notifyIndicatorClose('rsi'/'macd') si tu le veux.
    indicatorClosed = pyqtSignal(str)

    @pyqtSlot(str)
    def notifyIndicatorClose(self, key: str):
        """Reçoit un événement JS lorsqu'un pane indicateur est fermé depuis le HTML."""
        self.indicatorClosed.emit(key)

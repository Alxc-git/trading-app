# app/chart/chart_bridge.py
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

class ChartBridge(QObject):
    # Overlay de chargement
    showLoading = pyqtSignal()
    hideLoading = pyqtSignal()

    # Prix (historique + tick)
    seriesLoaded = pyqtSignal(str)   # JSON array of bars
    barUpdated   = pyqtSignal(str)   # JSON bar

    # Indicateurs (historique + tick)
    indicatorsLoaded = pyqtSignal(str)  # JSON dict {ema20:[], rsi14:[], macd:{line:[],signal:[],hist:[]}}
    indicatorUpdated = pyqtSignal(str)  # JSON dict {"ema20":{time,value}, "rsi14":{...}, "macd":{time,macd,signal,hist}}

    # Toggle visibilité (Python -> JS)
    indicatorToggle  = pyqtSignal(str)  # JSON dict {"ema20":bool, "rsi":bool, "macd":bool}

    # Demandes JS -> Python (fermeture pane via ✕)
    indicatorCloseRequested = pyqtSignal(str)  # "rsi" | "macd" | "ema20"

    @pyqtSlot(str)
    def notifyIndicatorClose(self, which: str):
        """Appelé depuis JS quand l’utilisateur clique sur ✕ d’un pane indicateur."""
        self.indicatorCloseRequested.emit(which)

# app/chart/chart_view.py
import json, pathlib
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl
from .chart_bridge import ChartBridge

class ChartView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = ChartBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)

        html_path = pathlib.Path(__file__).with_name("chart.html")
        self.load(QUrl.fromLocalFile(str(html_path)))

    def load_series(self, bars: list[dict]):
        self.bridge.seriesLoaded.emit(json.dumps(bars))

    def update_bar(self, bar: dict):
        self.bridge.barUpdated.emit(json.dumps(bar))

    # Overlay depuis Python
    def show_loading(self):
        self.bridge.showLoading.emit()

    def hide_loading(self):
        self.bridge.hideLoading.emit()

    # 👉 Pilotage du bouton LIVE JS
    def go_live(self):
        # appelle la fonction JS goLive() définie dans chart.html
        try:
            self.page().runJavaScript("typeof goLive==='function' && goLive();")
        except Exception:
            pass
    
    def load_indicators(self, indicators: dict):
        """Push les séries complètes (EMA/RSI/MACD) vers le JS."""
        import json
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.indicatorsLoaded.emit(json.dumps(indicators))

    def update_indicator_points(self, points: dict):
        """Push un tick d'indicateur (dernier point) vers le JS."""
        import json
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.indicatorUpdated.emit(json.dumps(points))

    def set_indicator_visibility(self, flags: dict):
        """flags = {"ema20":bool, "rsi":bool, "macd":bool} → JS montre/cache."""
        import json
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.indicatorToggle.emit(json.dumps(flags))

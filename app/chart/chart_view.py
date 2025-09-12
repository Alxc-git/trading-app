# app/chart/chart_view.py
from __future__ import annotations

import os
from PyQt6.QtCore import QUrl, QFileInfo, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel


from app.chart.chart_bridge import ChartBridge

class ChartView(QWebEngineView):
    """
    WebView qui charge chart.html et expose un ChartBridge via QWebChannel sous le nom 'bridge'.
    Fournit aussi des helpers que MainWindow appelle, qui forwardent vers le bridge.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        # Bridge + channel
        self.bridge = ChartBridge(self)
        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)

        # Charge le HTML
        html_path = os.path.join(os.path.dirname(__file__), "chart.html")
        self.load(QUrl.fromLocalFile(QFileInfo(html_path).absoluteFilePath()))

    # --------- Helpers appelés depuis MainWindow ---------
    def show_loading(self):
        self.bridge.show_loader()

    def hide_loading(self):
        self.bridge.hide_loader()

    def load_series(self, bars: list[dict]):
        """Batch initial → JS (seriesLoaded)"""
        self.bridge.send_bars_batch(bars)

    def update_bar(self, bar: dict):
        """Mise à jour live → JS (barUpdated)"""
        self.bridge.send_bar_update(bar)

    def load_indicators(self, indicators: dict):
        """Envoi complet des indicateurs → JS (indicatorsLoaded)"""
        self.bridge.send_indicators_all(indicators or {})

    def update_indicator_points(self, patch: dict):
        """
        Mise à jour incrémentale d'indicateurs (points/markers) → JS (indicatorUpdated).
        Si ton patch est déjà structuré côté Engine (ex: {"markers": {...}}), forward tel quel.
        """
        self.bridge.send_indicator_update(patch or {})

    def set_indicator_visibility(self, flags: dict):
        """Toggles d’affichage → JS (indicatorToggle)"""
        self.bridge.send_indicator_toggle(flags or {})

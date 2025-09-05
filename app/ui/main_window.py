# app/ui/main_window.py
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QToolBar,
    QComboBox, QSizePolicy, QToolButton, QMenu, QLabel, QHBoxLayout
)

from app.chart.chart_view import ChartView
from app.data.mt5_source import DataWorker
from app.chat.chat_panel import ChatPanel
from app.chat.chat_controller import ChatController
from app.news.news_service import NewsService
from app.indicators.ta import IndicatorEngine


DARK_QSS = """
QMainWindow, QWidget { background-color: #0e1116; color: #cfd3dc; }
QToolBar { background: #0b1220; border-bottom: 1px solid #1f2937; spacing: 8px; padding: 6px; }
QComboBox { background: #111827; color: #e5e7eb; border: 1px solid #334155; padding: 5px 10px; border-radius: 6px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background: #0b1220; color: #e5e7eb; }
QTextEdit, QTextBrowser { background: #0b1220; border: 1px solid #1f2937; border-radius: 8px; padding: 6px; color: #e5e7eb; }
QLineEdit { background: #0b1220; border: 1px solid #334155; padding: 6px 8px; border-radius: 6px; color: #e5e7eb; }
QSplitter::handle { background: #0e1116; width: 4px; }
QSplitter::handle:hover { background: #1f2937; }
QToolButton { background:#111827; color:#e5e7eb; border:1px solid #334155; padding:5px 10px; border-radius:6px; }
"""

def _flags(ema: bool, rsi: bool, macd: bool) -> dict:
    return {"ema20": ema, "rsi": rsi, "macd": macd}


class MainWindow(QMainWindow):
    paramsChanged = pyqtSignal(str, str)
    requestShutdown = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trading App")
        self.resize(1400, 900)
        self.setStyleSheet(DARK_QSS)

        # --- UI principal ---
        self.chart = ChartView()
        self.side  = ChatPanel()
        self.side.setMinimumWidth(420)

        # ---- Actus (réelles) ----
        self.news_service = NewsService(self)
        # HTML prêt à afficher (liste d'actus) → panneau de droite
        self.news_service.htmlReady.connect(self.side.demo_fill_news)
        # itemsReady n'existe peut-être pas dans ta version → on ne connecte que si présent
        if hasattr(self.news_service, "itemsReady"):
            self.news_service.itemsReady.connect(self._on_news_items)
        # refresh toutes les 3 minutes
        self.news_service.start(interval_ms=180_000)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.chart)
        splitter.addWidget(self.side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self._splitter = splitter

        self._saved_sizes_px: list[int] | None = None
        QTimer.singleShot(0, self._apply_initial_splitter_sizes)

        # --- Toolbar ---
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        # 1) LOGO À GAUCHE
        logo_path = Path(__file__).resolve().parents[2] / "assets" / "corec-logo.png"
        logo_h = 28
        self._logo_lbl = QLabel()
        pm = QPixmap(str(logo_path))
        if not pm.isNull():
            self._logo_lbl.setPixmap(pm.scaledToHeight(logo_h, Qt.TransformationMode.SmoothTransformation))
        self._logo_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._logo_lbl.setContentsMargins(4, 0, 10, 0)

        logo_wrap = QWidget()
        lw = QHBoxLayout(logo_wrap); lw.setContentsMargins(0, 0, 0, 0); lw.setSpacing(0)
        lw.addWidget(self._logo_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        tb.addWidget(logo_wrap)

        # 2) COMBOS & MENU INDICATEURS
        self.sym = QComboBox(); self.sym.addItems(["EURUSD","GBPUSD","USDJPY","USDCAD","AUDUSD"])
        self.tf  = QComboBox(); self.tf.addItems(["M1","M5","M30"])

        self.indBtn = QToolButton()
        self.indBtn.setText("Indicateurs ▾")
        self.indBtn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.indBtn)

        # Actions cochables
        self.actEMA  = QAction("EMA 20", self, checkable=True)
        self.actRSI  = QAction("RSI 14", self, checkable=True)
        self.actMACD = QAction("MACD (12,26,9)", self, checkable=True)
        # Actions rapides
        self.actALL = QAction("Tout afficher (ALL)", self)
        self.actOFF = QAction("Tout masquer (OFF)", self)

        menu.addAction(self.actEMA)
        menu.addAction(self.actRSI)
        menu.addAction(self.actMACD)
        menu.addSeparator()
        menu.addAction(self.actALL)
        menu.addAction(self.actOFF)

        self.indBtn.setMenu(menu)
        self.indBtn.setStyleSheet(
            "QToolButton::menu-indicator{image:none;width:0px;height:0px;} QToolButton{padding-right:12px;}"
        )

        tb.addWidget(self.sym)
        tb.addWidget(self.tf)
        tb.addWidget(self.indBtn)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self.toggle_side_act = QAction("🎛 Panneau", self, checkable=True)
        self.toggle_side_act.setChecked(True)
        self.toggle_side_act.toggled.connect(self._toggle_side_panel)
        tb.addAction(self.toggle_side_act)

        # (facultatif) si NewsService supporte MAJ par symbole/TF → connecter APRÈS création des combos
        if hasattr(self.news_service, "set_params"):
            self.paramsChanged.connect(self.news_service.set_params)
        elif hasattr(self.news_service, "set_symbol"):
            self.sym.currentTextChanged.connect(self.news_service.set_symbol)

        # --- Thread & worker (flux marché) ---
        self.thread = QThread(self)
        self.worker = DataWorker(self.sym.currentText(), self.tf.currentText(), depth=5000)
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.started.connect(self.worker.start)

        # Indicateurs
        self.indic = IndicatorEngine()

        # Data routes
        self.worker.historyReady.connect(self._on_history_ready)
        self.worker.barReady.connect(self._on_bar)

        # Panneau IA
        self._chat = ChatController(self.side)
        self.worker.historyReady.connect(self._chat.on_history)

        # Signaux UI → worker & IA
        self.paramsChanged.connect(self.worker.set_params, Qt.ConnectionType.QueuedConnection)
        self.paramsChanged.connect(self._chat.set_params)
        self.requestShutdown.connect(self.worker.shutdown, Qt.ConnectionType.QueuedConnection)

        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

        self.chart.show_loading()
        QTimer.singleShot(0, lambda: self.paramsChanged.emit(self.sym.currentText(), self.tf.currentText()))

        # Debounce pour symbol/TF
        self._debounce = QTimer(self); self._debounce.setSingleShot(True); self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._emit_params)
        self.sym.currentIndexChanged.connect(lambda *_: self._debounce.start())
        self.tf.currentIndexChanged.connect(lambda *_: self._debounce.start())

        # Connexions menu indicateurs
        self.actEMA.toggled.connect(self._on_menu_toggled)
        self.actRSI.toggled.connect(self._on_menu_toggled)
        self.actMACD.toggled.connect(self._on_menu_toggled)
        self.actALL.triggered.connect(self._on_all)
        self.actOFF.triggered.connect(self._on_off)

        # JS → Python : fermeture via ✕ dans les panes
        if hasattr(self.chart, "bridge") and self.chart.bridge:
            self.chart.bridge.indicatorCloseRequested.connect(self._on_indicator_closed_from_js)

        # stockage local actus JSON (si itemsReady dispo)
        self._news_recent: list[dict] = []

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.stop_feed)

    # --- Helpers indicateurs ---
    def _current_flags(self) -> dict:
        return _flags(self.actEMA.isChecked(), self.actRSI.isChecked(), self.actMACD.isChecked())

    def _apply_flags(self, flags: dict):
        try:
            self.chart.set_indicator_visibility(flags)
        except Exception:
            pass

    def _on_menu_toggled(self, _checked: bool):
        self._apply_flags(self._current_flags())

    def _on_all(self):
        for act in (self.actEMA, self.actRSI, self.actMACD):
            act.blockSignals(True); act.setChecked(True); act.blockSignals(False)
        self._apply_flags(self._current_flags())

    def _on_off(self):
        for act in (self.actEMA, self.actRSI, self.actMACD):
            act.blockSignals(True); act.setChecked(False); act.blockSignals(False)
        self._apply_flags(self._current_flags())

    def _on_indicator_closed_from_js(self, which: str):
        which = (which or "").lower()
        if   which == "rsi":   target = self.actRSI
        elif which == "macd":  target = self.actMACD
        elif which == "ema20": target = self.actEMA
        else: return
        target.blockSignals(True); target.setChecked(False); target.blockSignals(False)
        self._apply_flags(self._current_flags())

    # --- Data handlers ---
    def _emit_params(self):
        self.chart.show_loading()
        self.paramsChanged.emit(self.sym.currentText(), self.tf.currentText())

    def _on_history_ready(self, bars: list[dict]):
        self.chart.load_series(bars)
        self.indic.set_history(bars)
        try:
            self.chart.load_indicators(self.indic.series_for_chart())
            self._apply_flags(self._current_flags())
        except Exception:
            pass
        if hasattr(self._chat, "set_indicator_snapshot"):
            self._chat.set_indicator_snapshot(self.indic.latest_snapshot().__dict__)
        QTimer.singleShot(0, self.chart.hide_loading)

    def _on_bar(self, bar: dict):
        self.chart.update_bar(bar)
        pts = self.indic.on_bar(bar)
        if pts:
            try:
                self.chart.update_indicator_points(pts)
            except Exception:
                pass
        self._chat.on_bar(bar)
        if hasattr(self._chat, "set_indicator_snapshot"):
            self._chat.set_indicator_snapshot(self.indic.latest_snapshot().__dict__)

    # --- Actus JSON (optionnel si itemsReady existe) ---
    def _on_news_items(self, json_str: str):
        """Garde sous la main les actus en JSON (pour IA/markers plus tard)."""
        try:
            import json
            items = json.loads(json_str) or []
        except Exception:
            items = []
        self._news_recent = items
        if hasattr(self, "_chat") and hasattr(self._chat, "set_news_items"):
            try:
                self._chat.set_news_items(items)
            except Exception:
                pass

    # --- Layout helpers ---
    def _apply_initial_splitter_sizes(self):
        total = max(800, self._splitter.width() or self.width())
        left = int(total * 0.72); right = max(360, total - left)
        self._splitter.setSizes([left, right])

    def _toggle_side_panel(self, checked: bool):
        sizes = self._splitter.sizes()
        if checked:
            if self._saved_sizes_px and sum(self._saved_sizes_px) > 0:
                self._splitter.setSizes(self._saved_sizes_px)
            else:
                self._apply_initial_splitter_sizes()
            self.side.show()
        else:
            self._saved_sizes_px = sizes[:]
            self._splitter.setSizes([sizes[0] + sizes[1], 0])
            self.side.hide()

    # --- Shutdown ---
    def closeEvent(self, e):
        # Stopper NewsService proprement si dispo
        try:
            if hasattr(self, "news_service") and hasattr(self.news_service, "stop"):
                self.news_service.stop()
        except Exception:
            pass
        self.stop_feed()
        super().closeEvent(e)

    def stop_feed(self):
        if not self.thread:
            return
        try:
            from PyQt6.QtCore import QMetaObject, Qt as _Qt
            QMetaObject.invokeMethod(self.worker, "shutdown", _Qt.ConnectionType.QueuedConnection)
        except Exception:
            try:
                self.worker.shutdown()
            except Exception:
                pass

        if self.thread.isRunning():
            if not self.thread.wait(5000):
                self.thread.quit()
                if not self.thread.wait(3000):
                    self.thread.terminate(); self.thread.wait(1000)

        try:
            self.thread.deleteLater()
        except Exception:
            pass
        self.worker = None
        self.thread = None

# app/ui/main_window.py
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QToolBar,
    QComboBox, QSizePolicy, QToolButton, QMenu, QLabel, QHBoxLayout
)

from PyQt6.QtWidgets import QStatusBar

from app.chart.chart_view import ChartView
from app.data.mt5_source import DataWorker
from app.chat.chat_panel import ChatPanel
from app.chat.chat_controller import ChatController
from app.news.news_service import NewsService
from app.indicators.ta import IndicatorEngine

DARK_QSS = """
    /* --------- Global --------- */
    QMainWindow, QWidget { background-color:#0e1116; color:#cfd3dc; }
    * { font-family: "Inter", "Segoe UI", system-ui; font-size:13px; }

    /* --------- Toolbar chips --------- */
    QToolBar { background:#0b1220; border-bottom:1px solid #1f2937; spacing:10px; padding:6px; }
    QComboBox {
    background:#0f172a; color:#e5e7eb; border:1px solid #334155;
    padding:6px 10px; border-radius:999px; /* pill */
    }
    QComboBox::drop-down { border:none; width:0; }
    QComboBox QAbstractItemView { background:#0b1220; color:#e5e7eb; border:1px solid #1f2937; }

    /* Boutons (panneau, menu indicateurs, etc.) */
    QToolButton, QPushButton {
    background:#111827; color:#e5e7eb; border:1px solid #334155;
    padding:6px 12px; border-radius:10px;
    }
    QToolButton:hover, QPushButton:hover { background:#0b1220; }
    QToolButton:checked { background:#0b1220; border-color:#475569; }

    /* --------- Splitter --------- */
    QSplitter::handle { background:#0e1116; width:5px; }
    QSplitter::handle:hover { background:#1f2937; }

    /* --------- Text areas (chat/news) --------- */
    QTextBrowser {
    background:#0f131a; color:#e5e7eb; border:1px solid #1f2937; border-radius:10px;
    }
    QPlainTextEdit {
    background:transparent; color:#e5e7eb; border:none;
    }

    /* --------- Scrollbars --------- */
    QScrollBar:vertical {
    background:transparent; width:10px; margin:2px; border:none;
    }
    QScrollBar::handle:vertical {
    background:#293241; min-height:24px; border-radius:6px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
    QScrollBar:horizontal { height:10px; }
    QScrollBar::handle:horizontal { background:#293241; border-radius:6px; }

    /* --------- Chips “état” --------- */
    .Badge {
    background:#111827; border:1px solid #334155; color:#cfd3dc;
    padding:2px 8px; border-radius:999px;
    }
    .Badge--ok { background:#0a1f16; border-color:#1f7a4f; color:#8ff0b8; }
    .Badge--warn { background:#1f1a0a; border-color:#7a611f; color:#ffd479; }
    .Badge--err { background:#1f0a0a; border-color:#7a1f1f; color:#ff9a9a; }
"""

def _flags(ema: bool, rsi: bool, macd: bool, show_tr: bool, show_vbo: bool) -> dict:
    return {"ema20": ema, "rsi": rsi, "macd": macd, "showTR": show_tr, "showVB": show_vbo}

class MainWindow(QMainWindow):
    paramsChanged = pyqtSignal(str, str)
    requestShutdown = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trading App")
        self.resize(1400, 900)
        self.setStyleSheet(DARK_QSS)

        self.chart = ChartView()
        self.side  = ChatPanel()
        self.side.setMinimumWidth(420)

        # News
        self.news_service = NewsService(self)
        self.news_service.htmlReady.connect(self.side.demo_fill_news)
        if hasattr(self.news_service, "itemsReady"):
            self.news_service.itemsReady.connect(self._on_news_items)
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

        # Toolbar
        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)

        logo_path = Path(__file__).resolve().parents[2] / "assets" / "corec-logo.png"
        self._logo_lbl = QLabel(); pm = QPixmap(str(logo_path))
        if not pm.isNull(): self._logo_lbl.setPixmap(pm.scaledToHeight(28, Qt.TransformationMode.SmoothTransformation))
        self._logo_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._logo_lbl.setContentsMargins(4,0,10,0)
        logo_wrap = QWidget(); lw = QHBoxLayout(logo_wrap); lw.setContentsMargins(0,0,0,0); lw.addWidget(self._logo_lbl,0,Qt.AlignmentFlag.AlignVCenter)
        tb.addWidget(logo_wrap)

        self.sym = QComboBox(); self.sym.addItems(["EURUSD","GBPUSD","USDJPY","USDCAD","AUDUSD"])
        self.tf  = QComboBox(); self.tf.addItems(["M1","M5","M30"])

        self.indBtn = QToolButton(); self.indBtn.setText("Indicateurs ▾")
        self.indBtn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.indBtn)

        # Panes OFF
        self.actEMA  = QAction("EMA 20", self, checkable=True); self.actEMA.setChecked(False)
        self.actRSI  = QAction("RSI 14", self, checkable=True); self.actRSI.setChecked(False)
        self.actMACD = QAction("MACD (12,26,9)", self, checkable=True); self.actMACD.setChecked(False)

        # Flèches OFF
        self.actSigTR  = QAction("Flèches Trend Rider", self, checkable=True); self.actSigTR.setChecked(False)
        self.actSigVBO = QAction("Flèches Vol. Breakout", self, checkable=True); self.actSigVBO.setChecked(False)

        for a in (self.actEMA, self.actRSI, self.actMACD, self.actSigTR, self.actSigVBO):
            menu.addAction(a)

        menu.addSeparator()
        self.actALL = QAction("Tout afficher (ALL)", self)
        self.actOFF = QAction("Tout masquer (OFF)", self)
        menu.addAction(self.actALL); menu.addAction(self.actOFF)

        self.indBtn.setMenu(menu)
        self.indBtn.setStyleSheet("QToolButton::menu-indicator{image:none;width:0px;height:0px;} QToolButton{padding-right:12px;}")

        tb.addWidget(self.sym); tb.addWidget(self.tf); tb.addWidget(self.indBtn)

        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); tb.addWidget(spacer)

        self.toggle_side_act = QAction("🎛 Panneau", self, checkable=True)
        self.toggle_side_act.setChecked(True)
        self.toggle_side_act.toggled.connect(self._toggle_side_panel)
        tb.addAction(self.toggle_side_act)

        if hasattr(self.news_service, "set_params"):
            self.paramsChanged.connect(self.news_service.set_params)
        elif hasattr(self.news_service, "set_symbol"):
            self.sym.currentTextChanged.connect(self.news_service.set_symbol)

        # Worker / data
        self.thread = QThread(self)
        self.worker = DataWorker(self.sym.currentText(), self.tf.currentText(), depth=5000)
        # après avoir créé:
        # self.chart = ChartView()
        # self.worker = DataWorker(...)

        # batch initial -> JS (seriesLoaded)
        self.worker.historyReady.connect(self.chart.bridge.send_bars_batch)
        # updates live -> JS (barUpdated)
        self.worker.barReady.connect(self.chart.bridge.send_bar_update)

        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.started.connect(self.worker.start)

        self.indic = IndicatorEngine()

        self.worker.historyReady.connect(self._on_history_ready)
        self.worker.barReady.connect(self._on_bar)

        self._chat = ChatController(self.side)
        self.worker.historyReady.connect(self._chat.on_history)

        self.paramsChanged.connect(self.worker.set_params, Qt.ConnectionType.QueuedConnection)
        self.paramsChanged.connect(self._chat.set_params)
        self.requestShutdown.connect(self.worker.shutdown, Qt.ConnectionType.QueuedConnection)

        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

        self.chart.show_loading()
        QTimer.singleShot(0, lambda: self.paramsChanged.emit(self.sym.currentText(), self.tf.currentText()))

        # debounce
        self._debounce = QTimer(self); self._debounce.setSingleShot(True); self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._emit_params)
        self.sym.currentIndexChanged.connect(lambda *_: self._debounce.start())
        self.tf.currentIndexChanged.connect(lambda *_: self._debounce.start())

        for a in (self.actEMA, self.actRSI, self.actMACD, self.actSigTR, self.actSigVBO):
            a.toggled.connect(self._on_menu_toggled)
        self.actALL.triggered.connect(self._on_all)
        self.actOFF.triggered.connect(self._on_off)

        if hasattr(self.chart, "bridge") and self.chart.bridge:
            self.chart.bridge.indicatorClosed.connect(self._on_indicator_closed_from_js)

        self._news_recent: list[dict] = []

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.stop_feed)

    # ---------- helpers ----------
    def _current_flags(self) -> dict:
        return _flags(self.actEMA.isChecked(), self.actRSI.isChecked(), self.actMACD.isChecked(),
                      self.actSigTR.isChecked(), self.actSigVBO.isChecked())

    def _apply_flags(self, flags: dict):
        try:
            self.chart.set_indicator_visibility(flags)
        except Exception:
            pass

    def _on_menu_toggled(self, _checked: bool):
        self._apply_flags(self._current_flags())

    def _on_all(self):
        for act in (self.actEMA, self.actRSI, self.actMACD, self.actSigTR, self.actSigVBO):
            act.blockSignals(True); act.setChecked(True); act.blockSignals(False)
        self._apply_flags(self._current_flags())

    def _on_off(self):
        for act in (self.actEMA, self.actRSI, self.actMACD, self.actSigTR, self.actSigVBO):
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

    # ---------- data ----------
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

    # ---------- news ----------
    def _on_news_items(self, json_str: str):
        try:
            import json; items = json.loads(json_str) or []
        except Exception:
            items = []
        self._news_recent = items
        if hasattr(self, "_chat") and hasattr(self._chat, "set_news_items"):
            try: self._chat.set_news_items(items)
            except Exception: pass

    # ---------- layout ----------
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

    # ---------- shutdown ----------
    def closeEvent(self, e):
        try:
            if hasattr(self, "news_service") and hasattr(self.news_service, "stop"):
                self.news_service.stop()
        except Exception:
            pass
        self.stop_feed()
        super().closeEvent(e)

    def stop_feed(self):
        if not self.thread: return
        try:
            from PyQt6.QtCore import QMetaObject, Qt as _Qt
            QMetaObject.invokeMethod(self.worker, "shutdown", _Qt.ConnectionType.QueuedConnection)
        except Exception:
            try: self.worker.shutdown()
            except Exception: pass

        if self.thread.isRunning():
            if not self.thread.wait(5000):
                self.thread.quit()
                if not self.thread.wait(3000):
                    self.thread.terminate(); self.thread.wait(1000)

        try: self.thread.deleteLater()
        except Exception: pass
        self.worker = None; self.thread = None

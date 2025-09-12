# app/chat/chat_panel.py
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QTextBrowser, QPushButton,
    QTabWidget, QLabel, QPlainTextEdit, QSizePolicy, QSpacerItem
)
from PyQt6.QtGui import QFontMetrics, QTextOption   # ← ajoute QTextOption



class AutoGrowInput(QPlainTextEdit):
    """Zone de saisie: 1 ligne au départ, grandit jusqu’à 5 lignes, sans scrollbars.
       Entrée = envoyer (Shift+Entrée = nouvelle ligne)."""
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setWordWrapMode(self.wordWrapMode())  # par défaut, soft-wrap
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setPlaceholderText("Pose ta question (Groq AI)…")
        self.setStyleSheet("""
            QPlainTextEdit {
                background: transparent;
                color: #e5e7eb;
                padding: 6px 10px;          /* un peu d’air, le bouton est à droite */
            }
        """)
        
        # hauteurs min/max
        self._line_h = QFontMetrics(self.font()).lineSpacing()
        self._min_h  = int(self._line_h + 14)     # ~1 ligne
        self._max_h  = int(self._line_h * 5 + 16) # ~5 lignes
        self.setMinimumHeight(self._min_h)
        self.setMaximumHeight(self._max_h)

        # Ajuste la hauteur quand le contenu change
        self.textChanged.connect(self._recalc_height)
        self._recalc_height()

    def _recalc_height(self):
        doc_h = int(self.document().size().height()) + 10
        h = max(self._min_h, min(self._max_h, doc_h))
        if h != self.height():
            self.setFixedHeight(h)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            text = self.toPlainText().strip()
            if text:
                e.accept()
                self.clear()
                self.submitted.emit(text)
                return
        super().keyPressEvent(e)


class ChatPanel(QWidget):
    """Panneau à onglets: Chat (Groq) + Actus. Bouton rond ➤ dans le champ."""
    sendRequested = pyqtSignal(str)  # émis quand on envoie un message

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---------- Tabs ----------
        self.tabs = QTabWidget(self)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #1f2937; }
            QTabBar::tab {
                background: #0b1220; color: #e5e7eb;
                padding: 6px 12px; border-top-left-radius: 6px; border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { background: #111827; }
        """)

        # ---------- Onglet Chat ----------
        chat = QWidget(); chat_lay = QVBoxLayout(chat); chat_lay.setContentsMargins(8,8,8,8)
        self.view = QTextBrowser()
        
        self.view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)  # ← retour à la ligne
        self.view.setOpenLinks(False); self.view.setOpenExternalLinks(False)
        
        self.view.setStyleSheet("""
            QTextBrowser {
                background: #0f131a; color: #e5e7eb; border: 1px solid #1f2937; border-radius: 8px;
                padding: 8px;
            }
        """)

        # “barre de saisie” = un cadre foncé + input (translucide) + bouton ➤ à droite
        box = QFrame(); box.setObjectName("InputBox")
        box.setStyleSheet("""
            QFrame#InputBox {
                background: #121722; border: 1px solid #232a36; border-radius: 16px;
            }
        """)
        row = QHBoxLayout(box)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(6)

        self.input = AutoGrowInput()
        self.send_btn = QPushButton("➤")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #e5e7eb;           /* cercle blanc/gris */
                color: #0F131A;                 /* flèche */
                border: none; border-radius: 18px;
                font: 700 14px "Segoe UI", "Inter", system-ui;
            }
            QPushButton:hover   { background: #f3f4f6; }  /* un peu plus clair au survol */
            QPushButton:pressed { background: #d1d5db; }  /* léger appui */
            QPushButton:disabled{ background: #2a2f3a; color: #9aa4b2; }
        """)


        # étire l’input, bouton collé à droite
        row.addWidget(self.input, 1)
        row.addItem(QSpacerItem(6, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        # petit état “envoi…”
        self.status = QLabel("")
        self.status.setStyleSheet("QLabel{ color:#9aa4b2; }")

        chat_lay.addWidget(self.view, 1)
        chat_lay.addWidget(box, 0)
        chat_lay.addWidget(self.status, 0)

        # ---------- Onglet Actus ----------
        news = QWidget(); news_lay = QVBoxLayout(news); news_lay.setContentsMargins(8,8,8,8)
        self.news_view = QTextBrowser()
        self.news_view.setOpenExternalLinks(True)
        self.news_view.setStyleSheet("""
            QTextBrowser {
                background: #0f131a; color:#e5e7eb; border: 1px solid #1f2937; border-radius: 8px;
                padding: 10px;
            }
        """)
        self.news_view.setHtml(
            "<h3 style='margin-top:0'>Actualités économiques</h3>"
            "<p><i>À venir :</i> connexion API actus, résumé automatique et alertes.</p>"
        )
        news_lay.addWidget(self.news_view)

        self.tabs.addTab(chat, "Chat")
        self.tabs.addTab(news, "Actus")

        # ---------- Wrapper ----------
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0,0,0,0)
        wrap.addWidget(self.tabs)

        # ---------- Connexions ----------
        self.send_btn.clicked.connect(self._emit_send)
        self.input.submitted.connect(self._emit_send)

    # ---------- API utilisée par le contrôleur ----------
    def append_user(self, text: str):
        self.view.append(f"<div style='color:#93c5fd'><b>👤 Toi</b> : {self._esc(text)}</div>")

    def append_assistant(self, text: str):
        # on supprime le “Envoi à l’IA…” s’il est visible
        if self.status.text():
            self.status.setText("")
        self.view.append(f"<div style='color:#e5e7eb'><b>🤖 IA</b> : {self._esc(text)}</div>")

    def append_note(self, text: str):
        self.status.setText(text)

    def set_busy(self, busy: bool):
        self.send_btn.setDisabled(busy)
        self.status.setText("Envoi à l’IA…" if busy else "")

    def demo_fill_news(self, html: str | None = None):
        """Juste un helper pour remplir l'onglet Actus, si besoin."""
        if html:
            self.news_view.setHtml(html)

    # ---------- interne ----------
    def _emit_send(self, txt: str | None = None):
        if isinstance(txt, str):
            text = txt.strip()
        else:
            text = self.input.toPlainText().strip()
            self.input.clear()
        if not text:
            return
        self.append_user(text)
        self.set_busy(True)
        self.sendRequested.emit(text)

    @staticmethod
    def _esc(s: str) -> str:
        return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

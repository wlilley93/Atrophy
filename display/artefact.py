"""Artefact overlay and gallery for The Atrophied Mind.

ArtefactOverlay: full-bleed overlay that displays HTML, images, or video artefacts.
ArtefactGallery: scrollable modal listing recent artefacts with search/filter.
"""
import json
import os
from pathlib import Path

from PyQt5.QtCore import (
    Qt, QUrl, QPropertyAnimation, QEasingCurve, QSize, pyqtSignal,
)
from PyQt5.QtGui import QColor, QPainter, QPixmap, QFont, QImage
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QGraphicsOpacityEffect, QApplication,
)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

_BG = QColor(20, 20, 20)
_RADIUS = 10

_GALLERY_STYLE = """
QWidget#artefactGallery {
    background: rgba(15, 15, 15, 0.97);
}
QLabel { color: rgba(255,255,255,0.7); }
QLineEdit {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: white;
    padding: 6px 10px;
    font-size: 13px;
}
QPushButton#closeButton {
    background: rgba(255,255,255,0.06);
    border: none;
    border-radius: 16px;
    color: rgba(255,255,255,0.5);
    font-size: 18px;
}
QPushButton#closeButton:hover {
    background: rgba(180,80,80,0.4);
    color: white;
}
QPushButton#filterBtn {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    color: rgba(255,255,255,0.5);
    padding: 4px 12px;
    font-size: 11px;
}
QPushButton#filterBtn:checked {
    background: rgba(255,255,255,0.15);
    color: rgba(255,255,255,0.9);
    border-color: rgba(255,255,255,0.3);
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 6px;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.15);
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class _CloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("×", parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { background: rgba(0,0,0,0.6); color: #aaa;"
            "  border: none; border-radius: 16px; font-size: 18px; }"
            "QPushButton:hover { background: rgba(180,80,80,0.8); color: white; }"
        )


# ── Artefact Overlay ──

class ArtefactOverlay(QWidget):
    """Full-bleed overlay that displays an artefact (HTML, image, or video)."""
    dismissed = pyqtSignal()  # emitted when dismiss animation completes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setVisible(False)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._active = False
        self._current_path = None  # path to artefact dir

        # Web view for HTML artefacts (lazy — created on first use)
        self._web = None

        # Image label
        self._img_label = QLabel(self)
        self._img_label.setAlignment(Qt.AlignCenter)
        self._img_label.setVisible(False)

        # Close button
        self._close_btn = _CloseButton(self)
        self._close_btn.clicked.connect(self.dismiss)
        self._close_btn.raise_()

    def show_artefact(self, artefact_dir: str, artefact_type: str = None,
                      file_path: str = None):
        """Load and display an artefact."""
        self._current_path = artefact_dir

        # Read metadata if type not provided
        if not artefact_type or not file_path:
            meta_path = os.path.join(artefact_dir, "artefact.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                artefact_type = artefact_type or meta.get("type", "html")
                file_path = file_path or meta.get("file", "")

        # Hide all content widgets
        self._img_label.setVisible(False)
        if self._web:
            self._web.setVisible(False)

        if artefact_type == "html":
            if not file_path:
                file_path = os.path.join(artefact_dir, "index.html")
            if HAS_WEBENGINE:
                if not self._web:
                    self._web = QWebEngineView(self)
                    self._web.page().setBackgroundColor(_BG)
                self._web.setGeometry(0, 0, self.width(), self.height())
                self._web.load(QUrl.fromLocalFile(file_path))
                self._web.setVisible(True)

        elif artefact_type == "image":
            if file_path and os.path.exists(file_path):
                pixmap = QPixmap(file_path)
                scaled = pixmap.scaled(
                    self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._img_label.setPixmap(scaled)
                self._img_label.setGeometry(0, 0, self.width(), self.height())
                self._img_label.setVisible(True)

        elif artefact_type == "video":
            # For video, use a web view with a video tag
            if file_path and os.path.exists(file_path) and HAS_WEBENGINE:
                if not self._web:
                    self._web = QWebEngineView(self)
                    self._web.page().setBackgroundColor(_BG)
                html = f"""<!DOCTYPE html>
<html><head><style>
body {{ margin:0; background:#141414; display:flex; align-items:center; justify-content:center; height:100vh; }}
video {{ max-width:100%; max-height:100%; border-radius:8px; }}
</style></head><body>
<video src="{QUrl.fromLocalFile(file_path).toString()}" autoplay loop controls></video>
</body></html>"""
                self._web.setGeometry(0, 0, self.width(), self.height())
                self._web.setHtml(html)
                self._web.setVisible(True)

        # Fade in
        self._active = True
        self.setVisible(True)
        self.raise_()
        self._close_btn.raise_()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def dismiss(self):
        self._active = False
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def is_active(self) -> bool:
        return self._active

    def current_path(self) -> str | None:
        return self._current_path

    def reposition(self, x: int, y: int, w: int, h: int):
        self.setGeometry(x, y, w, h)
        if self._web:
            self._web.setGeometry(0, 0, w, h)
        self._img_label.setGeometry(0, 0, w, h)
        self._close_btn.move(w - 40, 8)

    def _on_fade_finished(self):
        if not self._active:
            self.setVisible(False)
            self.dismissed.emit()
            # Free web view memory when not showing
            if self._web:
                self._web.setHtml("")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(_BG)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), _RADIUS, _RADIUS)
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._web and self._web.isVisible():
            self._web.setGeometry(0, 0, self.width(), self.height())
        if self._img_label.isVisible():
            self._img_label.setGeometry(0, 0, self.width(), self.height())
        self._close_btn.move(self.width() - 40, 8)


# ── Artefact Gallery ──

class ArtefactGallery(QWidget):
    """Full-screen modal listing recent artefacts with search and filter."""

    def __init__(self, index_file: str, on_select=None, parent=None):
        super().__init__(parent)
        self.setObjectName("artefactGallery")
        self.setStyleSheet(_GALLERY_STYLE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._index_file = index_file
        self._on_select = on_select  # callback(artefact_dir, type, file)
        self._filter = "all"
        self._cards = []
        self._build_ui()
        self.hide()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(24, 16, 24, 8)
        title = QLabel("Artefacts")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: rgba(255,255,255,0.9);"
        )
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Search bar
        search_row = QHBoxLayout()
        search_row.setContentsMargins(24, 0, 24, 8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search artefacts...")
        self._search.textChanged.connect(self._refresh_list)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(24, 0, 24, 12)
        self._filter_btns = {}
        for label in ["All", "HTML", "Image", "Video"]:
            btn = QPushButton(label)
            btn.setObjectName("filterBtn")
            btn.setCheckable(True)
            btn.setChecked(label == "All")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, l=label: self._set_filter(l))
            filter_row.addWidget(btn)
            self._filter_btns[label] = btn
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(24, 0, 24, 24)
        self._list_layout.setSpacing(8)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

    def _set_filter(self, label):
        self._filter = label.lower()
        for name, btn in self._filter_btns.items():
            btn.setChecked(name == label)
        self._refresh_list()

    def show_gallery(self):
        self._refresh_list()
        self.show()
        self.raise_()

    def _load_index(self) -> list:
        if not os.path.exists(self._index_file):
            return []
        try:
            with open(self._index_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _refresh_list(self):
        # Clear existing cards
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        index = self._load_index()
        query = self._search.text().lower().strip()

        for entry in index:
            atype = entry.get("type", "html")
            name = entry.get("name", "untitled")
            desc = entry.get("description", "")
            date = entry.get("created_at", "")[:10]
            path = entry.get("path", "")

            # Filter
            if self._filter != "all" and atype != self._filter:
                continue

            # Search
            if query and query not in name.lower() and query not in desc.lower():
                continue

            card = self._make_card(name, atype, desc, date, path, entry)
            self._list_layout.addWidget(card)

        self._list_layout.addStretch()

    def _make_card(self, name, atype, desc, date, path, entry):
        card = QWidget()
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(
            "QWidget { background: rgba(255,255,255,0.04); border-radius: 8px; }"
            "QWidget:hover { background: rgba(255,255,255,0.08); }"
        )
        card.setFixedHeight(64)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)

        # Type badge
        badge_colors = {"html": "#4a9eff", "image": "#ff6b9d", "video": "#9b59b6"}
        badge = QLabel(atype.upper())
        badge.setFixedWidth(50)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"color: {badge_colors.get(atype, '#888')}; font-size: 9px; "
            f"font-weight: bold; background: rgba(255,255,255,0.06); "
            f"border-radius: 4px; padding: 2px 4px;"
        )
        layout.addWidget(badge)

        # Name and description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        name_lbl = QLabel(name.replace("-", " ").title())
        name_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.85); font-size: 13px; font-weight: bold;"
        )
        text_layout.addWidget(name_lbl)
        if desc:
            desc_lbl = QLabel(desc[:60] + ("..." if len(desc) > 60 else ""))
            desc_lbl.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px;")
            text_layout.addWidget(desc_lbl)
        layout.addLayout(text_layout, stretch=1)

        # Date
        date_lbl = QLabel(date)
        date_lbl.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px;")
        layout.addWidget(date_lbl)

        # Click handler
        card.mousePressEvent = lambda e, p=path, t=atype, f=entry.get("file", ""): (
            self._select(p, t, f)
        )
        return card

    def _select(self, path, atype, file_path):
        self.hide()
        if self._on_select:
            self._on_select(path, atype, file_path)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(15, 15, 15, 247))
        p.end()

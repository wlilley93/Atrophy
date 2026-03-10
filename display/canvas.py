"""Canvas — PIP overlay for the companion window.

A QWebEngineView that overlays the video surface, like screen sharing
on a video call. Content is pushed via a local file, updated when the
companion calls the render_canvas MCP tool.

The overlay fades in when content is written, and fades out when dismissed
(Cmd+K or close button). Voice/text streaming continues independently.
"""
import logging
from pathlib import Path

from PyQt5.QtCore import (
    Qt, QUrl, QFileSystemWatcher, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtProperty,
)
from PyQt5.QtGui import QColor, QPainter, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QGraphicsOpacityEffect,
)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

from config import PROJECT_ROOT, CANVAS_CONTENT, CANVAS_TEMPLATES

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE = CANVAS_TEMPLATES / "default_canvas.html"

_BG = QColor(26, 26, 26)
_CLOSE_NORMAL = QColor(80, 80, 80)
_CLOSE_HOVER = QColor(180, 80, 80)
_RADIUS = 10


class _CloseButton(QPushButton):
    """Small X button for the canvas overlay."""

    def __init__(self, parent=None):
        super().__init__("×", parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self.setStyleSheet(
            "QPushButton { background: rgba(0,0,0,0.5); color: #aaa;"
            "  border: none; border-radius: 14px; font-size: 16px; }"
            "QPushButton:hover { background: rgba(180,80,80,0.8); color: white; }"
        )


class CanvasOverlay(QWidget):
    """PIP overlay — child widget of CompanionWindow.

    Sits on top of the video surface. Fades in when content is written,
    fades out on dismiss. Parent is responsible for calling reposition()
    on resize to keep it covering the video area.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setVisible(False)

        # Opacity for fade animations
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        # Fade animation — finished signal connected once here
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

        # Web view or fallback label
        if HAS_WEBENGINE:
            self._web = QWebEngineView(self)
            self._web.setStyleSheet("background: #1a1a1a; border-radius: 8px;")
            page = self._web.page()
            page.setBackgroundColor(_BG)
        else:
            self._web = None
            log.warning("PyQtWebEngine not installed — canvas overlay disabled")

        # Close button (top-right corner)
        self._close_btn = _CloseButton(self)
        self._close_btn.clicked.connect(self.dismiss)
        self._close_btn.raise_()

        # File watcher for auto-refresh
        self._watcher = QFileSystemWatcher(self)
        if CANVAS_CONTENT.exists():
            self._watcher.addPath(str(CANVAS_CONTENT))
        self._watcher.fileChanged.connect(self._on_file_changed)

        # Debounce timer
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(100)
        self._reload_timer.timeout.connect(self._do_refresh)

        # Track whether we're showing content (vs dismissed)
        self._active = False

    # ── Public API ──

    def show_canvas(self):
        """Fade in the overlay."""
        if not self._web:
            return
        self._active = True
        self.refresh()
        self.setVisible(True)
        self.raise_()
        self._close_btn.raise_()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def dismiss(self):
        """Fade out and hide the overlay."""
        self._active = False
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def toggle(self):
        """Toggle overlay visibility."""
        if self._active:
            self.dismiss()
        else:
            self.show_canvas()

    def is_active(self) -> bool:
        return self._active

    def reposition(self, x: int, y: int, w: int, h: int):
        """Reposition overlay to cover the video area. Called by parent on resize."""
        # Inset slightly for a PIP look
        margin = 8
        self.setGeometry(x + margin, y + margin, w - margin * 2, h - margin * 2)
        if self._web:
            self._web.setGeometry(0, 0, self.width(), self.height())
        self._close_btn.move(self.width() - 36, 8)

    def set_content(self, html: str):
        """Write HTML to the canvas file and show."""
        CANVAS_CONTENT.write_text(html, encoding="utf-8")
        self._ensure_watched()
        if not self._active:
            self.show_canvas()
        else:
            self.refresh()

    def refresh(self):
        """Reload content from the canvas file."""
        if not self._web:
            return
        if not CANVAS_CONTENT.exists():
            return
        url = QUrl.fromLocalFile(str(CANVAS_CONTENT))
        self._web.load(url)

    # ── Internal ──

    def _on_fade_finished(self):
        """Hide widget after fade-out completes (connected once in __init__)."""
        if not self._active:
            self.setVisible(False)

    def _ensure_watched(self):
        """Re-add file to watcher if dropped."""
        if str(CANVAS_CONTENT) not in self._watcher.files():
            if CANVAS_CONTENT.exists():
                self._watcher.addPath(str(CANVAS_CONTENT))

    def _on_file_changed(self, path):
        """File watcher callback — auto-show and refresh."""
        self._ensure_watched()
        # Auto-show when content is written (e.g. by MCP tool)
        if not self._active:
            self.show_canvas()  # show_canvas calls refresh()
        else:
            self._reload_timer.start()  # debounced refresh if already visible

    def _do_refresh(self):
        self.refresh()

    def paintEvent(self, event):
        """Dark rounded background behind the web view."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(_BG)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), _RADIUS, _RADIUS)
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._web:
            self._web.setGeometry(0, 0, self.width(), self.height())
        self._close_btn.move(self.width() - 36, 8)


# Keep old name for backward compat during transition
CanvasPanel = CanvasOverlay

"""display/window.py — PyQt5 companion window.

Full-bleed video with overlay text and floating input bar.
Streaming inference → sentence-level TTS pipelining for low latency.
"""

import json
import random
import re
import subprocess
import sys
from pathlib import Path
from queue import Queue, Empty

from PyQt5.QtCore import (
    Qt, QUrl, QPropertyAnimation, QEasingCurve, QTimer, pyqtSignal,
    pyqtProperty, QThread, QRectF, QRect, QSize,
)
from PyQt5.QtGui import (
    QFont, QFontMetrics, QColor, QPainter, QPainterPath, QPen, QImage,
    QLinearGradient, QRadialGradient,
)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLineEdit, QPushButton, QMenu, QSystemTrayIcon,
    QScrollArea, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QComboBox,
    QCheckBox, QSpinBox, QFrame, QDoubleSpinBox,
)
from PyQt5.QtMultimedia import (
    QMediaPlayer, QMediaContent, QAbstractVideoSurface, QAbstractVideoBuffer,
    QVideoFrame,
)

from config import WINDOW_WIDTH, WINDOW_HEIGHT, IDLE_LOOP, AGENT_DISPLAY_NAME, USER_NAME

# Canvas — PIP overlay (graceful if QWebEngineView unavailable)
try:
    from display.canvas import CanvasOverlay, HAS_WEBENGINE
    HAS_CANVAS = True
except ImportError:
    HAS_CANVAS = False
    HAS_WEBENGINE = False

from display.artefact import ArtefactOverlay, ArtefactGallery

_W = WINDOW_WIDTH
_H = WINDOW_HEIGHT
_DISPLAY_TAG_RE = re.compile(r'\[[^\]]+\]')
_CODE_BLOCK_RE = re.compile(r'```[\s\S]*?```')
_INLINE_CODE_RE = re.compile(r'`[^`]+`')


def _strip_tags(text: str) -> str:
    """Strip audio/prosody tags and code blocks for display."""
    cleaned = _CODE_BLOCK_RE.sub('', text)
    cleaned = _INLINE_CODE_RE.sub('', cleaned)
    cleaned = _DISPLAY_TAG_RE.sub('', cleaned)
    return re.sub(r'  +', ' ', cleaned).strip()
_PAD = 24
_BAR_H = 48
_BAR_RADIUS = 24


# ── Video surface ──

class FrameGrabSurface(QAbstractVideoSurface):
    frame_ready = pyqtSignal(QImage)

    _FORMAT_MAP = {
        QVideoFrame.Format_ARGB32: QImage.Format_ARGB32,
        QVideoFrame.Format_ARGB32_Premultiplied: QImage.Format_ARGB32_Premultiplied,
        QVideoFrame.Format_RGB32: QImage.Format_RGB32,
        QVideoFrame.Format_RGB565: QImage.Format_RGB16,
    }

    def supportedPixelFormats(self, handle_type=QAbstractVideoBuffer.NoHandle):
        return list(self._FORMAT_MAP.keys())

    def isFormatSupported(self, fmt):
        return fmt.pixelFormat() in self._FORMAT_MAP

    def start(self, fmt):
        if fmt.pixelFormat() not in self._FORMAT_MAP:
            return False
        return super().start(fmt)

    def present(self, frame: QVideoFrame):
        if not frame.isValid():
            return False
        frame.map(QAbstractVideoBuffer.ReadOnly)
        fmt = self._FORMAT_MAP.get(frame.pixelFormat())
        if fmt is None:
            frame.unmap()
            return False
        img = QImage(
            frame.bits(), frame.width(), frame.height(),
            frame.bytesPerLine(), fmt,
        ).copy()
        frame.unmap()
        self.frame_ready.emit(img)
        return True


# ── Streaming pipeline worker ──

class StreamingPipelineWorker(QThread):
    """Parallel inference + TTS pipeline.

    Thread 1 (this thread): reads inference stream, queues sentences
    Thread 2 (TTS thread): picks up sentences, synthesises audio, emits signals

    This means sentence 2 is being read while sentence 1 is being synthesised.
    """
    text_ready = pyqtSignal(str, int)       # text available immediately (before TTS)
    sentence_ready = pyqtSignal(str, str, int)  # TTS done — audio path available
    tool_use = pyqtSignal(str, str)
    compacting = pyqtSignal()
    done = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, user_text, system, cli_session_id, synth_fn, muted=False):
        super().__init__()
        self._user_text = user_text
        self._system = system
        self._cli_session_id = cli_session_id
        self._synth = synth_fn
        self._muted = muted

    def run(self):
        import threading
        from core.inference import (
            stream_inference, SentenceReady, ToolUse,
            StreamDone, StreamError, TextDelta, Compacting,
        )

        sentence_queue = Queue()
        full_text = ""
        session_id = self._cli_session_id or ""

        # TTS worker thread — synthesises sentences from queue
        def tts_loop():
            while True:
                item = sentence_queue.get()
                if item is None:
                    break
                sentence, index = item
                audio_path = ""
                if self._synth and not self._muted:
                    try:
                        path = self._synth(sentence)
                        audio_path = str(path)
                    except Exception as e:
                        print(f"  [TTS error: {e}]")
                self.sentence_ready.emit(sentence, audio_path, index)

        tts_thread = threading.Thread(target=tts_loop, daemon=True)
        tts_thread.start()

        # Read inference stream (this thread)
        for event in stream_inference(
            self._user_text, self._system, self._cli_session_id
        ):
            if isinstance(event, SentenceReady):
                # Show text immediately, TTS happens in parallel
                self.text_ready.emit(event.sentence, event.index)
                sentence_queue.put((event.sentence, event.index))

            elif isinstance(event, ToolUse):
                self.tool_use.emit(event.name, event.tool_id)

            elif isinstance(event, Compacting):
                self.compacting.emit()

            elif isinstance(event, StreamDone):
                full_text = event.full_text
                session_id = event.session_id

            elif isinstance(event, StreamError):
                sentence_queue.put(None)
                tts_thread.join(timeout=5)
                self.error.emit(event.message)
                return

        # Signal TTS thread to finish, then wait
        sentence_queue.put(None)
        tts_thread.join(timeout=30)

        self.done.emit(full_text, session_id)


class MemoryFlushWorker(QThread):
    """Silent background memory flush before compaction."""
    finished_flush = pyqtSignal(str)  # new session_id or ""

    def __init__(self, cli_session_id, system):
        super().__init__()
        self._cli_session_id = cli_session_id
        self._system = system

    def run(self):
        from core.inference import run_memory_flush
        new_sid = run_memory_flush(self._cli_session_id, self._system)
        self.finished_flush.emit(new_sid or "")


class CoherenceWorker(QThread):
    """Background SENTINEL coherence check."""
    finished_check = pyqtSignal(str)  # new session_id or ""

    def __init__(self, cli_session_id, system):
        super().__init__()
        self._cli_session_id = cli_session_id
        self._system = system

    def run(self):
        from core.sentinel import run_coherence_check
        new_sid = run_coherence_check(self._cli_session_id, self._system)
        self.finished_check.emit(new_sid or "")


class OpeningWorker(QThread):
    """Generate dynamic opening line + TTS."""
    ready = pyqtSignal(str, str)  # (text, audio_path)
    error_signal = pyqtSignal(str)

    def __init__(self, infer_fn, synth_fn):
        super().__init__()
        self._infer = infer_fn
        self._synth = synth_fn

    def run(self):
        try:
            text = self._infer("")
            audio_path = ""
            if self._synth:
                try:
                    audio_path = str(self._synth(text))
                except Exception as e:
                    print(f"  [TTS error: {e}]")
            self.ready.emit(text, audio_path)
        except Exception as e:
            self.error_signal.emit(str(e))


# ── Thinking spinner ──


# ── Status bar — loading / shutting down ──

class StatusBar(QWidget):
    """Thin animated progress line — sits as top stroke of the chat bar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFixedHeight(2)
        self._progress = 0.0  # 0..1, or -1 for indeterminate
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._sweep = 0.0
        self.hide()

    def start(self, label: str = "", indeterminate: bool = True):
        self._progress = -1.0 if indeterminate else 0.0
        self._sweep = 0.0
        self.show()
        self._timer.start()

    def set_progress(self, value: float, label: str = None):
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._sweep = (self._sweep + 0.015) % 1.0
        self.update()

    def paintEvent(self, event):
        w = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        if self._progress < 0:
            # Indeterminate — sliding highlight
            bar_w = int(w * 0.3)
            x = int(self._sweep * (w + bar_w)) - bar_w
            p.setBrush(QColor(255, 255, 255, 100))
            p.drawRoundedRect(max(0, x), 0, min(bar_w, w - max(0, x)), 2, 1, 1)
        else:
            fill_w = int(w * self._progress)
            if fill_w > 0:
                p.setBrush(QColor(255, 255, 255, 100))
                p.drawRoundedRect(0, 0, fill_w, 2, 1, 1)

        p.end()


# ── Chat transcript overlay ──

class TranscriptOverlay(QWidget):
    """Scrolling chat transcript with selectable text.

    Uses a QTextBrowser for native text selection and copy, styled to match
    the transparent-overlay aesthetic. Messages are bottom-aligned with a
    fade gradient at the top.
    """
    _MSG_GAP = 6       # gap within a pair (user → companion)
    _PAIR_GAP = 20     # gap between pairs
    _SCROLL_STEP = 40

    def __init__(self, parent=None, font_family="Bricolage Grotesque"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        from PyQt5.QtWidgets import QTextBrowser

        self._browser = QTextBrowser(self)
        self._browser.setReadOnly(True)
        self._browser.setOpenLinks(False)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._browser.setStyleSheet(f"""
            QTextBrowser {{
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 220);
                font-family: '{font_family}';
                font-size: 14px;
                selection-background-color: rgba(100, 140, 255, 120);
                selection-color: white;
            }}
        """)

        # Each entry: {"role": "user"|"companion", "text": str, "revealed": int}
        self._messages = []
        self._opacity = 1.0
        self._auto_scroll = True
        self._html_dirty = True

        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(18)
        self._reveal_timer.timeout.connect(self._tick_reveal)

        # Track scroll position for auto-scroll detection
        vbar = self._browser.verticalScrollBar()
        vbar.rangeChanged.connect(self._on_range_changed)
        vbar.valueChanged.connect(self._on_scroll_changed)

    def _on_range_changed(self, _min, _max):
        """When content changes size, scroll to bottom if auto-scroll is on."""
        if self._auto_scroll:
            self._browser.verticalScrollBar().setValue(
                self._browser.verticalScrollBar().maximum()
            )

    def _on_scroll_changed(self, value):
        """Detect manual scrolling — disable auto-scroll when user scrolls up."""
        vbar = self._browser.verticalScrollBar()
        if vbar.maximum() > 0 and value < vbar.maximum():
            self._auto_scroll = False
        elif value >= vbar.maximum():
            self._auto_scroll = True

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self._browser.setStyleSheet(self._browser.styleSheet())  # force repaint
        self.update()

    opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def _invalidate_layout(self):
        self._html_dirty = True

    def _rebuild_html(self):
        """Rebuild the HTML content from messages."""
        if not self._html_dirty:
            return
        self._html_dirty = False

        parts = []
        for i, msg in enumerate(self._messages):
            text = msg["text"][:msg["revealed"]]
            if not text:
                continue

            # Escape HTML
            escaped = (text.replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;")
                          .replace("\n", "<br>"))

            # Spacing between pairs
            if i > 0:
                prev_role = self._messages[i - 1]["role"]
                if msg["role"] == "user" and prev_role == "companion":
                    parts.append(f'<div style="height: {self._PAIR_GAP}px;"></div>')
                else:
                    parts.append(f'<div style="height: {self._MSG_GAP}px;"></div>')

            if msg["role"] == "divider":
                parts.append(
                    f'<div style="color: rgba(120, 200, 120, 0.6); text-align: center; '
                    f'font-size: 11px; letter-spacing: 3px; padding: 8px 0; '
                    f'border-top: 1px solid rgba(120, 200, 120, 0.2); '
                    f'border-bottom: 1px solid rgba(120, 200, 120, 0.2); '
                    f'text-transform: uppercase; font-weight: 600;">'
                    f'{escaped}</div>'
                )
                continue

            if msg["role"] == "user":
                color = "rgba(180, 180, 180, 220)"
            else:
                color = "rgba(255, 255, 255, 220)"

            parts.append(
                f'<div style="color: {color}; '
                f'text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">'
                f'{escaped}</div>'
            )

        html = "".join(parts)
        # Preserve scroll position
        vbar = self._browser.verticalScrollBar()
        was_at_bottom = self._auto_scroll
        self._browser.setHtml(html)
        if was_at_bottom:
            vbar.setValue(vbar.maximum())

    def add_message(self, role: str, text: str, instant: bool = False):
        """Add a message. User messages reveal instantly, companion gradually."""
        revealed = len(text) if (instant or role == "user") else 0
        self._messages.append({
            "role": role, "text": text, "revealed": revealed,
        })
        if revealed < len(text) and not self._reveal_timer.isActive():
            self._reveal_timer.start()
        if self._auto_scroll:
            pass  # _on_range_changed handles scrolling
        self._html_dirty = True
        self._rebuild_html()

    def append_to_last(self, text: str):
        """Append text to the last companion message (streaming)."""
        if not self._messages:
            return
        msg = self._messages[-1]
        msg["text"] = (msg["text"] + " " + text).strip() if msg["text"] else text
        # For streaming, reveal immediately — text arrives as it streams
        msg["revealed"] = len(msg["text"])
        self._html_dirty = True
        self._rebuild_html()

    def set_last_text(self, text: str):
        """Set the text of the last message (first sentence)."""
        if not self._messages:
            return
        msg = self._messages[-1]
        msg["text"] = text
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()
        self._html_dirty = True
        self._rebuild_html()

    def add_divider(self, label: str = ""):
        """Add a visual divider — used during agent deferral (codec-style)."""
        self._messages.append({
            "role": "divider", "text": label, "revealed": len(label),
        })
        self._html_dirty = True
        self._rebuild_html()

    def clear_messages(self):
        self._messages.clear()
        self._auto_scroll = True
        self._browser.clear()
        self._html_dirty = True

    def scroll_up(self):
        vbar = self._browser.verticalScrollBar()
        vbar.setValue(vbar.value() - self._SCROLL_STEP)
        self._auto_scroll = False

    def scroll_down(self):
        vbar = self._browser.verticalScrollBar()
        vbar.setValue(vbar.value() + self._SCROLL_STEP)
        if vbar.value() >= vbar.maximum():
            self._auto_scroll = True

    def copy_last_companion(self):
        """Copy the last companion message to clipboard."""
        # If user has selected text in the browser, copy that instead
        cursor = self._browser.textCursor()
        if cursor.hasSelection():
            app = QApplication.instance()
            if app:
                app.clipboard().setText(cursor.selectedText())
                print(f"  [Copied selection]")
            return
        # Otherwise copy last companion message
        for msg in reversed(self._messages):
            if msg["role"] == "companion" and msg["text"]:
                app = QApplication.instance()
                if app:
                    app.clipboard().setText(msg["text"])
                    print(f"  [Copied: {msg['text'][:60]}...]")
                return
        print("  [Copy: no companion message found]")

    def _tick_reveal(self):
        any_pending = False
        for msg in self._messages:
            if msg["revealed"] < len(msg["text"]):
                msg["revealed"] = min(msg["revealed"] + 3, len(msg["text"]))
                any_pending = True
        if not any_pending:
            self._reveal_timer.stop()
        self._html_dirty = True
        self._rebuild_html()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._browser.setGeometry(0, 0, self.width(), self.height())

    def paintEvent(self, event):
        """Draw fade gradient over the top 1/3 of the transcript."""
        if self._opacity <= 0.001:
            return
        super().paintEvent(event)

        # Fade mask — gentle gradient at top so text doesn't end abruptly
        vis_h = self.height()
        fade_h = vis_h / 4.0
        if fade_h <= 0:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, 0, fade_h)
        # Subtle fade — just enough to soften the top edge, not a solid block
        grad.setColorAt(0.0, QColor(0, 0, 0, 100))
        grad.setColorAt(0.5, QColor(0, 0, 0, 30))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, self.width(), int(fade_h), grad)
        p.end()


def _fade(widget, start, end, duration_ms):
    anim = QPropertyAnimation(widget, b"opacity", widget)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setDuration(duration_ms)
    anim.setEasingCurve(QEasingCurve.InOutQuad)
    anim.start(QPropertyAnimation.DeleteWhenStopped)
    return anim


# ── Icon buttons ──

class _EyeButton(QPushButton):
    """Eye icon toggle button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._active = False

    def set_active(self, active):
        self._active = active
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Background pill
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Icon — centred in the pill
        cx, cy = 17, 17
        alpha = 220 if self._active else 120
        col = QColor(255, 255, 255, alpha)
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(7, cy)
        path.cubicTo(11, cy - 6, 23, cy - 6, 27, cy)
        path.cubicTo(23, cy + 6, 11, cy + 6, 7, cy)
        p.drawPath(path)
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - 3, cy - 3, 6, 6)
        if self._active:
            p.setPen(QPen(col, 1.8))
            p.drawLine(9, 25, 25, 9)
        p.end()


class _MuteButton(QPushButton):
    """Speaker/mute icon toggle button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._active = False

    def set_active(self, active):
        self._active = active
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Background pill
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Icon — centred
        alpha = 220 if self._active else 120
        col = QColor(255, 255, 255, alpha)
        p.setPen(QPen(col, 1.6))
        p.setBrush(col)
        p.drawRect(9, 13, 4, 8)
        path = QPainterPath()
        path.moveTo(13, 13)
        path.lineTo(19, 9)
        path.lineTo(19, 25)
        path.lineTo(13, 21)
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
        if not self._active:
            p.drawArc(20, 12, 5, 10, -60 * 16, 120 * 16)
            p.drawArc(22, 10, 6, 14, -60 * 16, 120 * 16)
        else:
            # X mark for muted
            p.setPen(QPen(col, 2.0))
            p.drawLine(22, 13, 28, 21)
            p.drawLine(28, 13, 22, 21)
        p.end()


class _MinimizeButton(QPushButton):
    """Minimize-to-tray icon button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Minimize icon — horizontal line
        p.setPen(QPen(QColor(255, 255, 255, 120), 2.0))
        p.drawLine(11, 17, 23, 17)
        p.end()


class _WakeButton(QPushButton):
    """Wake word listener toggle button — microphone with radio waves."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._active = False

    def set_active(self, active):
        self._active = active
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Background pill
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        if self._active:
            # Subtle green tint when active
            p.fillPath(bg, QColor(30, 80, 40, 210))
        else:
            p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Microphone icon
        cx, cy = 17, 15
        alpha = 220 if self._active else 120
        col = QColor(255, 255, 255, alpha)
        p.setPen(QPen(col, 1.6))
        p.setBrush(col)
        # Mic body (rounded rect)
        p.drawRoundedRect(QRectF(cx - 3, cy - 6, 6, 10), 3, 3)
        # Mic cup
        p.setBrush(Qt.NoBrush)
        p.drawArc(cx - 6, cy - 4, 12, 14, 0, -180 * 16)
        # Stand
        p.drawLine(cx, cy + 10, cx, cy + 13)
        p.drawLine(cx - 4, cy + 13, cx + 4, cy + 13)
        # Radio waves when active
        if self._active:
            wave_col = QColor(100, 255, 130, 160)
            p.setPen(QPen(wave_col, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawArc(cx - 10, cy - 10, 20, 20, 30 * 16, 120 * 16)
            p.drawArc(cx - 13, cy - 13, 26, 26, 30 * 16, 120 * 16)
        p.end()


class _ArtefactButton(QPushButton):
    """File/document icon button for artefact gallery."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._has_new = False

    def set_has_new(self, has_new):
        self._has_new = has_new
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Document icon
        alpha = 220 if self._has_new else 120
        col = QColor(255, 255, 255, alpha)
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.NoBrush)
        # Page outline with folded corner
        path = QPainterPath()
        path.moveTo(10, 8)
        path.lineTo(21, 8)
        path.lineTo(25, 12)
        path.lineTo(25, 26)
        path.lineTo(10, 26)
        path.closeSubpath()
        p.drawPath(path)
        # Corner fold
        p.drawLine(21, 8, 21, 12)
        p.drawLine(21, 12, 25, 12)
        # Content lines
        p.setPen(QPen(col, 1.0))
        p.drawLine(13, 16, 22, 16)
        p.drawLine(13, 19, 20, 19)
        p.drawLine(13, 22, 21, 22)
        # New indicator dot
        if self._has_new:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(100, 180, 255, 220))
            p.drawEllipse(26, 6, 6, 6)
        p.end()


from display.settings import SettingsModal


class _SettingsButton(QPushButton):
    """Gear icon button for settings panel."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._active = False

    def set_active(self, active):
        self._active = active
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        if self._active:
            p.fillPath(bg, QColor(40, 40, 50, 210))
        else:
            p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Gear icon
        cx, cy = 17, 17
        alpha = 220 if self._active else 120
        col = QColor(255, 255, 255, alpha)
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.NoBrush)
        # Inner circle
        p.drawEllipse(cx - 4, cy - 4, 8, 8)
        # Gear teeth (8 lines radiating out)
        import math
        for i in range(8):
            angle = i * math.pi / 4
            x1 = cx + 6 * math.cos(angle)
            y1 = cy + 6 * math.sin(angle)
            x2 = cx + 9 * math.cos(angle)
            y2 = cy + 9 * math.sin(angle)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        p.end()


class _CallButton(QPushButton):
    """Phone icon button for voice call mode."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._active = False
        self._status = "idle"  # idle, listening, thinking, speaking

    def set_active(self, active):
        self._active = active
        self.update()

    def set_status(self, status):
        self._status = status
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, 34, 34), 17, 17)
        if self._active:
            if self._status == "listening":
                p.fillPath(bg, QColor(30, 120, 50, 220))
            elif self._status == "thinking":
                p.fillPath(bg, QColor(80, 80, 30, 220))
            elif self._status == "speaking":
                p.fillPath(bg, QColor(30, 60, 120, 220))
            else:
                p.fillPath(bg, QColor(120, 30, 30, 220))
        else:
            p.fillPath(bg, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(bg)
        # Phone handset icon
        alpha = 240 if self._active else 120
        col = QColor(255, 255, 255, alpha)
        p.setPen(QPen(col, 1.8))
        p.setBrush(Qt.NoBrush)
        # Handset — a curved path like a phone receiver
        path = QPainterPath()
        path.moveTo(10, 13)
        path.quadTo(10, 10, 13, 10)
        path.lineTo(15, 10)
        path.quadTo(16, 10, 16, 12)
        # Curved middle
        path.quadTo(17, 17, 18, 22)
        path.quadTo(18, 24, 19, 24)
        path.lineTo(21, 24)
        path.quadTo(24, 24, 24, 21)
        # Hang-up slash when active
        if self._active:
            p.drawPath(path)
            p.setPen(QPen(QColor(255, 100, 100, 220), 2.2))
            p.drawLine(9, 25, 25, 9)
        else:
            p.drawPath(path)
        p.end()


# ── Settings panel (moved to display/settings.py) ──
# Old _SETTINGS_STYLE and SettingsPanel class removed.
# Import is at the top of this section: from display.settings import SettingsModal

_OLD_SETTINGS_STYLE = """
    QWidget#settingsPanel {
        background: transparent;
    }
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }
    QScrollBar:vertical {
        background: rgba(255, 255, 255, 10);
        width: 6px;
        margin: 0;
        border-radius: 3px;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 40);
        min-height: 30px;
        border-radius: 3px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QLabel {
        color: rgba(255, 255, 255, 0.85);
        font-size: 13px;
        background: transparent;
    }
    QLabel#sectionHeader {
        color: rgba(255, 255, 255, 0.5);
        font-size: 11px;
        font-weight: bold;
        text-transform: uppercase;
        padding-top: 12px;
        padding-bottom: 4px;
        background: transparent;
    }
    QLabel#settingLabel {
        color: rgba(255, 255, 255, 0.7);
        font-size: 12px;
        background: transparent;
    }
    QSlider::groove:horizontal {
        height: 4px;
        background: rgba(255, 255, 255, 0.15);
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        width: 14px;
        height: 14px;
        margin: -5px 0;
        background: rgba(255, 255, 255, 0.8);
        border-radius: 7px;
    }
    QSlider::sub-page:horizontal {
        background: rgba(255, 255, 255, 0.35);
        border-radius: 2px;
    }
    QComboBox {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
        min-width: 120px;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    QComboBox::down-arrow {
        image: none;
        border: none;
    }
    QComboBox QAbstractItemView {
        background: rgb(30, 30, 35);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        selection-background-color: rgba(255, 255, 255, 0.15);
    }
    QCheckBox {
        color: rgba(255, 255, 255, 0.85);
        font-size: 12px;
        spacing: 6px;
        background: transparent;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.05);
    }
    QCheckBox::indicator:checked {
        background: rgba(255, 255, 255, 0.3);
        border-color: rgba(255, 255, 255, 0.5);
    }
    QSpinBox, QDoubleSpinBox {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
        min-width: 80px;
    }
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        width: 16px;
        border: none;
        background: rgba(255, 255, 255, 0.05);
    }
    QLineEdit#settingsInput {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
    }
    QPushButton#saveButton {
        background: rgba(255, 255, 255, 0.12);
        color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 8px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: bold;
    }
    QPushButton#saveButton:hover {
        background: rgba(255, 255, 255, 0.18);
    }
    QPushButton#closeButton {
        background: transparent;
        color: rgba(255, 255, 255, 0.5);
        border: none;
        font-size: 20px;
        font-weight: bold;
    }
    QPushButton#closeButton:hover {
        color: rgba(255, 255, 255, 0.9);
    }
"""


class _LegacySettingsPanel(QWidget):
    """DEPRECATED — replaced by display.settings.SettingsModal."""
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.setStyleSheet(_OLD_SETTINGS_STYLE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._controls = {}  # key → widget, for reading values back
        self._build_ui()
        self.hide()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QHBoxLayout()
        header.setContentsMargins(24, 16, 24, 8)
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: rgba(255,255,255,0.9);")
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._close)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(24, 8, 24, 24)
        self._content_layout.setSpacing(4)

        self._build_sections()

        self._content_layout.addStretch()

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_settings)
        save_row.addWidget(save_btn)
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("saveButton")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_settings)
        save_row.addWidget(apply_btn)
        save_row.addStretch()
        self._content_layout.addLayout(save_row)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _add_section(self, title):
        label = QLabel(title)
        label.setObjectName("sectionHeader")
        self._content_layout.addWidget(label)
        # Separator line
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,0.08);")
        self._content_layout.addWidget(line)

    def _add_slider(self, key, label, min_val, max_val, current, decimals=2, step=0.01):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)

        slider = QSlider(Qt.Horizontal)
        scale = 10 ** decimals
        slider.setMinimum(int(min_val * scale))
        slider.setMaximum(int(max_val * scale))
        slider.setValue(int(current * scale))
        slider.setSingleStep(int(step * scale))

        val_label = QLabel(f"{current:.{decimals}f}")
        val_label.setFixedWidth(50)
        val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val_label.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 12px;")

        def on_change(v):
            real = v / scale
            val_label.setText(f"{real:.{decimals}f}")

        slider.valueChanged.connect(on_change)
        row.addWidget(slider, 1)
        row.addWidget(val_label)

        self._content_layout.addLayout(row)
        self._controls[key] = ("slider", slider, scale, decimals)

    def _add_combo(self, key, label, options, current):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)

        combo = QComboBox()
        combo.addItems(options)
        if current in options:
            combo.setCurrentText(current)
        row.addWidget(combo)
        row.addStretch()

        self._content_layout.addLayout(row)
        self._controls[key] = ("combo", combo)

    def _add_checkbox(self, key, label, checked):
        row = QHBoxLayout()
        cb = QCheckBox(label)
        cb.setChecked(checked)
        row.addWidget(cb)
        row.addStretch()

        self._content_layout.addLayout(row)
        self._controls[key] = ("checkbox", cb)

    def _add_spinbox(self, key, label, min_val, max_val, current, suffix=""):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)

        spin = QSpinBox()
        spin.setMinimum(min_val)
        spin.setMaximum(max_val)
        spin.setValue(current)
        if suffix:
            spin.setSuffix(f" {suffix}")
        row.addWidget(spin)
        row.addStretch()

        self._content_layout.addLayout(row)
        self._controls[key] = ("spinbox", spin)

    def _add_text(self, key, label, current, password=False):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)

        inp = QLineEdit()
        inp.setObjectName("settingsInput")
        inp.setText(str(current))
        if password:
            inp.setEchoMode(QLineEdit.Password)
        row.addWidget(inp, 1)

        self._content_layout.addLayout(row)
        self._controls[key] = ("text", inp)

    def _add_info(self, key, label, value):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)

        val = QLabel(str(value))
        val.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px;")
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(val)
        row.addStretch()

        self._content_layout.addLayout(row)
        self._controls[key] = ("info", val)

    def _build_sections(self):
        import config as cfg
        from core.agent_manager import discover_agents, get_agent_state

        # ── Agents ──
        self._add_section("AGENTS")
        self._agent_controls = {}
        agents = discover_agents()
        for agent in agents:
            name = agent["name"]
            display = agent["display_name"]
            state = get_agent_state(name)
            is_current = (name == cfg.AGENT_NAME)

            row = QHBoxLayout()

            # Agent name with current indicator
            label_text = f"  {display}" if not is_current else f"  {display}"
            name_lbl = QLabel(label_text)
            name_lbl.setFixedWidth(140)
            if is_current:
                name_lbl.setStyleSheet(
                    "color: rgba(255,255,255,0.95); font-weight: bold; font-size: 13px;"
                )
            else:
                name_lbl.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 13px;")
            row.addWidget(name_lbl)

            # Enabled checkbox (controls cron jobs)
            enabled_cb = QCheckBox("Enabled")
            enabled_cb.setChecked(state.get("enabled", True))
            row.addWidget(enabled_cb)

            # Muted checkbox (per-agent TTS suppression)
            muted_cb = QCheckBox("Muted")
            muted_cb.setChecked(state.get("muted", False))
            row.addWidget(muted_cb)

            # Switch button (if not current)
            if not is_current:
                switch_btn = QPushButton("Switch")
                switch_btn.setObjectName("saveButton")
                switch_btn.setFixedWidth(70)
                switch_btn.setCursor(Qt.PointingHandCursor)
                switch_btn.clicked.connect(
                    lambda checked, a=name: self._switch_to_agent(a)
                )
                row.addWidget(switch_btn)
            else:
                current_lbl = QLabel("active")
                current_lbl.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px;")
                row.addWidget(current_lbl)

            row.addStretch()
            self._content_layout.addLayout(row)
            self._agent_controls[name] = {
                "enabled": enabled_cb,
                "muted": muted_cb,
                "label": name_lbl,
            }

        # New agent button
        new_agent_row = QHBoxLayout()
        new_agent_btn = QPushButton("+ New Agent")
        new_agent_btn.setObjectName("saveButton")
        new_agent_btn.setFixedWidth(120)
        new_agent_btn.setCursor(Qt.PointingHandCursor)
        new_agent_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.7); "
            "border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 6px 12px; "
            "font-size: 12px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.15); color: rgba(255,255,255,0.9); }"
        )
        new_agent_btn.clicked.connect(self._run_new_agent_flow)
        new_agent_row.addWidget(new_agent_btn)
        new_agent_row.addStretch()
        self._content_layout.addLayout(new_agent_row)

        # ── Agent Identity ──
        self._add_section("AGENT IDENTITY")
        self._add_info("agent_name", "Agent Slug", cfg.AGENT_NAME)
        self._add_text("agent_display_name", "Display Name", cfg.AGENT_DISPLAY_NAME)
        self._add_text("user_name", "User Name", cfg.USER_NAME)
        self._add_text("opening_line", "Opening Line", cfg.OPENING_LINE)
        self._add_text("wake_words", "Wake Words",
                       ", ".join(cfg.WAKE_WORDS))

        # ── Per-Agent Tool Disabling ──
        self._add_section("TOOLS")
        self._tool_checkboxes = {}
        _toggleable_tools = [
            ("mcp__memory__defer_to_agent", "Agent deferral"),
            ("mcp__memory__send_telegram", "Telegram messaging"),
            ("mcp__memory__set_reminder", "Reminders"),
            ("mcp__memory__set_timer", "Timers"),
            ("mcp__memory__create_task", "Task scheduling"),
            ("mcp__memory__render_canvas", "Canvas overlay"),
            ("mcp__memory__write_note", "Write Obsidian notes"),
            ("mcp__memory__prompt_journal", "Journal prompting"),
            ("mcp__memory__update_emotional_state", "Emotional state"),
            ("mcp__memory__create_artefact", "Artefact creation"),
            ("mcp__memory__manage_schedule", "Schedule management"),
            ("mcp__puppeteer__*", "Browser (Puppeteer)"),
            ("mcp__fal__*", "Media generation (fal)"),
        ]
        _disabled = set(cfg.DISABLED_TOOLS)
        for tool_id, label in _toggleable_tools:
            cb = QCheckBox(label)
            cb.setChecked(tool_id not in _disabled)
            cb.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 12px; padding-left: 8px;")
            self._content_layout.addWidget(cb)
            self._tool_checkboxes[tool_id] = cb

        # ── Display / Window ──
        self._add_section("WINDOW")
        self._add_spinbox("window_width", "Window Width",
                          300, 1920, cfg.WINDOW_WIDTH, suffix="px")
        self._add_spinbox("window_height", "Window Height",
                          400, 1080, cfg.WINDOW_HEIGHT, suffix="px")
        self._add_text("window_title", "Window Title",
                       cfg.AGENT.get("display", {}).get("title",
                           f"THE ATROPHIED MIND -- {cfg.AGENT_DISPLAY_NAME}"))
        self._add_checkbox("avatar_enabled", "Avatar Enabled",
                           cfg.AVATAR_ENABLED)
        self._add_spinbox("avatar_resolution", "Avatar Resolution",
                          128, 1024, cfg.AVATAR_RESOLUTION)

        # ── Voice / TTS ──
        self._add_section("VOICE & TTS")
        self._add_combo("tts_backend", "TTS Backend",
                        ["elevenlabs", "fal", "none"], cfg.TTS_BACKEND)
        self._add_text("elevenlabs_api_key", "ElevenLabs API Key",
                       cfg.ELEVENLABS_API_KEY, password=True)
        self._add_text("elevenlabs_voice_id", "ElevenLabs Voice ID",
                       cfg.ELEVENLABS_VOICE_ID)
        self._add_combo("elevenlabs_model", "ElevenLabs Model",
                        ["eleven_v3", "eleven_v2", "eleven_multilingual_v2",
                         "eleven_turbo_v2_5", "eleven_flash_v2_5"],
                        cfg.ELEVENLABS_MODEL)
        self._add_slider("elevenlabs_stability", "Stability",
                         0.0, 1.0, cfg.ELEVENLABS_STABILITY)
        self._add_slider("elevenlabs_similarity", "Similarity",
                         0.0, 1.0, cfg.ELEVENLABS_SIMILARITY)
        self._add_slider("elevenlabs_style", "Style",
                         0.0, 1.0, cfg.ELEVENLABS_STYLE)
        self._add_slider("tts_playback_rate", "Playback Rate",
                         0.5, 2.0, cfg.TTS_PLAYBACK_RATE)
        self._add_text("fal_voice_id", "Fal Voice ID", cfg.FAL_VOICE_ID)

        # ── Input ──
        self._add_section("INPUT")
        self._add_combo("input_mode", "Input Mode",
                        ["dual", "voice", "text"], cfg.INPUT_MODE)
        self._add_text("ptt_key", "Push-to-Talk Key", cfg.PTT_KEY)
        self._add_checkbox("wake_word_enabled", "Wake Word Detection",
                           cfg.WAKE_WORD_ENABLED)
        self._add_spinbox("wake_chunk_seconds", "Wake Chunk Duration",
                          1, 10, cfg.WAKE_CHUNK_SECONDS, suffix="sec")

        # ── Notifications ──
        self._add_section("NOTIFICATIONS")
        self._add_checkbox("notifications_enabled", "macOS Notifications",
                           cfg.NOTIFICATIONS_ENABLED)

        # ── Audio Capture ──
        self._add_section("AUDIO CAPTURE")
        self._add_spinbox("sample_rate", "Sample Rate",
                          8000, 48000, cfg.SAMPLE_RATE, suffix="Hz")
        self._add_spinbox("max_record_sec", "Max Record Duration",
                          10, 300, cfg.MAX_RECORD_SEC, suffix="sec")

        # ── Inference ──
        self._add_section("INFERENCE")
        self._add_text("claude_bin", "Claude Binary", cfg.CLAUDE_BIN)
        self._add_combo("claude_effort", "Claude Effort",
                        ["low", "medium", "high"], cfg.CLAUDE_EFFORT)
        self._add_checkbox("adaptive_effort", "Adaptive Effort",
                           cfg.ADAPTIVE_EFFORT)

        # ── Memory ──
        self._add_section("MEMORY & CONTEXT")
        self._add_spinbox("context_summaries", "Context Summaries",
                          0, 20, cfg.CONTEXT_SUMMARIES)
        self._add_spinbox("max_context_tokens", "Max Context Tokens",
                          10000, 500000, cfg.MAX_CONTEXT_TOKENS)
        self._add_slider("vector_search_weight", "Vector Search Weight",
                         0.0, 1.0, cfg.VECTOR_SEARCH_WEIGHT)
        self._add_text("embedding_model", "Embedding Model", cfg.EMBEDDING_MODEL)
        self._add_spinbox("embedding_dim", "Embedding Dimensions",
                          64, 2048, cfg.EMBEDDING_DIM)

        # ── Session ──
        self._add_section("SESSION")
        self._add_spinbox("session_soft_limit", "Soft Limit",
                          10, 480, cfg.SESSION_SOFT_LIMIT_MINS, suffix="min")

        # ── Heartbeat ──
        self._add_section("HEARTBEAT")
        self._add_spinbox("heartbeat_start", "Active Start Hour",
                          0, 23, cfg.HEARTBEAT_ACTIVE_START, suffix="h")
        self._add_spinbox("heartbeat_end", "Active End Hour",
                          0, 23, cfg.HEARTBEAT_ACTIVE_END, suffix="h")
        self._add_spinbox("heartbeat_interval", "Interval",
                          5, 120, cfg.HEARTBEAT_INTERVAL_MINS, suffix="min")

        # ── Paths ──
        self._add_section("PATHS")
        self._add_text("obsidian_vault", "Obsidian Vault",
                       str(cfg.OBSIDIAN_VAULT))
        self._add_info("db_path", "Database", str(cfg.DB_PATH))
        self._add_info("whisper_bin", "Whisper Binary", str(cfg.WHISPER_BIN))

        # ── Telegram ──
        self._add_section("TELEGRAM")
        self._add_text("telegram_bot_token", "Bot Token",
                       cfg.TELEGRAM_BOT_TOKEN, password=True)
        self._add_text("telegram_chat_id", "Chat ID",
                       cfg.TELEGRAM_CHAT_ID)

        # ── About ──
        self._add_section("ABOUT")
        self._add_info("app_version", "Version", cfg.VERSION)
        self._add_info("build_root", "Install Path", str(cfg.BUNDLE_ROOT))

        # Check for updates button
        update_row = QHBoxLayout()
        self._update_label = QLabel("")
        self._update_label.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        update_row.addWidget(self._update_label)
        update_row.addStretch()
        update_btn = QPushButton("Check for Updates")
        update_btn.setObjectName("saveButton")
        update_btn.setFixedWidth(150)
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.clicked.connect(self._check_for_updates)
        update_row.addWidget(update_btn)
        self._content_layout.addLayout(update_row)

    def _check_for_updates(self):
        """Check git remote for new commits and offer to update."""
        import config as cfg
        self._update_label.setText("Checking...")
        self._update_label.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        QApplication.processEvents()

        try:
            # Fetch latest from remote
            subprocess.run(
                ["git", "fetch", "--quiet"],
                cwd=str(cfg.BUNDLE_ROOT),
                capture_output=True, timeout=15,
            )
            # Check if we're behind
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..@{u}"],
                cwd=str(cfg.BUNDLE_ROOT),
                capture_output=True, text=True, timeout=10,
            )
            behind = int(result.stdout.strip()) if result.returncode == 0 else 0

            if behind == 0:
                self._update_label.setText(f"v{cfg.VERSION} — up to date")
                self._update_label.setStyleSheet(
                    "color: rgba(100,255,100,0.7); font-size: 11px;")
            else:
                self._update_label.setText(
                    f"{behind} update{'s' if behind != 1 else ''} available")
                self._update_label.setStyleSheet(
                    "color: rgba(255,200,100,0.9); font-size: 11px;")
                self._offer_update(behind)
        except Exception as e:
            self._update_label.setText(f"Check failed: {e}")
            self._update_label.setStyleSheet(
                "color: rgba(255,100,100,0.7); font-size: 11px;")

    def _offer_update(self, behind: int):
        """Replace the check button with an Update Now button."""
        import config as cfg
        # Find the update row and add an update button
        update_btn = QPushButton(f"Update Now ({behind})")
        update_btn.setObjectName("saveButton")
        update_btn.setFixedWidth(150)
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.setStyleSheet(
            "QPushButton { background: rgba(100,200,100,0.2); color: rgba(100,255,100,0.9); "
            "border: 1px solid rgba(100,255,100,0.3); border-radius: 6px; padding: 6px 12px; "
            "font-size: 12px; font-weight: bold; } "
            "QPushButton:hover { background: rgba(100,200,100,0.35); }"
        )
        update_btn.clicked.connect(lambda: self._do_update(cfg.BUNDLE_ROOT))
        # Add to the parent layout of _update_label
        self._update_label.parent().layout().addWidget(update_btn)

    def _do_update(self, bundle_root):
        """Pull latest changes and notify user."""
        self._update_label.setText("Updating...")
        QApplication.processEvents()
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(bundle_root),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                # Re-read version
                version_file = bundle_root / "VERSION"
                new_version = version_file.read_text().strip() if version_file.exists() else "?"
                self._update_label.setText(
                    f"Updated to v{new_version} — restart to apply")
                self._update_label.setStyleSheet(
                    "color: rgba(100,255,100,0.9); font-size: 11px;")
            else:
                self._update_label.setText(f"Update failed: {result.stderr[:80]}")
                self._update_label.setStyleSheet(
                    "color: rgba(255,100,100,0.7); font-size: 11px;")
        except Exception as e:
            self._update_label.setText(f"Update failed: {e}")
            self._update_label.setStyleSheet(
                "color: rgba(255,100,100,0.7); font-size: 11px;")

    def _switch_to_agent(self, agent_name: str):
        """Switch agent from settings panel."""
        companion = self.parent()
        if companion and hasattr(companion, 'switch_agent'):
            self._close()
            companion.switch_agent(agent_name)

    def _run_new_agent_flow(self):
        """Launch the interactive create_agent.py script in a terminal."""
        import config as cfg
        script = Path(cfg.BUNDLE_ROOT) / "scripts" / "create_agent.py"
        if not script.exists():
            return
        # Open in a new Terminal window so the user can interact
        cmd = (
            f'tell application "Terminal" to do script '
            f'"cd {str(cfg.BUNDLE_ROOT).replace(chr(34), chr(92)+chr(34))} && '
            f'python3 {str(script).replace(chr(34), chr(92)+chr(34))}"'
        )
        subprocess.Popen(["osascript", "-e", cmd])

    def _get_value(self, key):
        """Read the current value from a control."""
        if key not in self._controls:
            return None
        kind = self._controls[key][0]
        if kind == "slider":
            _, slider, scale, decimals = self._controls[key]
            return round(slider.value() / scale, decimals)
        elif kind == "combo":
            return self._controls[key][1].currentText()
        elif kind == "checkbox":
            return self._controls[key][1].isChecked()
        elif kind == "spinbox":
            return self._controls[key][1].value()
        elif kind == "text":
            return self._controls[key][1].text()
        elif kind == "info":
            return self._controls[key][1].text()
        return None

    def _apply_settings(self):
        """Apply current settings to the running config module."""
        import config as cfg
        from core.agent_manager import set_agent_state

        # ── Per-agent states ──
        for name, controls in self._agent_controls.items():
            set_agent_state(
                name,
                muted=controls["muted"].isChecked(),
                enabled=controls["enabled"].isChecked(),
            )

        # Update current agent's mute state on the companion window
        companion = self.parent()
        if companion and hasattr(companion, '_agent_muted'):
            current = cfg.AGENT_NAME
            if current in self._agent_controls:
                companion._agent_muted = self._agent_controls[current]["muted"].isChecked()
                companion._muted = companion._global_muted or companion._agent_muted

        # ── Agent identity ──
        cfg.AGENT_DISPLAY_NAME = self._get_value("agent_display_name")
        cfg.USER_NAME = self._get_value("user_name")
        cfg.OPENING_LINE = self._get_value("opening_line")
        wake_str = self._get_value("wake_words") or ""
        new_wake = [w.strip() for w in wake_str.split(",") if w.strip()]
        wake_changed = new_wake != cfg.WAKE_WORDS
        cfg.WAKE_WORDS = new_wake

        # ── Window ──
        cfg.WINDOW_WIDTH = self._get_value("window_width")
        cfg.WINDOW_HEIGHT = self._get_value("window_height")
        cfg.AVATAR_ENABLED = self._get_value("avatar_enabled")
        cfg.AVATAR_RESOLUTION = self._get_value("avatar_resolution")

        # ── Voice / TTS ──
        cfg.TTS_BACKEND = self._get_value("tts_backend")
        cfg.ELEVENLABS_API_KEY = self._get_value("elevenlabs_api_key")
        cfg.ELEVENLABS_VOICE_ID = self._get_value("elevenlabs_voice_id")
        cfg.ELEVENLABS_MODEL = self._get_value("elevenlabs_model")
        cfg.ELEVENLABS_STABILITY = self._get_value("elevenlabs_stability")
        cfg.ELEVENLABS_SIMILARITY = self._get_value("elevenlabs_similarity")
        cfg.ELEVENLABS_STYLE = self._get_value("elevenlabs_style")
        cfg.TTS_PLAYBACK_RATE = self._get_value("tts_playback_rate")
        cfg.FAL_VOICE_ID = self._get_value("fal_voice_id")

        # ── Input ──
        cfg.INPUT_MODE = self._get_value("input_mode")
        cfg.PTT_KEY = self._get_value("ptt_key")
        cfg.WAKE_WORD_ENABLED = self._get_value("wake_word_enabled")
        cfg.WAKE_CHUNK_SECONDS = self._get_value("wake_chunk_seconds")

        # ── Notifications ──
        cfg.NOTIFICATIONS_ENABLED = self._get_value("notifications_enabled")

        # ── Audio ──
        cfg.SAMPLE_RATE = self._get_value("sample_rate")
        cfg.MAX_RECORD_SEC = self._get_value("max_record_sec")

        # ── Inference ──
        cfg.CLAUDE_BIN = self._get_value("claude_bin")
        cfg.CLAUDE_EFFORT = self._get_value("claude_effort")
        cfg.ADAPTIVE_EFFORT = self._get_value("adaptive_effort")

        # ── Memory ──
        cfg.CONTEXT_SUMMARIES = self._get_value("context_summaries")
        cfg.MAX_CONTEXT_TOKENS = self._get_value("max_context_tokens")
        cfg.VECTOR_SEARCH_WEIGHT = self._get_value("vector_search_weight")
        cfg.EMBEDDING_MODEL = self._get_value("embedding_model")
        cfg.EMBEDDING_DIM = self._get_value("embedding_dim")

        # ── Session ──
        cfg.SESSION_SOFT_LIMIT_MINS = self._get_value("session_soft_limit")

        # ── Heartbeat ──
        cfg.HEARTBEAT_ACTIVE_START = self._get_value("heartbeat_start")
        cfg.HEARTBEAT_ACTIVE_END = self._get_value("heartbeat_end")
        cfg.HEARTBEAT_INTERVAL_MINS = self._get_value("heartbeat_interval")

        # ── Paths ──
        vault_path = self._get_value("obsidian_vault")
        if vault_path:
            cfg.OBSIDIAN_VAULT = Path(vault_path)

        # ── Telegram ──
        cfg.TELEGRAM_BOT_TOKEN = self._get_value("telegram_bot_token")
        cfg.TELEGRAM_CHAT_ID = self._get_value("telegram_chat_id")

        # ── Per-agent tool disabling ──
        disabled = []
        for tool_id, cb in self._tool_checkboxes.items():
            if not cb.isChecked():
                disabled.append(tool_id)
        cfg.DISABLED_TOOLS = disabled
        # Reset MCP config so new disallowed list takes effect
        from core.inference import reset_mcp_config
        reset_mcp_config()

        # Update env vars so child processes inherit
        os.environ["TTS_BACKEND"] = cfg.TTS_BACKEND
        os.environ["ELEVENLABS_API_KEY"] = cfg.ELEVENLABS_API_KEY
        os.environ["ELEVENLABS_VOICE_ID"] = cfg.ELEVENLABS_VOICE_ID
        os.environ["ELEVENLABS_MODEL"] = cfg.ELEVENLABS_MODEL
        os.environ["ELEVENLABS_STABILITY"] = str(cfg.ELEVENLABS_STABILITY)
        os.environ["ELEVENLABS_SIMILARITY"] = str(cfg.ELEVENLABS_SIMILARITY)
        os.environ["ELEVENLABS_STYLE"] = str(cfg.ELEVENLABS_STYLE)
        os.environ["TTS_PLAYBACK_RATE"] = str(cfg.TTS_PLAYBACK_RATE)
        os.environ["INPUT_MODE"] = cfg.INPUT_MODE
        os.environ["CLAUDE_BIN"] = cfg.CLAUDE_BIN
        os.environ["CLAUDE_EFFORT"] = cfg.CLAUDE_EFFORT
        os.environ["ADAPTIVE_EFFORT"] = str(cfg.ADAPTIVE_EFFORT).lower()
        os.environ["WAKE_WORD_ENABLED"] = str(cfg.WAKE_WORD_ENABLED).lower()
        os.environ["AVATAR_ENABLED"] = str(cfg.AVATAR_ENABLED).lower()
        os.environ["NOTIFICATIONS_ENABLED"] = str(cfg.NOTIFICATIONS_ENABLED).lower()

        # Update audio player rate
        if hasattr(self.parent(), '_audio_player'):
            self.parent()._audio_player._rate = str(cfg.TTS_PLAYBACK_RATE)

        # Restart wake word listener if words changed
        companion = self.parent()
        if wake_changed and hasattr(companion, '_wake_listener'):
            if companion._wake_listener:
                companion._stop_wake_listener()
            if companion._wake_enabled:
                companion._start_wake_listener()

        print("  [Settings applied]")

    def _save_settings(self):
        """Write current settings to ~/.atrophy/config.json and agent.json."""
        self._apply_settings()
        import config as cfg

        # ── Save agent.json (agent-specific settings) ──
        manifest_path = cfg.AGENT_DIR / "data" / "agent.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
        else:
            manifest = {}

        manifest["name"] = cfg.AGENT_NAME
        manifest["display_name"] = cfg.AGENT_DISPLAY_NAME
        manifest["user_name"] = cfg.USER_NAME
        manifest["opening_line"] = cfg.OPENING_LINE
        manifest["wake_words"] = cfg.WAKE_WORDS

        manifest.setdefault("voice", {})
        manifest["voice"]["tts_backend"] = cfg.TTS_BACKEND
        manifest["voice"]["elevenlabs_voice_id"] = cfg.ELEVENLABS_VOICE_ID
        manifest["voice"]["elevenlabs_model"] = cfg.ELEVENLABS_MODEL
        manifest["voice"]["elevenlabs_stability"] = cfg.ELEVENLABS_STABILITY
        manifest["voice"]["elevenlabs_similarity"] = cfg.ELEVENLABS_SIMILARITY
        manifest["voice"]["elevenlabs_style"] = cfg.ELEVENLABS_STYLE
        manifest["voice"]["fal_voice_id"] = cfg.FAL_VOICE_ID
        manifest["voice"]["playback_rate"] = cfg.TTS_PLAYBACK_RATE

        manifest.setdefault("display", {})
        manifest["display"]["window_width"] = cfg.WINDOW_WIDTH
        manifest["display"]["window_height"] = cfg.WINDOW_HEIGHT
        manifest["display"]["title"] = self._get_value("window_title") or f"THE ATROPHIED MIND -- {cfg.AGENT_DISPLAY_NAME}"

        manifest.setdefault("heartbeat", {})
        manifest["heartbeat"]["active_start"] = cfg.HEARTBEAT_ACTIVE_START
        manifest["heartbeat"]["active_end"] = cfg.HEARTBEAT_ACTIVE_END
        manifest["heartbeat"]["interval_mins"] = cfg.HEARTBEAT_INTERVAL_MINS

        # Save disabled tools
        manifest["disabled_tools"] = cfg.DISABLED_TOOLS

        manifest.setdefault("telegram", {})
        tg = manifest["telegram"]
        token_env = tg.get("bot_token_env", f"TELEGRAM_BOT_TOKEN_{cfg.AGENT_NAME.upper()}")
        chat_env = tg.get("chat_id_env", f"TELEGRAM_CHAT_ID_{cfg.AGENT_NAME.upper()}")
        manifest["telegram"]["bot_token_env"] = token_env
        manifest["telegram"]["chat_id_env"] = chat_env

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  [Saved agent.json: {manifest_path}]")

        # ── Save config.json (global app settings) ──
        user_cfg = {
            "AGENT": cfg.AGENT_NAME,
            "INPUT_MODE": cfg.INPUT_MODE,
            "WAKE_WORD_ENABLED": str(cfg.WAKE_WORD_ENABLED).lower(),
            "CLAUDE_BIN": cfg.CLAUDE_BIN,
            "CLAUDE_EFFORT": cfg.CLAUDE_EFFORT,
            "ADAPTIVE_EFFORT": str(cfg.ADAPTIVE_EFFORT).lower(),
            "AVATAR_ENABLED": str(cfg.AVATAR_ENABLED).lower(),
            "NOTIFICATIONS_ENABLED": str(cfg.NOTIFICATIONS_ENABLED).lower(),
            "OBSIDIAN_VAULT": str(cfg.OBSIDIAN_VAULT),
        }
        # Secrets go to config.json (user-local, gitignored by nature)
        if cfg.ELEVENLABS_API_KEY:
            user_cfg["ELEVENLABS_API_KEY"] = cfg.ELEVENLABS_API_KEY
        if cfg.TELEGRAM_BOT_TOKEN:
            user_cfg[token_env] = cfg.TELEGRAM_BOT_TOKEN
        if cfg.TELEGRAM_CHAT_ID:
            user_cfg[chat_env] = cfg.TELEGRAM_CHAT_ID

        cfg.save_user_config(user_cfg)
        print(f"  [Saved config.json: {cfg.USER_DATA / 'config.json'}]")

    def _close(self):
        self.hide()
        self.closed.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(14, 14, 16, 245))
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(event)


# ── Input bar ──

class InputBar(QWidget):
    submitted = pyqtSignal(str)
    mic_pressed = pyqtSignal()
    copy_requested = pyqtSignal()  # Cmd+C with no selection → copy companion text
    stop_requested = pyqtSignal()  # stop button pressed during inference

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_BAR_H)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText("Message...")
        self._input.setFont(QFont("Bricolage Grotesque", 14))
        self._input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 0.9);
                padding-left: 20px;
                padding-right: 54px;
                selection-background-color: rgba(255, 255, 255, 0.2);
            }
        """)
        self._input.returnPressed.connect(self._on_submit)
        self._input.installEventFilter(self)

        # Keystroke sounds
        self._keystroke_proc = None
        self._input.textChanged.connect(self._on_keystroke)

        self._mic = QPushButton(self)
        self._mic.setFixedSize(36, 36)
        self._mic.setCursor(Qt.PointingHandCursor)
        self._mic.setStyleSheet("""
            QPushButton { background: transparent; border: none; }
            QPushButton:hover { background: transparent; }
        """)
        self._mic.clicked.connect(self._on_mic_click)
        self._stop_mode = False

    def set_stop_mode(self, active: bool):
        self._stop_mode = active
        self.update()

    def _on_mic_click(self):
        if self._stop_mode:
            self.stop_requested.emit()
        else:
            self.mic_pressed.emit()

    def resizeEvent(self, event):
        w = self.width()
        self._input.setFixedSize(w, _BAR_H)
        self._mic.move(w - 42, 6)
        super().resizeEvent(event)

    def paintEvent(self, event):
        w = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, _BAR_H), _BAR_RADIUS, _BAR_RADIUS)
        p.fillPath(path, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(path)
        cx, cy = w - 24, _BAR_H // 2
        r = 14
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        if self._stop_mode:
            # Stop square
            p.setBrush(QColor(255, 255, 255, 200))
            s = 8
            p.drawRoundedRect(QRectF(cx - s/2, cy - s/2, s, s), 2, 2)
        else:
            # Send arrow
            p.setPen(QPen(QColor(255, 255, 255, 180), 1.8))
            p.setBrush(Qt.NoBrush)
            p.drawLine(cx, cy + 5, cx, cy - 5)
            p.drawLine(cx, cy - 5, cx - 4, cy - 1)
            p.drawLine(cx, cy - 5, cx + 4, cy - 1)
        p.end()

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            mods = event.modifiers()
            if event.key() == Qt.Key_C and (mods & Qt.ControlModifier or mods & Qt.MetaModifier):
                if not self._input.hasSelectedText():
                    self.copy_requested.emit()
                    return True
        return super().eventFilter(obj, event)

    def _on_keystroke(self):
        if self._keystroke_proc is not None and self._keystroke_proc.poll() is None:
            return  # previous sound still playing
        self._keystroke_proc = subprocess.Popen(
            ["afplay", "-v", "0.02", "/System/Library/Sounds/Tink.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _on_submit(self):
        text = self._input.text().strip()
        if text:
            self._input.clear()
            self.submitted.emit(text)

    def focus_input(self):
        self._input.setFocus()


# ── Audio playback queue ──

class AudioPlayer(QThread):
    """Plays audio files sequentially from a queue."""
    file_started = pyqtSignal(int)  # sentence index
    file_done = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._queue = Queue()
        self._running = True
        from config import TTS_PLAYBACK_RATE
        self._rate = str(TTS_PLAYBACK_RATE)

    def enqueue(self, audio_path: str, index: int):
        self._queue.put((audio_path, index))

    def stop(self):
        self._running = False
        self._queue.put(None)

    def run(self):
        rate = self._rate
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except Empty:
                continue
            if item is None:
                break
            audio_path, index = item
            if not audio_path:
                print(f"  [AudioPlayer] empty path for index {index}")
                continue
            import os
            size = os.path.getsize(audio_path) if os.path.exists(audio_path) else -1
            print(f"  [AudioPlayer] playing index={index} size={size} path={audio_path}")
            self.file_started.emit(index)
            try:
                result = subprocess.run(
                    ["afplay", "-r", rate, audio_path],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    print(f"  [AudioPlayer] afplay error: {result.stderr[:200]}")
            except Exception as e:
                print(f"  [AudioPlayer] exception: {e}")
            self.file_done.emit(index)


# ── Main window ──

class CompanionWindow(QWidget):

    def __init__(self, on_input=None, on_synth=None, on_opening=None,
                 system_prompt="", cli_session_id=None, session=None,
                 cached_opening_audio="", dormant=False):
        super().__init__()
        self._on_input = on_input    # unused in streaming mode
        self._on_synth = on_synth    # synthesise_sync
        self._on_opening = on_opening
        self._cached_opening_audio = cached_opening_audio
        self._system = system_prompt
        self._cli_session_id = cli_session_id
        self._session = session
        self._dormant = dormant       # True = don't boot until first shown
        self._switching = False       # True during agent switch animation
        self._worker = None
        self._anims = []
        self._frame = QImage()
        self._scaled_frame = None
        self._shutdown_mode = False
        self._first_sentence_shown = False

        # Conversation history
        # Each entry: {"user": str, "companion": str}
        self._history = []
        self._approx_tokens = 0  # rough context size tracker
        self._compaction_warned = False
        self._needs_memory_flush = False
        self._flush_worker = None

        # Ken Burns drift — slow, gentle movement
        self._drift_x = 0.0
        self._drift_y = 0.0
        self._drift_dx = 0.04
        self._drift_dy = 0.03
        self._drift_timer = QTimer(self)
        self._drift_timer.setInterval(50)
        self._drift_timer.timeout.connect(self._tick_drift)
        self._drift_timer.start()

        # Silence detection (disabled)
        self._silence_timer = None
        self._silence_seconds = 0.0
        self._silence_prompted = False

        # Warm vignette overlay
        self._vignette_opacity = 0.0
        self._vignette_target = 0.0
        self._vignette_img = None  # cached vignette image
        self._vignette_size = (0, 0)  # size it was rendered at

        # PIP transition — video shrinks to bottom-right when artefact is shown
        self._pip_progress = 0.0  # 0.0 = full-bleed, 1.0 = PIP corner
        self._pip_anim = None

        # Iris wipe — agent switch transition
        self._iris_progress = 0.0  # 0.0 = fully open, 1.0 = fully closed
        self._iris_phase = None    # "closing" or "opening"

        self.setWindowTitle(AGENT_DISPLAY_NAME)
        self.resize(_W, _H)
        self.setMinimumSize(360, 480)

        # Normal window — allows macOS tiling (ctrl+left/right)
        # Pin on top can be toggled later if needed

        # Audio player thread
        self._audio_player = AudioPlayer()
        self._audio_player.file_started.connect(self._on_audio_started)
        self._audio_player.file_done.connect(self._on_audio_done)
        self._audio_player.start()

        # Mode flags
        self._global_muted = False   # Global mute (main panel button)
        self._muted = False          # Combined: global OR per-agent
        self._eye_mode = False       # True = minimal (chat bar only)

        # Multi-agent
        from core.agent_manager import discover_agents, get_agent_state
        import config as _cfg
        self._agents = discover_agents()
        self._current_agent = _cfg.AGENT_NAME
        _agent_state = get_agent_state(self._current_agent)
        self._agent_muted = _agent_state.get("muted", False)
        self._muted = self._global_muted or self._agent_muted

        # Wake word detection
        self._wake_listener = None
        self._wake_enabled = False

        # Idle → away timer (10 min no input)
        from core.status import IDLE_TIMEOUT_SECS, set_active
        set_active()  # app launch = active
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        self._idle_timer.start(IDLE_TIMEOUT_SECS * 1000)

        # Boot overlay — black screen that fades out when ready
        self._boot_opacity = 1.0
        self._booting = True

        self._build_video()
        self._build_overlays()
        self._build_input_bar()
        self._build_mode_buttons()
        self._build_status_bar()
        self._build_canvas()
        self._reflow()

        # Hide UI during boot
        self._bar.hide()
        self._transcript.hide()
        self._mute_btn.hide()
        self._eye_btn.hide()
        self._min_btn.hide()
        self._wake_btn.hide()
        self._artefact_btn.hide()
        self._settings_btn.hide()

        # Centre status bar for boot
        self._status_bar.start("connecting...")
        self._centre_status_bar()

        # Dormant mode — skip boot sequence until first shown
        if self._dormant:
            self._opening_worker = None
            self._status_bar.stop()
            return

        # Dynamic opening
        self._start_boot_sequence()

    def _start_boot_sequence(self):
        """Begin the opening line generation and boot animation."""
        on_opening = self._on_opening
        on_synth = self._on_synth
        if on_opening:
            if self._cached_opening_audio:
                synth_for_opening = None
                self._status_bar.set_progress(0.5, "loading cached opening...")
            else:
                self._status_bar.set_progress(0.1, "generating opening...")
                synth_for_opening = on_synth
            self._opening_worker = OpeningWorker(on_opening, synth_for_opening)
            self._opening_worker.ready.connect(self._on_opening_ready)
            self._opening_worker.error_signal.connect(self._on_opening_error)
            QTimer.singleShot(300, self._opening_worker.start)
        else:
            def _default_boot():
                self._present("Ready. Where are we?")
                self._history.append({"user": "", "companion": "Ready. Where are we?"})
                self._boot_complete()
            QTimer.singleShot(600, _default_boot)

    def wake_up(self):
        """Wake from dormant mode — called on first show."""
        if not self._dormant:
            return
        self._dormant = False
        self._status_bar.start("waking up...")
        self._centre_status_bar()
        self._start_boot_sequence()

    def _centre_status_bar(self):
        # During boot — centre horizontally, middle of screen
        w = self.width()
        bar_w = w - _PAD * 4
        self._status_bar.setFixedWidth(bar_w)
        self._status_bar.move((w - bar_w) // 2, self.height() // 2)

    def _boot_complete(self):
        """Fade from black to live UI."""
        self._status_bar.stop()
        self._bar.show()
        self._transcript.show()
        self._mute_btn.show()
        self._eye_btn.show()
        self._min_btn.show()
        self._wake_btn.show()
        self._artefact_btn.show()
        self._settings_btn.show()
        self._position_status_bar()  # restore normal position

        # Reveal animation — iris open for agent switch, fade for cold boot
        if self._iris_phase == "closing":
            # Iris open — circle expands from center to reveal new agent
            self._iris_phase = "opening"
            self._boot_anim = QPropertyAnimation(self, b"iris_progress", self)
            self._boot_anim.setStartValue(0.0)
            self._boot_anim.setEndValue(1.0)
            self._boot_anim.setDuration(500)
            self._boot_anim.setEasingCurve(QEasingCurve.OutQuad)
            self._boot_anim.finished.connect(self._on_boot_faded)
            self._boot_anim.start()
        else:
            # Standard fade from black
            self._boot_anim = QPropertyAnimation(self, b"boot_opacity", self)
            self._boot_anim.setStartValue(1.0)
            self._boot_anim.setEndValue(0.0)
            self._boot_anim.setDuration(600)
            self._boot_anim.setEasingCurve(QEasingCurve.InOutQuad)
            self._boot_anim.finished.connect(self._on_boot_faded)
            self._boot_anim.start()

    def _on_boot_faded(self):
        self._booting = False
        self._switching = False
        # Reset iris state
        self._iris_progress = 0.0
        self._iris_phase = None
        # Schedule a journal nudge — random point 15-45 mins into session
        delay_ms = random.randint(15 * 60_000, 45 * 60_000)
        self._journal_nudge_timer = QTimer(self)
        self._journal_nudge_timer.setSingleShot(True)
        self._journal_nudge_timer.timeout.connect(self._do_journal_nudge)
        self._journal_nudge_timer.start(delay_ms)

        # SENTINEL coherence monitor — every 5 minutes
        self._coherence_timer = QTimer(self)
        self._coherence_timer.setInterval(5 * 60_000)  # 300 seconds
        self._coherence_timer.timeout.connect(self._do_coherence_check)
        self._coherence_timer.start()
        self._coherence_worker = None

        # Timer request watcher — check every 2 seconds for MCP-requested timers
        self._timer_watcher = QTimer(self)
        self._timer_watcher.setInterval(2000)
        self._timer_watcher.timeout.connect(self._check_timer_requests)
        self._timer_watcher.start()
        self._active_timers = []

        # Inbox watcher — check all agents' message queues every 30 seconds
        self._inbox_timer = QTimer(self)
        self._inbox_timer.setInterval(30_000)
        self._inbox_timer.timeout.connect(self._check_inbox)
        self._inbox_timer.start()

        # Deferral request watcher — check every 2 seconds for agent handoffs
        self._deferral_watcher = QTimer(self)
        self._deferral_watcher.setInterval(2000)
        self._deferral_watcher.timeout.connect(self._check_deferral_requests)
        self._deferral_watcher.start()
        self._deferral_count = 0
        self._deferral_window_start = 0.0

        # Artefact request watcher — check every 2 seconds for approval requests
        self._artefact_watcher = QTimer(self)
        self._artefact_watcher.setInterval(2000)
        self._artefact_watcher.timeout.connect(self._check_artefact_requests)
        self._artefact_watcher.start()

        # Artefact display watcher — check every 2 seconds for new artefacts to show
        self._artefact_display_watcher = QTimer(self)
        self._artefact_display_watcher.setInterval(2000)
        self._artefact_display_watcher.timeout.connect(self._check_artefact_display)
        self._artefact_display_watcher.start()

        self._boot_anim = None
        self.update()

    def _get_boot_opacity(self):
        return self._boot_opacity

    def _set_boot_opacity(self, val):
        self._boot_opacity = val
        self.update()

    boot_opacity = pyqtProperty(float, _get_boot_opacity, _set_boot_opacity)

    def _get_pip_progress(self):
        return self._pip_progress

    def _set_pip_progress(self, val):
        self._pip_progress = val
        self._scaled_frame = None  # force re-render at new size
        self.update()

    pip_progress = pyqtProperty(float, _get_pip_progress, _set_pip_progress)

    def _get_iris_progress(self):
        return self._iris_progress

    def _set_iris_progress(self, val):
        self._iris_progress = val
        self.update()

    iris_progress = pyqtProperty(float, _get_iris_progress, _set_iris_progress)

    def _on_opening_ready(self, text, audio_path):
        self._opening_worker = None
        self._present(text)
        play_audio = self._cached_opening_audio or audio_path
        if play_audio and not self._muted:
            self._audio_player.enqueue(play_audio, 0)
        self._cached_opening_audio = ""
        if self._session:
            self._session.add_turn("agent", text)
        self._history.append({"user": "", "companion": text})
        self._boot_complete()
        # Drain queued messages (morning brief, etc.) after a short pause
        QTimer.singleShot(3000, self._drain_message_queue)

    def _drain_message_queue(self):
        """Check for queued messages from cron jobs and enqueue them for paced delivery."""
        from core.agent_manager import discover_agents, get_agent_state

        # Drain active agent's queue
        self._drain_agent_queue(self._current_agent, is_active=True)

        # Check other agents' queues — notify but don't speak
        for agent in discover_agents():
            if agent["name"] != self._current_agent:
                self._drain_agent_queue(agent["name"], is_active=False)

    def _drain_agent_queue(self, agent_name: str, is_active: bool):
        """Drain one agent's message queue. Active agent = present + audio. Others = notify only."""
        import fcntl
        from config import USER_DATA
        queue_file = USER_DATA / "agents" / agent_name / "data" / ".message_queue.json"
        if not queue_file.exists():
            return

        lock_path = queue_file.with_suffix(".lock")
        try:
            with open(lock_path, "w") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                queue = json.loads(queue_file.read_text())
                queue_file.unlink()
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception:
            return
        if not queue:
            return

        from core.agent_manager import get_agent_state
        agent_state = get_agent_state(agent_name)
        agent_muted = agent_state.get("muted", False)

        for i, msg in enumerate(queue):
            text = msg.get("text", "")
            audio = msg.get("audio_path", "")
            source = msg.get("source", "unknown")
            if not text:
                continue

            # Verify audio file still exists
            if audio and not Path(audio).exists():
                audio = ""

            if is_active:
                # Pace messages — delay between each one
                delay = i * 4000  # 4 seconds between messages
                QTimer.singleShot(delay, lambda t=text, a=audio, m=agent_muted: (
                    self._deliver_transmission(t, a, m)
                ))
            else:
                # Inactive agent — macOS notification only, don't interrupt
                # Load display name
                from config import _find_agent_dir
                manifest = _find_agent_dir(agent_name) / "data" / "agent.json"
                display_name = agent_name.title()
                if manifest.exists():
                    try:
                        display_name = json.loads(manifest.read_text()).get("display_name", display_name)
                    except Exception:
                        pass

                from core.notify import send_notification
                body = text[:200] + "..." if len(text) > 200 else text
                send_notification(display_name, body, subtitle=source)

    def _deliver_transmission(self, text: str, audio_path: str, agent_muted: bool):
        """Deliver a single queued message with text + optional audio."""
        self._present(text)
        if self._session:
            self._session.add_turn("agent", text)
        # Audio only if not globally muted AND not agent-muted
        if audio_path and not self._muted and not agent_muted:
            self._audio_player.enqueue(audio_path, 0)

    def _on_opening_error(self, msg):
        self._opening_worker = None
        print(f"  [Opening error: {msg}]")
        self._present("Ready. Where are we?")
        self._history.append({"user": "", "companion": "Ready. Where are we?"})
        self._boot_complete()

    # ── Silence detection ──

    def _tick_silence(self):
        # Only count silence when not thinking/streaming/waiting for opening
        if self._worker is not None or getattr(self, '_opening_worker', None) is not None:
            self._silence_seconds = 0.0
            return
        self._silence_seconds += 1.0
        if self._silence_prompted:
            return
        from core.agency import silence_prompt
        prompt = silence_prompt(self._silence_seconds)
        if prompt:
            self._silence_prompted = True
            self._present(prompt)
            # Optionally synthesise and play
            if self._on_synth and not self._muted:
                import threading
                def _synth_and_play():
                    try:
                        path = self._on_synth(prompt)
                        if path:
                            self._audio_player.enqueue(str(path), 0)
                    except Exception:
                        pass
                threading.Thread(target=_synth_and_play, daemon=True).start()

    # ── Video ──

    def _build_video(self):
        # Single player + surface — ambient_loop.mp4 is pre-built 10-min cycle
        self._surface = FrameGrabSurface(self)
        self._surface.frame_ready.connect(self._on_frame)
        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._surface)
        self._player.setMuted(True)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        if IDLE_LOOP.exists():
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(IDLE_LOOP))))
            self._player.play()

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    def _on_frame(self, img):
        self._frame = img
        self._scaled_frame = None
        if not self._eye_mode:
            self.update()

    def _tick_drift(self):
        try:
            if self._eye_mode:
                return
            self._drift_x += self._drift_dx
            if abs(self._drift_x) > 2.0:
                self._drift_dx = -self._drift_dx
            self._drift_y += self._drift_dy
            if abs(self._drift_y) > 2.0:
                self._drift_dy = -self._drift_dy
            # Smooth vignette interpolation — only repaint when actually changing
            diff = self._vignette_target - self._vignette_opacity
            if abs(diff) > 0.001:
                self._vignette_opacity += diff * 0.05
                self.update()
        except RuntimeError:
            pass  # widget deleted during shutdown


    def _video_rect(self):
        """Calculate the video draw rect, interpolating between full-bleed and PIP."""
        win_w, win_h = self.width(), self.height()
        img_w, img_h = self._frame.width(), self._frame.height()
        if img_w == 0 or img_h == 0:
            return 0, 0, win_w, win_h

        # Full-bleed rect
        scale_full = min(win_w / img_w, win_h / img_h) * 1.01
        sw_full = int(img_w * scale_full)
        sh_full = int(img_h * scale_full)
        x_full = (win_w - sw_full) // 2 + int(self._drift_x)
        y_full = (win_h - sh_full) // 2 + int(self._drift_y)

        if self._pip_progress < 0.001:
            return x_full, y_full, sw_full, sh_full

        # PIP rect — bottom-right corner, 25% of window size
        pip_w = int(win_w * 0.25)
        pip_h = int(pip_w * img_h / img_w)
        pip_margin = 16
        x_pip = win_w - pip_w - pip_margin
        y_pip = win_h - pip_h - pip_margin - _BAR_H - 8

        # Smooth interpolation
        t = self._pip_progress
        # Ease curve (cubic)
        t = t * t * (3 - 2 * t)
        x = int(x_full + (x_pip - x_full) * t)
        y = int(y_full + (y_pip - y_full) * t)
        w = int(sw_full + (pip_w - sw_full) * t)
        h = int(sh_full + (pip_h - sh_full) * t)
        return x, y, w, h

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._eye_mode or self._frame.isNull():
            p.fillRect(self.rect(), QColor(18, 18, 20))
            p.end()
            return
        win_w, win_h = self.width(), self.height()

        # Black background
        p.fillRect(self.rect(), QColor(0, 0, 0))

        # Video frame — full-bleed or PIP depending on _pip_progress
        vx, vy, vw, vh = self._video_rect()

        # Scale frame to target size (cached)
        if (self._scaled_frame is None
                or self._scaled_frame.width() != vw
                or self._scaled_frame.height() != vh):
            self._scaled_frame = self._frame.scaled(
                vw, vh, Qt.IgnoreAspectRatio, Qt.FastTransformation,
            )

        if self._pip_progress > 0.01:
            # PIP mode — clip to rounded rect with shadow
            p.save()
            pip_radius = int(8 + 4 * self._pip_progress)
            pip_path = QPainterPath()
            pip_path.addRoundedRect(QRectF(vx, vy, vw, vh), pip_radius, pip_radius)
            # Shadow
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, int(80 * self._pip_progress)))
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(
                QRectF(vx + 2, vy + 2, vw, vh), pip_radius, pip_radius
            )
            p.drawPath(shadow_path)
            # Clip and draw video
            p.setClipPath(pip_path)
            p.drawImage(vx, vy, self._scaled_frame)
            # Thin border
            p.setClipping(False)
            p.setPen(QPen(QColor(255, 255, 255, int(30 * self._pip_progress)), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(pip_path)
            p.restore()
        else:
            # Full-bleed — no clipping needed
            p.drawImage(vx, vy, self._scaled_frame)

        # Warm vignette overlay (only in full-bleed mode)
        if self._vignette_opacity > 0.01 and self._pip_progress < 0.5:
            if self._vignette_img is None or self._vignette_size != (win_w, win_h):
                vig = QImage(win_w, win_h, QImage.Format_ARGB32_Premultiplied)
                vig.fill(QColor(0, 0, 0, 0))
                vp = QPainter(vig)
                cx, cy = win_w / 2, win_h / 2
                radius = max(win_w, win_h) * 0.7
                grad = QRadialGradient(cx, cy, radius)
                grad.setColorAt(0.0, QColor(0, 0, 0, 0))
                grad.setColorAt(1.0, QColor(40, 25, 10, 120))
                vp.fillRect(vig.rect(), grad)
                vp.end()
                self._vignette_img = vig
                self._vignette_size = (win_w, win_h)
            fade = 1.0 - self._pip_progress * 2  # fade out as we go to PIP
            p.setOpacity(self._vignette_opacity * max(0, fade))
            p.drawImage(0, 0, self._vignette_img)
            p.setOpacity(1.0)

        # Iris wipe — circular mask for agent switch transitions
        if self._iris_progress > 0.001:
            cx, cy = win_w / 2, win_h / 2
            max_radius = (win_w ** 2 + win_h ** 2) ** 0.5 / 2
            # Iris closes: circle shrinks to 0. Iris opens: circle grows from 0.
            if self._iris_phase == "closing":
                radius = max_radius * (1.0 - self._iris_progress)
            else:  # opening
                radius = max_radius * self._iris_progress

            # Draw the mask: fill everything outside the circle with black
            mask = QPainterPath()
            mask.addRect(QRectF(0, 0, win_w, win_h))
            circle = QPainterPath()
            circle.addEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
            mask = mask.subtracted(circle)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0))
            p.drawPath(mask)

        # Boot overlay — black screen that fades out when ready
        if self._booting and self._boot_opacity > 0.001:
            p.fillRect(self.rect(), QColor(0, 0, 0, int(255 * self._boot_opacity)))
        p.end()

    # ── Overlays ──

    def _build_overlays(self):
        self._transcript = TranscriptOverlay(self)

    # ── Input bar ──

    def _build_input_bar(self):
        self._bar = InputBar(self)
        bar_w = self.width() - _PAD * 2
        self._bar.setFixedSize(bar_w, _BAR_H)
        self._bar.move(_PAD, self.height() - _PAD - _BAR_H)
        self._bar.submitted.connect(self._on_user_input)
        self._bar.copy_requested.connect(self._transcript.copy_last_companion)
        self._bar.stop_requested.connect(self._on_stop)
        self._bar.raise_()

        # Metrics label — small text above right side of input bar
        self._metrics_label = QLabel(self)
        self._metrics_label.setStyleSheet(
            "color: rgba(255,255,255,0.25); font-size: 10px; background: transparent;"
        )
        self._metrics_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self._metrics_label.setFixedHeight(14)
        self._metrics_label.hide()
        self._response_start_time = None

        # Global Cmd+C shortcut — copies last companion message when no text selected
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        copy_shortcut = QShortcut(QKeySequence.Copy, self)
        copy_shortcut.activated.connect(self._handle_copy)
        self._copy_shortcut = copy_shortcut  # prevent gc

    def _update_metrics_label(self, response_tokens=0):
        """Update the small metrics display above the input bar."""
        import time as _time
        import config as cfg
        parts = []

        # Response time
        if self._response_start_time:
            elapsed = _time.time() - self._response_start_time
            parts.append(f"{elapsed:.1f}s")
            self._response_start_time = None

        # Token estimate for this response
        if response_tokens > 0:
            if response_tokens >= 1000:
                parts.append(f"~{response_tokens / 1000:.1f}k tok")
            else:
                parts.append(f"~{response_tokens} tok")

        # Context usage %
        max_tokens = cfg.MAX_CONTEXT_TOKENS
        if max_tokens > 0:
            pct = min(100, (self._approx_tokens / max_tokens) * 100)
            parts.append(f"{pct:.0f}% ctx")

        if parts:
            self._metrics_label.setText("  ".join(parts))
            self._position_metrics_label()
            self._metrics_label.show()

    def _position_metrics_label(self):
        """Position metrics label above right side of input bar."""
        left, right, _, h = self._content_rect()
        content_w = right - left
        bar_y = h - _PAD - _BAR_H
        self._metrics_label.setFixedWidth(content_w)
        self._metrics_label.move(left, bar_y - 16)

    def _handle_copy(self):
        """Global Cmd+C handler — copy selected transcript text, input text, or last companion message."""
        if self._bar._input.hasSelectedText():
            self._bar._input.copy()
        else:
            self._transcript.copy_last_companion()  # copies selection if any, else last msg

    # ── Mode toggle buttons ──

    def _build_mode_buttons(self):
        self._mute_btn = _MuteButton(self)
        self._mute_btn.clicked.connect(self._toggle_mute)

        self._eye_btn = _EyeButton(self)
        self._eye_btn.clicked.connect(self._toggle_eye)

        self._min_btn = _MinimizeButton(self)
        self._min_btn.clicked.connect(self._minimize_to_tray)

        self._wake_btn = _WakeButton(self)
        self._wake_btn.clicked.connect(self._toggle_wake)

        self._artefact_btn = _ArtefactButton(self)
        self._artefact_btn.clicked.connect(self._toggle_artefact_gallery)

        self._settings_btn = _SettingsButton(self)
        self._settings_btn.clicked.connect(self._toggle_settings)

        self._call_btn = _CallButton(self)
        self._call_btn.clicked.connect(self._toggle_call)
        self._voice_call = None  # VoiceCall thread

        # Settings panel (tabbed modal)
        self._settings_panel = SettingsModal(self)
        self._settings_panel.closed.connect(lambda: self._settings_btn.set_active(False))
        self._settings_open = False

        # Artefact overlay and gallery
        import config as cfg
        self._artefact_overlay = ArtefactOverlay(self)
        self._artefact_overlay.dismissed.connect(self._animate_from_pip)
        self._artefact_gallery = ArtefactGallery(
            str(cfg.ARTEFACT_INDEX_FILE),
            on_select=self._on_artefact_selected,
            parent=self,
        )

        # Keyboard shortcut: Cmd+Shift+W to toggle wake word
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        wake_shortcut = QShortcut(QKeySequence("Ctrl+Shift+W"), self)
        wake_shortcut.activated.connect(self._toggle_wake)
        self._wake_shortcut = wake_shortcut  # prevent gc

        # Cmd+, for settings
        settings_shortcut = QShortcut(QKeySequence("Meta+,"), self)
        settings_shortcut.activated.connect(self._toggle_settings)
        self._settings_shortcut = settings_shortcut

        self._position_mode_buttons()

    def _position_mode_buttons(self):
        _, right, _, _ = self._content_rect()
        btn_y = _PAD
        self._eye_btn.move(right - 34, btn_y)
        self._mute_btn.move(right - 34 - 38, btn_y)
        self._min_btn.move(right - 34 - 38 - 38, btn_y)
        self._wake_btn.move(right - 34 - 38 - 38 - 38, btn_y)
        self._call_btn.move(right - 34 - 38 - 38 - 38 - 38, btn_y)
        self._artefact_btn.move(right - 34 - 38 - 38 - 38 - 38 - 38, btn_y)
        self._settings_btn.move(right - 34 - 38 - 38 - 38 - 38 - 38 - 38, btn_y)

    def _toggle_settings(self):
        self._settings_open = not self._settings_open
        self._settings_btn.set_active(self._settings_open)
        if self._settings_open:
            self._settings_panel.setGeometry(0, 0, self.width(), self.height())
            self._settings_panel.show()
            self._settings_panel.raise_()
        else:
            self._settings_panel.hide()

    def _toggle_call(self):
        """Start or end a voice call."""
        if self._voice_call and self._voice_call.isRunning():
            # End call
            self._voice_call.stop()
            self._call_btn.set_active(False)
            self._call_btn.set_status("idle")
            self._status_bar.set_status("")
            return

        # Start call
        from voice.call import VoiceCall
        self._voice_call = VoiceCall(
            system_prompt=self._system,
            cli_session_id=self._session.cli_session_id if self._session else None,
            session=self._session,
            synth_fn=self._on_synth,
        )
        self._voice_call.status_changed.connect(self._on_call_status)
        self._voice_call.user_said.connect(self._on_call_user_said)
        self._voice_call.agent_said.connect(self._on_call_agent_said)
        self._voice_call.error.connect(lambda e: print(f"  [Call] {e}"))
        self._voice_call.call_ended.connect(self._on_call_ended)

        self._call_btn.set_active(True)
        self._call_btn.set_status("listening")
        self._status_bar.start("Call active", indeterminate=True)
        self._voice_call.start()

    def _on_call_status(self, status: str):
        self._call_btn.set_status(status)

    def _on_call_user_said(self, text: str):
        self._transcript.add_message("user", text)

    def _on_call_agent_said(self, text: str):
        self._transcript.add_message("companion", _strip_tags(text))

    def _on_call_ended(self):
        self._call_btn.set_active(False)
        self._call_btn.set_status("idle")
        self._status_bar.stop()
        # Sync CLI session ID back from the call
        if self._voice_call and self._session:
            new_id = self._voice_call.cli_session_id
            if new_id and new_id != self._session.cli_session_id:
                self._session.set_cli_session_id(new_id)
        self._voice_call = None

    def _minimize_to_tray(self):
        self.hide()

    def changeEvent(self, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            # Intercept native minimize (Cmd+M / yellow button) → hide to tray instead
            event.ignore()
            QTimer.singleShot(0, self._minimize_to_tray)
            return
        super().changeEvent(event)

    def _build_status_bar(self):
        self._status_bar = StatusBar(self)
        self._position_status_bar()

    def _position_status_bar(self):
        # Sits as top stroke of the chat bar — same x/width, just above it
        bar_x = self._bar.x()
        bar_y = self._bar.y()
        bar_w = self._bar.width()
        self._status_bar.setFixedWidth(bar_w)
        self._status_bar.move(bar_x, bar_y - 2)

    def _toggle_mute(self):
        """Toggle global mute — overrides all per-agent mute states."""
        self._global_muted = not self._global_muted
        self._muted = self._global_muted or self._agent_muted
        self._mute_btn.set_active(self._global_muted)

    def _toggle_wake(self):
        """Toggle wake word listening on/off."""
        self._wake_enabled = not self._wake_enabled
        self._wake_btn.set_active(self._wake_enabled)

        if self._wake_enabled:
            self._start_wake_listener()
        else:
            self._stop_wake_listener()

    def _start_wake_listener(self):
        """Start the wake word listener."""
        if self._wake_listener is not None:
            return
        try:
            from voice.wake_word import WakeWordListener
            self._wake_listener = WakeWordListener(
                callback=self._on_wake_word_detected,
            )
            self._wake_listener.start()
            self._status_bar.start("listening for wake word...")
            QTimer.singleShot(2000, self._status_bar.stop)
        except Exception as e:
            print(f"  [Wake word error: {e}]")
            self._wake_enabled = False
            self._wake_btn.set_active(False)

    def _stop_wake_listener(self):
        """Stop the wake word listener."""
        if self._wake_listener:
            self._wake_listener.stop()
            self._wake_listener = None

    def _on_wake_word_detected(self):
        """Called from the wake word thread when a wake word is heard."""
        # Schedule UI work on the main thread via QTimer
        QTimer.singleShot(0, self._handle_wake_activation)

    def _handle_wake_activation(self):
        """Main-thread handler for wake word detection."""
        if not self._wake_enabled:
            return

        # Don't activate if already processing a turn
        if self._worker is not None:
            if self._wake_listener:
                self._wake_listener.resume()
            return

        # Flash status bar to indicate activation
        self._status_bar.start("wake word detected — recording...")

        # Play subtle activation sound
        import threading
        threading.Thread(
            target=lambda: subprocess.run(
                ["afplay", "-v", "0.15", "/System/Library/Sounds/Pop.aiff"],
                capture_output=True,
            ),
            daemon=True,
        ).start()

        # Record full voice input using sounddevice, then transcribe
        import threading as _thr
        def _record_and_transcribe():
            try:
                import numpy as np
                import sounddevice as sd
                from config import SAMPLE_RATE, CHANNELS
                from voice.stt import transcribe

                # Record up to 15 seconds (stop on 1.5s silence)
                max_seconds = 15
                chunk_size = int(SAMPLE_RATE * 0.5)  # 500ms chunks
                silence_threshold = 0.005
                silence_chunks_needed = 3  # 1.5s of silence to stop
                max_chunks = int(max_seconds / 0.5)

                frames = []
                silence_count = 0

                for _ in range(max_chunks):
                    chunk = sd.rec(
                        chunk_size,
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype="float32",
                        blocking=True,
                    )
                    frames.append(chunk)

                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    if rms < silence_threshold:
                        silence_count += 1
                        if silence_count >= silence_chunks_needed and len(frames) > 2:
                            break
                    else:
                        silence_count = 0

                if not frames:
                    QTimer.singleShot(0, self._wake_recording_done)
                    return

                audio = np.concatenate(frames, axis=0).flatten()

                if len(audio) < SAMPLE_RATE * 0.3:
                    QTimer.singleShot(0, self._wake_recording_done)
                    return

                text = transcribe(audio)
                if text and len(text.strip()) >= 2:
                    QTimer.singleShot(0, lambda: self._wake_input_ready(text.strip()))
                else:
                    QTimer.singleShot(0, self._wake_recording_done)

            except Exception as e:
                print(f"  [Wake record error: {e}]")
                QTimer.singleShot(0, self._wake_recording_done)

        _thr.Thread(target=_record_and_transcribe, daemon=True).start()

    def _wake_input_ready(self, text: str):
        """Voice input from wake word activation is ready."""
        self._status_bar.stop()
        # Pause wake listener during the conversation turn
        if self._wake_listener:
            self._wake_listener.pause()
        # Feed the text into the normal input pipeline
        self._on_user_input(text)

    def _wake_recording_done(self):
        """Wake recording finished with no usable input."""
        self._status_bar.stop()
        if self._wake_listener:
            self._wake_listener.resume()

    # ── Agent switching ──

    def switch_agent(self, agent_name: str):
        """Switch to a different agent with fade animation."""
        if agent_name == self._current_agent:
            return
        if self._switching:
            return
        if self._worker is not None:
            self._status_bar.start("finish conversation first")
            QTimer.singleShot(2000, self._status_bar.stop)
            return

        self._switching = True
        self._switch_target = agent_name

        # Stop background services
        if self._wake_listener:
            self._stop_wake_listener()
        if hasattr(self, '_coherence_timer') and self._coherence_timer:
            self._coherence_timer.stop()
        if hasattr(self, '_journal_nudge_timer') and self._journal_nudge_timer:
            self._journal_nudge_timer.stop()

        # Iris wipe — circle closes to center, swaps agent, circle opens
        self._iris_phase = "closing"
        self._switch_anim = QPropertyAnimation(self, b"iris_progress", self)
        self._switch_anim.setStartValue(0.0)
        self._switch_anim.setEndValue(1.0)
        self._switch_anim.setDuration(400)
        self._switch_anim.setEasingCurve(QEasingCurve.InQuad)
        self._switch_anim.finished.connect(self._on_switch_faded_out)
        self._switch_anim.start()

    def _on_switch_faded_out(self):
        """At peak black — swap everything, then fade back in."""
        import threading
        from core.agent_manager import reload_agent_config, get_agent_state
        from core.context import load_system_prompt
        from core import memory

        target = self._switch_target

        # End old session in background (summary generation can be slow)
        old_session = self._session
        old_system = self._system
        if old_session:
            threading.Thread(
                target=lambda: old_session.end(old_system),
                daemon=True,
            ).start()

        # Reload config for new agent
        reload_agent_config(target)
        from core.inference import reset_mcp_config
        reset_mcp_config()
        import config as cfg

        # Update state
        self._current_agent = target
        agent_state = get_agent_state(target)
        self._agent_muted = agent_state.get("muted", False)
        self._muted = self._global_muted or self._agent_muted

        # Update UI
        self.setWindowTitle(cfg.AGENT_DISPLAY_NAME)
        self._transcript.clear_messages()

        # Swap video if available
        idle_loop = cfg.IDLE_LOOP
        if idle_loop.exists():
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(idle_loop))))
            self._player.play()
        else:
            self._player.stop()
            self._frame = QImage()

        # Re-init memory and session
        memory.init_db()
        from core.session import Session
        self._session = Session()
        self._session.start()
        self._system = load_system_prompt()
        self._cli_session_id = self._session.cli_session_id
        self._history.clear()
        self._approx_tokens = 0

        # Update mute button visual
        self._mute_btn.set_active(self._global_muted)

        # Show agent name flash
        self._flash_agent_name(cfg.AGENT_DISPLAY_NAME)

        # Start boot sequence (generates opening line, fades in)
        self._start_boot_sequence()

    def _flash_agent_name(self, name: str):
        """Show agent name centred, fades out after 2 seconds."""
        if hasattr(self, '_agent_label') and self._agent_label:
            self._agent_label.deleteLater()

        lbl = QLabel(name.upper(), self)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "color: rgba(255,255,255,0.8); font-size: 28px; font-weight: bold; "
            "letter-spacing: 6px; background: transparent;"
        )
        lbl.setFixedSize(self.width(), 60)
        lbl.move(0, self.height() // 2 - 50)
        lbl.show()
        lbl.raise_()
        self._agent_label = lbl

        def _fade_label():
            if hasattr(self, '_agent_label') and self._agent_label:
                self._agent_label.deleteLater()
                self._agent_label = None

        QTimer.singleShot(2500, _fade_label)

    # ── Agent deferral (codec-style handoff) ──

    def _check_deferral_requests(self):
        """Poll for deferral requests written by the MCP defer_to_agent tool."""
        # Don't process during active inference or switching
        if self._worker is not None or self._switching or self._booting:
            return
        import config as cfg
        deferral_file = cfg.DATA_DIR / ".deferral_request.json"
        if not deferral_file.exists():
            return
        try:
            data = json.loads(deferral_file.read_text())
            deferral_file.unlink()
        except Exception:
            return

        target = data.get("target", "")
        if not target or target == self._current_agent:
            return

        # Anti-loop: max 3 deferrals in 60 seconds
        import time as _time
        now = _time.time()
        if now - self._deferral_window_start > 60:
            self._deferral_count = 0
            self._deferral_window_start = now
        self._deferral_count += 1
        if self._deferral_count > 3:
            print("  [deferral] suppressed — too many in 60s")
            return

        self._defer_to_agent(target, data)

    def _defer_to_agent(self, target: str, deferral_data: dict):
        """Codec-style handoff to another agent. No boot sequence, no transcript clear."""
        if self._switching:
            return

        self._switching = True
        self._switch_target = target
        self._deferral_data = deferral_data

        # Stop wake listener
        if self._wake_listener:
            self._stop_wake_listener()

        # Kill audio — current agent's speech stops
        self._kill_audio()

        # Iris wipe — fast, like switching channels
        self._iris_phase = "closing"
        self._switch_anim = QPropertyAnimation(self, b"iris_progress", self)
        self._switch_anim.setStartValue(0.0)
        self._switch_anim.setEndValue(1.0)
        self._switch_anim.setDuration(250)
        self._switch_anim.setEasingCurve(QEasingCurve.InQuad)
        self._switch_anim.finished.connect(self._on_deferral_faded_out)
        self._switch_anim.start()

    def _on_deferral_faded_out(self):
        """At peak black during deferral — swap agent, inject context, respond."""
        from core.agent_manager import (
            reload_agent_config, get_agent_state,
            suspend_agent_session, resume_agent_session,
        )
        from core.context import load_system_prompt
        from core.inference import reset_mcp_config
        from core import memory

        target = self._switch_target
        deferral = self._deferral_data
        source_agent = self._current_agent

        # Suspend current agent's session (don't end it — preserves CLI conversation)
        suspend_agent_session(
            source_agent,
            cli_session_id=self._cli_session_id,
            session=self._session,
        )

        # Reload config for target agent
        reload_agent_config(target)
        reset_mcp_config()
        import config as cfg

        # Update state
        self._current_agent = target
        agent_state = get_agent_state(target)
        self._agent_muted = agent_state.get("muted", False)
        self._muted = self._global_muted or self._agent_muted

        # Update window
        self.setWindowTitle(cfg.AGENT_DISPLAY_NAME)

        # DO NOT clear transcript — conversation should feel continuous
        # Add a codec-style divider instead
        source_name = deferral.get("source_display_name", source_agent)
        self._transcript.add_divider(f"{source_name}  ›  {cfg.AGENT_DISPLAY_NAME}")

        # Swap video/avatar
        idle_loop = cfg.IDLE_LOOP
        if idle_loop.exists():
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(idle_loop))))
            self._player.play()
        else:
            self._player.stop()
            self._frame = QImage()

        # Check for a suspended session for the target agent
        suspended = resume_agent_session(target)
        if suspended:
            self._session = suspended["session"]
            self._cli_session_id = suspended["cli_session_id"]
            self._system = load_system_prompt()
        else:
            # New session for this agent
            memory.init_db()
            from core.session import Session
            self._session = Session()
            self._session.start()
            self._system = load_system_prompt()
            self._cli_session_id = self._session.cli_session_id

        # Update mute button
        self._mute_btn.set_active(self._global_muted)

        # Flash agent name — codec style
        self._flash_agent_name(cfg.AGENT_DISPLAY_NAME)

        # Iris open — fast reveal of new agent
        self._iris_phase = "opening"
        self._switch_anim = QPropertyAnimation(self, b"iris_progress", self)
        self._switch_anim.setStartValue(0.0)
        self._switch_anim.setEndValue(1.0)
        self._switch_anim.setDuration(300)
        self._switch_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._switch_anim.finished.connect(self._on_deferral_faded_in)
        self._switch_anim.start()

    def _on_deferral_faded_in(self):
        """Deferral fade-in complete — send the deferred question to the new agent."""
        self._switching = False
        self._switch_anim = None
        self._iris_progress = 0.0
        self._iris_phase = None

        deferral = self._deferral_data
        context = deferral.get("context", "")
        user_question = deferral.get("user_question", "")
        source = deferral.get("source_display_name", deferral.get("source_agent", "another agent"))

        # Build injected message with handoff context
        injected = (
            f"[{source} has deferred this conversation to you. "
            f"Context: {context}]\n\n{user_question}"
        )

        # Launch inference — the new agent responds to the deferred question
        self._bar.set_stop_mode(True)
        self._status_bar.start("thinking...")
        self._first_sentence_shown = False
        self._retry_text = user_question
        self._retried = False

        self._launch_worker(injected, self._cli_session_id)
        self._deferral_data = None

        # Resume wake listener after response completes (handled by _on_done)

    def _toggle_eye(self):
        self._eye_mode = not self._eye_mode
        self._eye_btn.set_active(self._eye_mode)
        if self._eye_mode:
            # Collapse to chat-bar-only mode
            self._player.pause()
            self._pre_eye_geometry = self.geometry()
            self._transcript.hide()
            self._mute_btn.hide()
            self._min_btn.hide()
            self._wake_btn.hide()
            self._settings_btn.hide()
            if self._settings_open:
                self._settings_panel.hide()
                self._settings_open = False
                self._settings_btn.set_active(False)
            self._eye_btn.hide()
            # Resize to just the input bar + eye button
            bar_w = min(self.width(), 500)
            collapsed_h = _BAR_H + 8  # bar + tiny margin
            # Keep centred horizontally at current position
            cx = self.x() + self.width() // 2
            self.setFixedSize(bar_w, collapsed_h)
            self.move(cx - bar_w // 2, self.y())
            # Reposition bar and eye button inside collapsed window
            self._bar.setFixedSize(bar_w - 42, _BAR_H)
            self._bar.move(4, 4)
            self._eye_btn.show()
            self._eye_btn.move(bar_w - 38, (collapsed_h - 34) // 2)
            self._eye_btn.raise_()
            self.update()
        else:
            # Restore full window
            self._transcript.show()
            self._mute_btn.show()
            self._min_btn.show()
            self._wake_btn.show()
            self._settings_btn.show()
            geo = getattr(self, '_pre_eye_geometry', None)
            self.setMinimumSize(360, 480)
            self.setMaximumSize(16777215, 16777215)  # reset fixed size
            if geo:
                self.setGeometry(geo)
            else:
                self.resize(_W, _H)
            self._player.play()
            self._reflow()
            self._position_mode_buttons()
            self.update()

    # ── Canvas overlay (PIP) ──

    def _build_canvas(self):
        """Create the PIP canvas overlay (hidden by default, child of this window)."""
        self._canvas = None
        if not HAS_CANVAS:
            return
        self._canvas = CanvasOverlay(self)
        # Position it over the video area
        self._reflow_canvas()
        # Cmd+K shortcut to toggle canvas
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        canvas_shortcut = QShortcut(QKeySequence("Meta+K"), self)
        canvas_shortcut.activated.connect(self._toggle_canvas)
        self._canvas_shortcut = canvas_shortcut  # prevent gc

    def _toggle_canvas(self):
        """Toggle the PIP canvas overlay."""
        if not self._canvas:
            return
        self._canvas.toggle()

    def _reflow_canvas(self):
        """Position canvas overlay to cover the video surface area."""
        if not self._canvas:
            return
        # Cover the full window (video is full-bleed)
        self._canvas.reposition(0, 0, self.width(), self.height())

    # ── Artefact system ──

    def _toggle_artefact_gallery(self):
        """Toggle the artefact gallery modal."""
        if self._artefact_gallery.isVisible():
            self._artefact_gallery.hide()
        else:
            self._artefact_gallery.setGeometry(0, 0, self.width(), self.height())
            self._artefact_gallery.show_gallery()
        self._artefact_btn.set_has_new(False)

    def _on_artefact_selected(self, artefact_dir, atype, file_path):
        """User clicked an artefact in the gallery — display it."""
        self._artefact_overlay.reposition(0, 0, self.width(), self.height())
        self._artefact_overlay.show_artefact(artefact_dir, atype, file_path)
        self._animate_to_pip()

    def _animate_to_pip(self):
        """Smoothly shrink the video to PIP in the bottom-right corner."""
        if self._pip_anim:
            self._pip_anim.stop()
        self._pip_anim = QPropertyAnimation(self, b"pip_progress", self)
        self._pip_anim.setStartValue(self._pip_progress)
        self._pip_anim.setEndValue(1.0)
        self._pip_anim.setDuration(500)
        self._pip_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._pip_anim.start()

    def _animate_from_pip(self):
        """Smoothly grow the video back from PIP to full-bleed."""
        if self._pip_anim:
            self._pip_anim.stop()
        self._pip_anim = QPropertyAnimation(self, b"pip_progress", self)
        self._pip_anim.setStartValue(self._pip_progress)
        self._pip_anim.setEndValue(0.0)
        self._pip_anim.setDuration(500)
        self._pip_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._pip_anim.start()

    def _check_artefact_requests(self):
        """Poll for artefact approval requests from MCP create_artefact tool."""
        if self._booting or self._switching:
            return
        import config as cfg
        req_file = cfg.ARTEFACT_REQUEST_FILE
        if not req_file.exists():
            return
        try:
            data = json.loads(req_file.read_text())
        except Exception:
            return

        # Only handle pending requests — approved/denied handled by MCP
        status = data.get("status", "")
        if status != "pending":
            return

        self._show_artefact_approval(data, req_file)

    def _show_artefact_approval(self, data, req_file):
        """Show an approval overlay for a paid artefact (image/video)."""
        atype = data.get("type", "unknown")
        name = data.get("name", "untitled")
        desc = data.get("description", "")
        cost_hint = "image generation" if atype == "image" else "video generation"

        # Build a simple approval overlay
        overlay = QWidget(self)
        overlay.setGeometry(0, 0, self.width(), self.height())
        overlay.setStyleSheet("background: rgba(0, 0, 0, 0.85);")

        layout = QVBoxLayout(overlay)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel(f"Artefact Request: {name}")
        title.setStyleSheet(
            "color: white; font-size: 18px; font-weight: bold;"
        )
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        type_lbl = QLabel(f"Type: {atype.upper()} ({cost_hint})")
        type_lbl.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 13px;")
        type_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(type_lbl)

        if desc:
            desc_lbl = QLabel(desc[:200])
            desc_lbl.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px;")
            desc_lbl.setAlignment(Qt.AlignCenter)
            desc_lbl.setWordWrap(True)
            desc_lbl.setMaximumWidth(400)
            layout.addWidget(desc_lbl)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)

        approve_btn = QPushButton("Approve")
        approve_btn.setStyleSheet(
            "QPushButton { background: rgba(80,180,100,0.8); color: white; "
            "border: none; border-radius: 8px; padding: 8px 24px; font-size: 14px; }"
            "QPushButton:hover { background: rgba(80,200,100,0.9); }"
        )
        approve_btn.setCursor(Qt.PointingHandCursor)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background: rgba(180,80,80,0.8); color: white; "
            "border: none; border-radius: 8px; padding: 8px 24px; font-size: 14px; }"
            "QPushButton:hover { background: rgba(200,80,80,0.9); }"
        )
        cancel_btn.setCursor(Qt.PointingHandCursor)

        def _approve():
            data["status"] = "approved"
            req_file.write_text(json.dumps(data))
            overlay.deleteLater()

        def _cancel():
            data["status"] = "denied"
            req_file.write_text(json.dumps(data))
            overlay.deleteLater()

        approve_btn.clicked.connect(_approve)
        cancel_btn.clicked.connect(_cancel)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(approve_btn)
        layout.addLayout(btn_row)

        overlay.show()
        overlay.raise_()

    def _check_artefact_display(self):
        """Poll for newly created artefacts that should be displayed."""
        import config as cfg
        display_file = cfg.ARTEFACT_DISPLAY_FILE
        if not display_file.exists():
            return
        try:
            data = json.loads(display_file.read_text())
            display_file.unlink()
        except Exception:
            return

        artefact_dir = data.get("path", "")
        atype = data.get("type", "html")
        file_path = data.get("file", "")

        if artefact_dir or file_path:
            self._artefact_overlay.reposition(0, 0, self.width(), self.height())
            self._artefact_overlay.show_artefact(artefact_dir, atype, file_path)
            self._artefact_btn.set_has_new(True)
            self._animate_to_pip()

    def _reflow_artefacts(self):
        """Reposition artefact overlays on resize."""
        if self._artefact_overlay.is_active():
            self._artefact_overlay.reposition(0, 0, self.width(), self.height())
        if self._artefact_gallery.isVisible():
            self._artefact_gallery.setGeometry(0, 0, self.width(), self.height())

    # ── Streaming interaction flow ──

    def _on_idle_timeout(self):
        from core.status import set_away
        set_away("idle")

    def _reset_idle_timer(self):
        from core.status import IDLE_TIMEOUT_SECS, set_active
        set_active()
        self._idle_timer.start(IDLE_TIMEOUT_SECS * 1000)

    def _on_user_input(self, text):
        self._reset_idle_timer()
        self._start_turn(text)

    def _start_turn(self, text):
        # Pause wake listener during active conversation
        if self._wake_listener:
            self._wake_listener.pause()

        # Detect away intent — set status before processing
        from core.status import detect_away_intent, set_away
        away_reason = detect_away_intent(text)
        if away_reason:
            set_away(away_reason)

        # Cancel opening if still loading — user went first
        if getattr(self, '_opening_worker', None):
            self._opening_worker = None
            self._status_bar.stop()

        # Cut off any active response — kill worker + audio
        if self._worker:
            self._worker.terminate()
            self._worker.wait(2000)
            self._worker = None
        self._kill_audio()

        # Add user message to transcript
        self._transcript.add_message("user", text)

        # Record user turn — companion text filled in when done
        self._history.append({"user": text, "companion": ""})

        if self._session:
            self._session.add_turn("will", text)

        # Start streaming pipeline
        self._bar.set_stop_mode(True)
        self._status_bar.start("thinking...")
        self._first_sentence_shown = False
        self._retry_text = text  # stash for auto-retry
        self._retried = False

        self._launch_worker(text, self._cli_session_id)

    def _launch_worker(self, text, session_id):
        """Launch the streaming pipeline worker."""
        import time as _time
        self._response_start_time = _time.time()
        self._worker = StreamingPipelineWorker(
            user_text=text,
            system=self._system,
            cli_session_id=session_id,
            synth_fn=self._on_synth,
            muted=self._muted,
        )
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.sentence_ready.connect(self._on_sentence_ready)
        self._worker.tool_use.connect(self._on_tool_use)
        self._worker.compacting.connect(self._on_compacting)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _auto_retry(self):
        """Reset session and retry the last message once."""
        if self._retried:
            self._present("[couldn't connect — try again]")
            self._bar.set_stop_mode(False)
            return
        self._retried = True
        print("  [Session reset — retrying...]")
        self._cli_session_id = None
        if self._session:
            self._session.set_cli_session_id(None)
        self._first_sentence_shown = False
        self._launch_worker(self._retry_text, None)

    def _on_text_ready(self, sentence, index):
        """Text available immediately — show in transcript before TTS finishes."""
        if not self._first_sentence_shown:
            self._first_sentence_shown = True
            self._status_bar.stop()
            self._transcript.add_message("companion", _strip_tags(sentence))
        else:
            self._transcript.append_to_last(_strip_tags(sentence))

    def _on_sentence_ready(self, sentence, audio_path, index):
        """TTS done — queue audio only (text already shown by _on_text_ready)."""
        if audio_path and not self._muted:
            self._audio_player.enqueue(audio_path, index)

    def _on_tool_use(self, name, tool_id):
        """Claude invoked a tool — show in UI."""
        if name == "mcp__memory__defer_to_agent":
            self._status_bar.start("handing off...")

    def _on_compacting(self):
        """Context window is being compacted — set flush flag and show status."""
        self._needs_memory_flush = True
        self._compaction_warned = False
        # After compaction, context is roughly halved
        self._approx_tokens = self._approx_tokens // 3
        self._status_bar.start("compacting memory...")

    def _on_done(self, full_text, session_id):
        """Stream complete."""
        self._worker = None

        if session_id:
            self._cli_session_id = session_id

        # Empty response — auto-retry with fresh session
        if not full_text and not self._first_sentence_shown:
            self._auto_retry()
            return

        self._status_bar.stop()
        self._bar.set_stop_mode(False)

        # Update session
        if self._session:
            if session_id:
                self._session.set_cli_session_id(session_id)
            self._session.add_turn("agent", full_text)

        # Update history with full companion text
        if self._history:
            self._history[-1]["companion"] = full_text

        # Track approximate context usage (~4 chars per token)
        user_text = self._history[-1]["user"] if self._history else ""
        response_tokens = len(full_text) // 4
        self._approx_tokens += (len(user_text) // 4) + response_tokens
        if self._approx_tokens > 150000 and not self._compaction_warned:
            self._compaction_warned = True
            self._status_bar.start("context getting full — compaction soon")
            QTimer.singleShot(5000, self._status_bar.stop)

        # Update metrics label
        self._update_metrics_label(response_tokens)

        # If no sentences came through streaming, synthesise then show text + audio together
        if not self._first_sentence_shown and full_text:
            if self._on_synth and not self._muted:
                import threading
                def _synth_then_present():
                    try:
                        path = self._on_synth(_strip_tags(full_text))
                        # Use QTimer to update UI from the main thread
                        from PyQt5.QtCore import QMetaObject, Q_ARG
                        QTimer.singleShot(0, lambda: self._present_with_audio(full_text, str(path) if path else ""))
                    except Exception:
                        QTimer.singleShot(0, lambda: self._present(full_text))
                threading.Thread(target=_synth_then_present, daemon=True).start()
            else:
                self._present(full_text)

        # Pre-compaction memory flush — fire in background, invisible to user
        if self._needs_memory_flush:
            self._needs_memory_flush = False
            self._flush_worker = MemoryFlushWorker(self._cli_session_id, self._system)
            self._flush_worker.finished_flush.connect(self._on_flush_done)
            self._flush_worker.start()

        # Follow-up agency
        from core.agency import should_follow_up
        if full_text and should_follow_up():
            QTimer.singleShot(random.randint(3000, 8000), self._do_follow_up)
        else:
            # No follow-up — safe to resume wake listener
            self._resume_wake_after_turn()

    def _resume_wake_after_turn(self):
        """Resume wake word listener after a conversation turn completes."""
        if self._wake_enabled and self._wake_listener:
            # Delay slightly so any final TTS audio finishes
            QTimer.singleShot(500, self._wake_listener.resume)

    def _do_follow_up(self):
        """Unprompted follow-up — a second thought that arrived late."""
        if self._worker is not None:
            return  # already streaming something new
        from core.agency import followup_prompt
        from core.inference import stream_inference, SentenceReady, StreamDone, StreamError

        # Run a quick one-shot follow-up
        followup_system = self._system + "\n\n" + followup_prompt()

        self._first_sentence_shown = False
        self._worker = StreamingPipelineWorker(
            user_text="(continue — your second thought)",
            system=followup_system,
            cli_session_id=self._cli_session_id,
            synth_fn=self._on_synth,
            muted=self._muted,
        )
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.sentence_ready.connect(self._on_sentence_ready)
        self._worker.tool_use.connect(self._on_tool_use)
        self._worker.compacting.connect(self._on_compacting)
        self._worker.done.connect(self._on_followup_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _check_timer_requests(self):
        """Poll for timer requests written by the MCP set_timer tool."""
        import config as cfg
        timer_file = cfg.DATA_DIR / ".timer_request.json"
        if not timer_file.exists():
            return
        try:
            data = json.loads(timer_file.read_text())
            timer_file.unlink()
        except Exception:
            return

        seconds = data.get("seconds", 0)
        label = data.get("label", "Timer")
        if seconds <= 0:
            return

        from display.timer import TimerOverlay
        timer = TimerOverlay(seconds=seconds, label=label)
        timer.finished.connect(lambda lbl: self._on_timer_finished(lbl))
        timer.show()
        self._active_timers.append(timer)

    def _check_inbox(self):
        """Periodic check for new messages across all agents."""
        # Don't check during boot, switch, or if worker is active
        if self._booting or self._switching:
            return
        self._drain_message_queue()

    def _on_timer_finished(self, label: str):
        """Timer completed — clean up reference."""
        self._active_timers = [t for t in self._active_timers if t.isVisible()]

    def _do_journal_nudge(self):
        """Unprompted journal nudge — once per session, timed randomly."""
        if self._worker is not None:
            # Busy — try again in 5 minutes
            QTimer.singleShot(5 * 60_000, self._do_journal_nudge)
            return

        nudge_system = (
            self._system + "\n\n"
            "RIGHT NOW: Gently but directly suggest Will take some time to journal. "
            "This is not a subtle weave — tell him openly. Reference what you've "
            "been talking about if there's something worth sitting with, or just "
            "invite him to write about whatever's on his mind. Keep it to 2-3 "
            "sentences. Use prompt_journal to leave him a specific question in "
            "Obsidian. Be warm but don't overthink it — just ask him to write."
        )

        self._first_sentence_shown = False
        self._bar.set_stop_mode(True)
        self._worker = StreamingPipelineWorker(
            user_text="(journal nudge — speak unprompted)",
            system=nudge_system,
            cli_session_id=self._cli_session_id,
            synth_fn=self._on_synth,
            muted=self._muted,
        )
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.sentence_ready.connect(self._on_sentence_ready)
        self._worker.tool_use.connect(self._on_tool_use)
        self._worker.compacting.connect(self._on_compacting)
        self._worker.done.connect(self._on_followup_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_followup_done(self, full_text, session_id):
        """Follow-up complete."""
        self._worker = None
        self._bar.set_stop_mode(False)
        self._cli_session_id = session_id
        if self._session:
            self._session.set_cli_session_id(session_id)
            if full_text:
                self._session.add_turn("agent", full_text)
        # Append to current history entry
        if self._history and full_text:
            self._history[-1]["companion"] += "\n\n" + full_text
        if not self._first_sentence_shown and full_text:
            if self._on_synth and not self._muted:
                import threading
                def _synth_then_present():
                    try:
                        path = self._on_synth(_strip_tags(full_text))
                        QTimer.singleShot(0, lambda: self._present_with_audio(full_text, str(path) if path else ""))
                    except Exception:
                        QTimer.singleShot(0, lambda: self._present(full_text))
                threading.Thread(target=_synth_then_present, daemon=True).start()
            else:
                self._present(full_text)

    def _on_flush_done(self, new_session_id):
        """Memory flush complete — update session ID if changed."""
        self._flush_worker = None
        if new_session_id:
            self._cli_session_id = new_session_id
            if self._session:
                self._session.set_cli_session_id(new_session_id)

    def _do_coherence_check(self):
        """SENTINEL — periodic coherence check. Skipped if streaming or no session."""
        if self._worker is not None:
            return  # mid-stream — skip this cycle
        if not self._cli_session_id:
            return  # no active CLI session
        if self._coherence_worker is not None:
            return  # previous check still running
        self._coherence_worker = CoherenceWorker(self._cli_session_id, self._system)
        self._coherence_worker.finished_check.connect(self._on_coherence_done)
        self._coherence_worker.start()

    def _on_coherence_done(self, new_session_id):
        """SENTINEL check complete — update session ID if re-anchoring changed it."""
        self._coherence_worker = None
        if new_session_id:
            self._cli_session_id = new_session_id
            if self._session:
                self._session.set_cli_session_id(new_session_id)

    def _kill_audio(self):
        """Kill playing audio and clear the queue."""
        try:
            subprocess.run(["pkill", "-f", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        while not self._audio_player._queue.empty():
            try:
                self._audio_player._queue.get_nowait()
            except Exception:
                break

    def _on_stop(self):
        """User pressed stop — kill inference and audio."""
        if self._worker:
            self._worker.terminate()
            self._worker.wait(2000)
            self._worker = None
        self._status_bar.stop()
        self._bar.set_stop_mode(False)
        self._kill_audio()

    def _on_error(self, msg):
        self._worker = None
        print(f"  [Inference error: {msg}]")
        # Auto-retry with fresh session
        self._auto_retry()

    def _on_audio_started(self, index):
        """Audio playback began for a sentence."""
        self._vignette_target = 1.0
        # Pause wake listener during TTS to avoid self-triggering
        if self._wake_listener:
            self._wake_listener.pause()

    def _on_audio_done(self, index):
        """Audio playback finished for a sentence."""
        # Fade out vignette if nothing else queued
        if self._audio_player._queue.empty():
            self._vignette_target = 0.0
            # Resume wake listener when all audio is done
            if self._wake_enabled and self._wake_listener and self._worker is None:
                self._wake_listener.resume()

    def _present(self, text):
        self._transcript.add_message("companion", _strip_tags(text))

    def _present_with_audio(self, text, audio_path):
        """Show text and play audio simultaneously."""
        self._transcript.add_message("companion", _strip_tags(text))
        if audio_path and not self._muted:
            self._audio_player.enqueue(audio_path, 0)

    # ── Public API ──

    def set_video(self, path):
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(path))))
        self._player.play()

    # ── Layout ──

    def _content_rect(self):
        """Return the content area clamped to the video's visible bounds."""
        win_w, win_h = self.width(), self.height()
        if self._frame.isNull():
            return _PAD, win_w - _PAD, 0, win_h
        img_w, img_h = self._frame.width(), self._frame.height()
        scale = max(win_w / img_w, win_h / img_h) * 1.01
        sw = int(img_w * scale)
        sh = int(img_h * scale)
        # Clamp to whichever is smaller: video extent or window
        vid_left = max(0, (win_w - sw) // 2)
        vid_right = min(win_w, vid_left + sw)
        vid_top = max(0, (win_h - sh) // 2)
        vid_bottom = min(win_h, vid_top + sh)
        left = vid_left + _PAD
        right = vid_right - _PAD
        # Cap width to a readable maximum (avoids ultra-wide text lines)
        max_content = 700
        content_w = right - left
        if content_w > max_content:
            cx = (left + right) // 2
            left = cx - max_content // 2
            right = cx + max_content // 2
        return left, right, vid_top, vid_bottom

    def resizeEvent(self, event):
        self._scaled_frame = None  # invalidate cache
        self._vignette_img = None  # invalidate vignette cache
        self._transcript._invalidate_layout()
        self._reflow()
        if self._settings_open:
            self._settings_panel.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)

    def _reflow(self):
        left, right, _, h = self._content_rect()
        content_w = right - left
        # Input bar
        self._bar.setFixedSize(content_w, _BAR_H)
        self._bar.move(left, h - _PAD - _BAR_H)
        # Transcript — bottom half, above input bar
        bar_y = h - _PAD - _BAR_H
        gap = 10
        transcript_h = h // 2
        transcript_y = bar_y - gap - transcript_h
        self._transcript.setGeometry(left, transcript_y, content_w, transcript_h)
        # Buttons and status bar
        self._position_mode_buttons()
        self._position_status_bar()
        # Metrics label
        if self._metrics_label.isVisible():
            self._position_metrics_label()
        # Canvas overlay
        self._reflow_canvas()
        # Artefact overlays
        self._reflow_artefacts()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._audio_player.stop()
            self.close()
        elif event.key() == Qt.Key_Up and (event.modifiers() & Qt.MetaModifier):
            from core.agent_manager import cycle_agent
            next_agent = cycle_agent(-1, self._current_agent)
            if next_agent:
                self.switch_agent(next_agent)
        elif event.key() == Qt.Key_Down and (event.modifiers() & Qt.MetaModifier):
            from core.agent_manager import cycle_agent
            next_agent = cycle_agent(+1, self._current_agent)
            if next_agent:
                self.switch_agent(next_agent)
        elif event.key() == Qt.Key_Up:
            self._transcript.scroll_up()
        elif event.key() == Qt.Key_Down:
            self._transcript.scroll_down()
        elif event.key() == Qt.Key_C and (event.modifiers() & Qt.ControlModifier or event.modifiers() & Qt.MetaModifier):
            # If input bar has selected text, let it handle copy
            if self._bar._input.hasSelectedText():
                super().keyPressEvent(event)
                return
            self._transcript.copy_last_companion()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)

    _shutting_down = pyqtSignal()
    _shutdown_status = pyqtSignal(str, float)  # (label, progress 0..1)

    def closeEvent(self, event):
        if getattr(self, '_shutdown_done', False):
            super().closeEvent(event)
            app = QApplication.instance()
            if app:
                app.quit()
            return

        if getattr(self, '_shutdown_started', False):
            event.ignore()
            return

        event.ignore()
        self._begin_shutdown()

    def _begin_shutdown(self):
        """Run cleanup with visible progress, then close."""
        self._shutdown_started = True
        self._shutdown_mode = True
        self._drift_timer.stop()
        self._player.stop()
        self._audio_player.stop()
        self._stop_wake_listener()
        # Hide chat panel and tray icon
        if _chat_panel:
            _chat_panel.hide()
        if _global_hotkey:
            _global_hotkey.stop()
        if _menu_bar_icon:
            _menu_bar_icon.hide()
        # Kill any orphaned afplay processes
        import os, signal
        try:
            subprocess.run(["pkill", "-f", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        if self._worker:
            self._worker.terminate()
            self._worker.wait(2000)

        # Cut to black — hide everything
        self._bar.hide()
        self._transcript.hide()
        self._mute_btn.hide()
        self._eye_btn.hide()
        self._min_btn.hide()
        self._wake_btn.hide()
        self._settings_btn.hide()
        if self._settings_open:
            self._settings_panel.hide()
        self._frame = QImage()  # clear video frame
        self._scaled_frame = None
        self.update()  # repaint black

        # Centre the status bar
        self._status_bar.setFixedWidth(self.width() - _PAD * 4)
        cx = (self.width() - self._status_bar.width()) // 2
        cy = self.height() // 2
        self._status_bar.move(cx, cy)
        self._status_bar.start("stopping audio...")

        # Connect signals for thread-safe updates
        self._shutting_down.connect(self._finish_shutdown)
        self._shutdown_status.connect(
            lambda label, prog: self._status_bar.set_progress(prog, label)
        )

        import threading

        def _cleanup():
            self._shutdown_status.emit("ending session...", 0.3)
            if self._session:
                try:
                    self._session.end(self._system)
                except Exception:
                    pass

            self._shutdown_status.emit("done", 1.0)
            self._shutting_down.emit()

        threading.Thread(target=_cleanup, daemon=True).start()

    def _finish_shutdown(self):
        self._status_bar.stop()
        self._shutdown_done = True
        self.close()


# ── Chat panel (lightweight floating overlay) ──

class ChatPanel(QWidget):
    """Cmd+Shift+Space chat overlay — text-only, no video."""

    def __init__(self, companion):
        super().__init__()
        self._companion = companion
        self._worker = None
        self._first_sentence_shown = False

        self.setWindowTitle("Chat")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(520, 380)

        self._transcript = TranscriptOverlay(self)
        self._bar = InputBar(self)
        self._bar.submitted.connect(self._on_input)
        self._bar.stop_requested.connect(self._on_stop)
        self._bar.copy_requested.connect(self._transcript.copy_last_companion)

        self._drag_pos = None
        self._reflow()

    def _reflow(self):
        w, h = self.width(), self.height()
        pad = 16
        bar_y = h - pad - _BAR_H
        self._bar.setFixedSize(w - pad * 2, _BAR_H)
        self._bar.move(pad, bar_y)
        transcript_h = h - pad * 2 - _BAR_H - 10
        self._transcript.setGeometry(pad, pad, w - pad * 2, transcript_h)

    def resizeEvent(self, event):
        self._reflow()
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 16, 16)
        p.fillPath(path, QColor(18, 18, 20, 240))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(path)
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self._companion.wake_up()  # no-op if already awake
            # Centre on screen
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - self.width()) // 2
            y = int(screen.height() * 0.25)
            self.move(x, y)
            self.show()
            self.raise_()
            self.activateWindow()
            self._bar.focus_input()

    def _on_input(self, text):
        # Don't send if companion is already streaming
        c = self._companion
        if c._worker is not None:
            return

        self._transcript.add_message("user", text)

        # Share session state
        if c._session:
            c._session.add_turn("will", text)
        c._history.append({"user": text, "companion": ""})

        self._first_sentence_shown = False
        self._bar.set_stop_mode(True)
        self._worker = StreamingPipelineWorker(
            user_text=text,
            system=c._system,
            cli_session_id=c._cli_session_id,
            synth_fn=None,  # text-only — no TTS
            muted=True,
        )
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.sentence_ready.connect(self._on_sentence_ready)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_text_ready(self, sentence, index):
        if not self._first_sentence_shown:
            self._first_sentence_shown = True
            self._transcript.add_message("companion", _strip_tags(sentence))
        else:
            self._transcript.append_to_last(_strip_tags(sentence))

    def _on_sentence_ready(self, sentence, audio_path, index):
        pass  # text-only — audio ignored

    def _on_done(self, full_text, session_id):
        self._worker = None
        self._bar.set_stop_mode(False)
        c = self._companion
        if session_id:
            c._cli_session_id = session_id
        if c._session:
            if session_id:
                c._session.set_cli_session_id(session_id)
            if full_text:
                c._session.add_turn("agent", full_text)
        if c._history:
            c._history[-1]["companion"] = full_text
        if not self._first_sentence_shown and full_text:
            self._transcript.add_message("companion", _strip_tags(full_text))

    def _on_error(self, msg):
        self._worker = None
        self._bar.set_stop_mode(False)
        print(f"  [ChatPanel error: {msg}]")

    def _on_stop(self):
        if self._worker:
            self._worker.terminate()
            self._worker.wait(2000)
            self._worker = None
        self._bar.set_stop_mode(False)


# ── Menu bar icon ──

class MenuBarIcon:
    """Native macOS status bar icon using NSStatusBar.

    QSystemTrayIcon doesn't work on modern macOS (zero-height geometry),
    so we use pyobjc to create a native NSStatusItem instead.
    """
    def __init__(self, companion_window, chat_panel):
        self._window = companion_window
        self._chat = chat_panel
        self._status_item = None
        self._away = False

        try:
            from AppKit import (
                NSStatusBar, NSImage, NSMenu, NSMenuItem,
                NSVariableStatusItemLength,
            )
            from objc import selector

            # Create status bar item
            bar = NSStatusBar.systemStatusBar()
            self._status_item = bar.statusItemWithLength_(
                NSVariableStatusItemLength
            )

            # Create a small circle icon as NSImage
            self._status_item.button().setTitle_("●")

            # Build native menu
            menu = NSMenu.alloc().init()

            show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Show/Hide", "toggleWindow:", "")
            show_item.setTarget_(self)
            menu.addItem_(show_item)

            chat_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Chat Panel", "toggleChat:", "")
            chat_item.setTarget_(self)
            menu.addItem_(chat_item)

            menu.addItem_(NSMenuItem.separatorItem())

            # Agent submenu
            from core.agent_manager import discover_agents
            agents = discover_agents()
            if len(agents) > 1:
                agents_submenu = NSMenu.alloc().init()
                for agent in agents:
                    a_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        agent["display_name"], "switchAgent:", "")
                    a_item.setTarget_(self)
                    a_item.setRepresentedObject_(agent["name"])
                    agents_submenu.addItem_(a_item)
                agents_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Agents", "", "")
                agents_parent.setSubmenu_(agents_submenu)
                menu.addItem_(agents_parent)
                menu.addItem_(NSMenuItem.separatorItem())

            self._status_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Set Away", "toggleStatus:", "")
            self._status_menu_item.setTarget_(self)
            menu.addItem_(self._status_menu_item)

            menu.addItem_(NSMenuItem.separatorItem())

            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit", "quitApp:", "")
            quit_item.setTarget_(self)
            menu.addItem_(quit_item)

            self._status_item.setMenu_(menu)
            self._menu = menu  # prevent gc

        except ImportError:
            print("  [AppKit unavailable — no menu bar icon]")
            # Fallback to QSystemTrayIcon
            self._setup_qt_fallback()

    def _setup_qt_fallback(self):
        """Fallback for non-macOS or missing pyobjc."""
        self._tray = QSystemTrayIcon()
        from PyQt5.QtGui import QPixmap, QIcon
        pix = QPixmap(22, 22)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawEllipse(5, 5, 12, 12)
        p.end()
        self._tray.setIcon(QIcon(pix))
        self._tray.setToolTip(AGENT_DISPLAY_NAME)
        menu = QMenu()
        menu.addAction("Show/Hide", self._toggle_window)
        menu.addAction("Quit", self._quit)
        self._tray.setContextMenu(menu)
        self._tray.show()

    # ── NSMenu action selectors ──

    def toggleWindow_(self, sender):
        self._toggle_window()

    def toggleChat_(self, sender):
        self._toggle_chat()

    def switchAgent_(self, sender):
        name = sender.representedObject()
        self._switch_to(name)

    def toggleStatus_(self, sender):
        self._toggle_status()

    def quitApp_(self, sender):
        self._quit()

    # ── Shared logic ──

    def _toggle_window(self):
        w = self._window
        if w.isVisible():
            w.hide()
        else:
            w.wake_up()
            w.show()
            w.raise_()
            w.activateWindow()
            w._bar.focus_input()

    def _toggle_chat(self):
        self._chat.toggle()

    def _switch_to(self, agent_name):
        self._window.wake_up()
        self._window.switch_agent(agent_name)

    def _toggle_status(self):
        from core.status import is_away, set_active, set_away
        if is_away():
            set_active()
            self._away = False
            if self._status_item:
                self._status_menu_item.setTitle_("Set Away")
            self._window._reset_idle_timer()
        else:
            set_away("manual")
            self._away = True
            if self._status_item:
                self._status_menu_item.setTitle_("Set Active")

    def _quit(self):
        self._window.close()

    def hide(self):
        if self._status_item:
            from AppKit import NSStatusBar
            NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
            self._status_item = None
        elif hasattr(self, '_tray'):
            self._tray.hide()


# ── Global hotkey ──

class GlobalHotkey:
    """Cmd+Shift+Space global hotkey via NSEvent monitor."""
    def __init__(self, callback):
        self._monitors = []
        self._callback = callback
        try:
            from AppKit import NSEvent
            from Cocoa import (
                NSEventMaskKeyDown,
                NSEventModifierFlagCommand,
                NSEventModifierFlagShift,
            )

            def handler(event):
                if (event.keyCode() == 49  # Space
                    and event.modifierFlags() & NSEventModifierFlagCommand
                    and event.modifierFlags() & NSEventModifierFlagShift):
                    QTimer.singleShot(0, self._callback)

            # Global monitor — fires when app is NOT focused
            m1 = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, handler
            )
            if m1:
                self._monitors.append(m1)

            # Local monitor — fires when app IS focused
            def local_handler(event):
                if (event.keyCode() == 49
                    and event.modifierFlags() & NSEventModifierFlagCommand
                    and event.modifierFlags() & NSEventModifierFlagShift):
                    QTimer.singleShot(0, self._callback)
                    return None  # consume event
                return event

            m2 = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown, local_handler
            )
            if m2:
                self._monitors.append(m2)

            print("  [Global hotkey: Cmd+Shift+Space registered]")
        except Exception as e:
            print(f"  [Global hotkey failed: {e} — use tray icon instead]")

    def stop(self):
        try:
            from AppKit import NSEvent
            for m in self._monitors:
                NSEvent.removeMonitor_(m)
        except Exception:
            pass
        self._monitors.clear()


# ── Entry point ──

def run_app(on_synth_callback=None, on_opening_callback=None,
            system_prompt="", cli_session_id=None, session=None,
            cached_opening_audio="", menu_bar_mode=False):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Menu-bar-only mode — hide from Dock (like Amphetamine)
    if menu_bar_mode:
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        except ImportError:
            print("  [AppKit unavailable — app will still appear in Dock]")

    # App icon — orb
    from display.icon import get_app_icon
    app_icon = get_app_icon()
    app.setWindowIcon(app_icon)

    # Handle Ctrl+C gracefully
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    global _companion_window, _chat_panel, _menu_bar_icon, _global_hotkey

    _companion_window = CompanionWindow(
        on_synth=on_synth_callback,
        on_opening=on_opening_callback,
        system_prompt=system_prompt,
        cli_session_id=cli_session_id,
        session=session,
        cached_opening_audio=cached_opening_audio,
        dormant=False,
    )

    _chat_panel = ChatPanel(_companion_window)
    _menu_bar_icon = MenuBarIcon(_companion_window, _chat_panel)
    _global_hotkey = GlobalHotkey(_chat_panel.toggle)

    _companion_window.show()
    _companion_window._bar.focus_input()

    app.exec_()

    # Cleanup
    if _global_hotkey:
        _global_hotkey.stop()
    if _menu_bar_icon:
        _menu_bar_icon.hide()

_companion_window = None
_chat_panel = None
_menu_bar_icon = None
_global_hotkey = None

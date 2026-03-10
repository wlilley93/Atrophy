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
    """Scrolling chat transcript — messages accumulate bottom-aligned."""
    _MSG_GAP = 6       # gap within a pair (user → companion)
    _PAIR_GAP = 20     # gap between pairs
    _SCROLL_STEP = 40

    def __init__(self, parent=None, font_family="Bricolage Grotesque"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self._font = QFont(font_family, 14)
        self._fm = QFontMetrics(self._font)
        # Each entry: {"role": "user"|"companion", "text": str, "revealed": int}
        self._messages = []
        self._opacity = 1.0
        self._scroll_offset = 0.0  # 0 = pinned to bottom, positive = scrolled up
        self._auto_scroll = True   # snap to bottom on new messages
        self._layout_dirty = True  # recalc layout only when messages change
        self._cached_blocks = []   # cached layout measurements
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(18)
        self._reveal_timer.timeout.connect(self._tick_reveal)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.update()

    opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def _invalidate_layout(self):
        self._layout_dirty = True

    def add_message(self, role: str, text: str, instant: bool = False):
        """Add a message. User messages reveal instantly, companion gradually."""
        revealed = len(text) if (instant or role == "user") else 0
        self._messages.append({
            "role": role, "text": text, "revealed": revealed,
        })
        if revealed < len(text) and not self._reveal_timer.isActive():
            self._reveal_timer.start()
        if self._auto_scroll:
            self._scroll_offset = 0.0
        self._invalidate_layout()
        self.update()

    def append_to_last(self, text: str):
        """Append text to the last companion message (streaming)."""
        if not self._messages:
            return
        msg = self._messages[-1]
        msg["text"] = (msg["text"] + " " + text).strip() if msg["text"] else text
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()
        if self._auto_scroll:
            self._scroll_offset = 0.0
        self._invalidate_layout()
        self.update()

    def set_last_text(self, text: str):
        """Set the text of the last message (first sentence)."""
        if not self._messages:
            return
        msg = self._messages[-1]
        msg["text"] = text
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()
        self._invalidate_layout()
        self.update()

    def clear_messages(self):
        self._messages.clear()
        self._scroll_offset = 0.0
        self._invalidate_layout()
        self.update()

    def scroll_up(self):
        max_s = self._max_scroll()
        if max_s > 0:
            self._scroll_offset = min(self._scroll_offset + self._SCROLL_STEP, max_s)
            self._auto_scroll = False
            self.update()

    def scroll_down(self):
        self._scroll_offset = max(0.0, self._scroll_offset - self._SCROLL_STEP)
        if self._scroll_offset <= 0:
            self._auto_scroll = True
        self.update()

    def copy_last_companion(self):
        """Copy the last companion message to clipboard."""
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
        self._invalidate_layout()
        self.update()

    def _gap_before(self, index):
        """Gap before message at index — bigger between pairs."""
        if index == 0:
            return 0
        prev_role = self._messages[index - 1]["role"]
        curr_role = self._messages[index]["role"]
        # New pair starts at each user message (unless first)
        if curr_role == "user" and prev_role == "companion":
            return self._PAIR_GAP
        return self._MSG_GAP

    def _rebuild_layout(self):
        """Rebuild cached block measurements."""
        w = self.width()
        blocks = []
        if w <= 0:
            self._cached_blocks = blocks
            self._layout_dirty = False
            return
        fm = self._fm
        for i, msg in enumerate(self._messages):
            text = msg["text"][:msg["revealed"]]
            if not text:
                continue
            br = fm.boundingRect(QRect(0, 0, w, 99999), Qt.TextWordWrap, text)
            blocks.append({
                "text": text,
                "role": msg["role"],
                "height": br.height(),
                "gap": self._gap_before(i),
            })
        self._cached_blocks = blocks
        self._layout_dirty = False

    def _total_content_height(self):
        """Total height of all messages."""
        if self._layout_dirty:
            self._rebuild_layout()
        return sum(b["height"] + b["gap"] for b in self._cached_blocks)

    def _max_scroll(self):
        return max(0.0, self._total_content_height() - self.height())

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.scroll_up()
        elif delta < 0:
            self.scroll_down()

    def paintEvent(self, event):
        if not self._messages or self._opacity <= 0.001:
            return

        if self._layout_dirty:
            self._rebuild_layout()

        blocks = self._cached_blocks
        if not blocks:
            return

        w = self.width()
        vis_h = self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setClipRect(0, 0, w, vis_h)
        p.setFont(self._font)

        # Layout bottom-up, offset by scroll
        y = vis_h + self._scroll_offset
        layout = []
        for block in reversed(blocks):
            y -= block["height"]
            layout.insert(0, (block, y))
            y -= block["gap"]

        # Fade zone — top 1/3 of the widget
        fade_h = vis_h / 3.0
        opacity = self._opacity

        # Draw each message
        for block, y_pos in layout:
            bottom = y_pos + block["height"]
            if bottom < 0 or y_pos > vis_h:
                continue

            # Fade based on vertical position — full at bottom, fading in top 1/3
            msg_center = y_pos + block["height"] / 2
            fade_alpha = min(1.0, max(0.0, msg_center / fade_h)) if msg_center < fade_h else 1.0
            combined = opacity * fade_alpha

            alpha = int(220 * combined)
            y_int = int(y_pos)

            # Shadow
            p.setPen(QColor(0, 0, 0, int(120 * combined)))
            p.drawText(QRect(1, y_int + 1, w, block["height"] + 4),
                       Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, block["text"])
            # Text — companion white, user greyed
            if block["role"] == "user":
                p.setPen(QColor(180, 180, 180, alpha))
            else:
                p.setPen(QColor(255, 255, 255, alpha))
            p.drawText(QRect(0, y_int, w, block["height"] + 4),
                       Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, block["text"])

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


# ── Settings panel ──

_SETTINGS_STYLE = """
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


class SettingsPanel(QWidget):
    """Full-screen settings overlay — dark, scrollable, grouped by category."""
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.setStyleSheet(_SETTINGS_STYLE)
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

        # Save to .env button
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("Save to .env")
        save_btn.setObjectName("saveButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_to_env)
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

        # ── Agent Identity ──
        self._add_section("AGENT IDENTITY")
        self._add_info("agent_name", "Agent Slug", cfg.AGENT_NAME)
        self._add_text("agent_display_name", "Display Name", cfg.AGENT_DISPLAY_NAME)
        self._add_text("user_name", "User Name", cfg.USER_NAME)
        self._add_text("opening_line", "Opening Line", cfg.OPENING_LINE)
        self._add_text("wake_words", "Wake Words",
                       ", ".join(cfg.WAKE_WORDS))

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

    def _save_to_env(self):
        """Write current settings to .env and agent.json."""
        self._apply_settings()
        import config as cfg

        # ── Save agent.json ──
        manifest_path = cfg.AGENT_DIR / "agent.json"
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

        manifest.setdefault("telegram", {})
        tg = manifest["telegram"]
        token_env = tg.get("bot_token_env", f"TELEGRAM_BOT_TOKEN_{cfg.AGENT_NAME.upper()}")
        chat_env = tg.get("chat_id_env", f"TELEGRAM_CHAT_ID_{cfg.AGENT_NAME.upper()}")
        manifest["telegram"]["bot_token_env"] = token_env
        manifest["telegram"]["chat_id_env"] = chat_env

        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  [Saved agent.json: {manifest_path}]")

        # ── Save .env ──
        env_path = cfg.PROJECT_ROOT / ".env"
        existing = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()

        env_map = {
            "AGENT": cfg.AGENT_NAME,
            "TTS_BACKEND": cfg.TTS_BACKEND,
            "ELEVENLABS_API_KEY": cfg.ELEVENLABS_API_KEY,
            "INPUT_MODE": cfg.INPUT_MODE,
            "WAKE_WORD_ENABLED": str(cfg.WAKE_WORD_ENABLED).lower(),
            "CLAUDE_BIN": cfg.CLAUDE_BIN,
            "CLAUDE_EFFORT": cfg.CLAUDE_EFFORT,
            "ADAPTIVE_EFFORT": str(cfg.ADAPTIVE_EFFORT).lower(),
            "AVATAR_ENABLED": str(cfg.AVATAR_ENABLED).lower(),
            "OBSIDIAN_VAULT": str(cfg.OBSIDIAN_VAULT),
        }
        # Telegram tokens go to env (secrets shouldn't live in agent.json)
        if cfg.TELEGRAM_BOT_TOKEN:
            env_map[token_env] = cfg.TELEGRAM_BOT_TOKEN
        if cfg.TELEGRAM_CHAT_ID:
            env_map[chat_env] = cfg.TELEGRAM_CHAT_ID

        existing.update(env_map)

        lines = [f"{k}={v}" for k, v in sorted(existing.items())]
        env_path.write_text("\n".join(lines) + "\n")
        print(f"  [Saved .env: {env_path}]")

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
                 cached_opening_audio=""):
        super().__init__()
        self._on_input = on_input    # unused in streaming mode
        self._on_synth = on_synth    # synthesise_sync
        self._on_opening = on_opening
        self._cached_opening_audio = cached_opening_audio
        self._system = system_prompt
        self._cli_session_id = cli_session_id
        self._session = session
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
        self._muted = False       # True = text-only (no audio playback)
        self._eye_mode = False    # True = minimal (chat bar only)

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
        self._settings_btn.hide()

        # Centre status bar for boot
        self._status_bar.start("connecting...")
        self._centre_status_bar()

        # Dynamic opening
        if on_opening:
            if cached_opening_audio:
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
        self._settings_btn.show()
        self._position_status_bar()  # restore normal position

        # Animate boot overlay fade-out
        self._boot_anim = QPropertyAnimation(self, b"boot_opacity", self)
        self._boot_anim.setStartValue(1.0)
        self._boot_anim.setEndValue(0.0)
        self._boot_anim.setDuration(600)
        self._boot_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._boot_anim.finished.connect(self._on_boot_faded)
        self._boot_anim.start()

    def _on_boot_faded(self):
        self._booting = False
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

        self._boot_anim = None
        self.update()

    def _get_boot_opacity(self):
        return self._boot_opacity

    def _set_boot_opacity(self, val):
        self._boot_opacity = val
        self.update()

    boot_opacity = pyqtProperty(float, _get_boot_opacity, _set_boot_opacity)

    def _on_opening_ready(self, text, audio_path):
        self._opening_worker = None
        self._present(text)
        play_audio = self._cached_opening_audio or audio_path
        if play_audio and not self._muted:
            self._audio_player.enqueue(play_audio, 0)
        self._cached_opening_audio = ""
        if self._session:
            self._session.add_turn("companion", text)
        self._history.append({"user": "", "companion": text})
        self._boot_complete()
        # Drain queued messages (morning brief, etc.) after a short pause
        QTimer.singleShot(3000, self._drain_message_queue)

    def _drain_message_queue(self):
        """Check for queued messages from cron jobs and present them."""
        from config import MESSAGE_QUEUE
        if not MESSAGE_QUEUE.exists():
            return
        try:
            queue = json.loads(MESSAGE_QUEUE.read_text())
            MESSAGE_QUEUE.unlink()
        except Exception:
            return
        if not queue:
            return
        for msg in queue:
            text = msg.get("text", "")
            audio = msg.get("audio_path", "")
            if not text:
                continue
            # Verify audio file still exists
            if audio and not Path(audio).exists():
                audio = ""
            self._present_with_audio(text, audio)
            if self._session:
                self._session.add_turn("companion", text)

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


    def paintEvent(self, event):
        p = QPainter(self)
        if self._eye_mode or self._frame.isNull():
            p.fillRect(self.rect(), QColor(18, 18, 20))
            p.end()
            return
        win_w, win_h = self.width(), self.height()
        img_w, img_h = self._frame.width(), self._frame.height()
        # Black background (visible as pillarbox bars when window is wider than video)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        # Fit scaling — preserve aspect ratio, never crop
        scale = min(win_w / img_w, win_h / img_h) * 1.01
        sw, sh = int(img_w * scale), int(img_h * scale)
        # Cache the scaled frame — only rescale when source or size changes
        if (self._scaled_frame is None
                or self._scaled_frame.width() != sw
                or self._scaled_frame.height() != sh):
            self._scaled_frame = self._frame.scaled(
                sw, sh, Qt.IgnoreAspectRatio, Qt.FastTransformation,
            )
        x = (win_w - sw) // 2 + int(self._drift_x)
        y = (win_h - sh) // 2 + int(self._drift_y)
        p.drawImage(x, y, self._scaled_frame)
        # Warm vignette overlay (cached image, alpha-blended)
        if self._vignette_opacity > 0.01:
            if self._vignette_img is None or self._vignette_size != (win_w, win_h):
                # Render vignette to an image at full intensity — modulate via opacity
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
            p.setOpacity(self._vignette_opacity)
            p.drawImage(0, 0, self._vignette_img)
            p.setOpacity(1.0)
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

        # Global Cmd+C shortcut — copies last companion message when no text selected
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        copy_shortcut = QShortcut(QKeySequence.Copy, self)
        copy_shortcut.activated.connect(self._handle_copy)
        self._copy_shortcut = copy_shortcut  # prevent gc

    def _handle_copy(self):
        """Global Cmd+C handler — copy selected input text, or last companion message."""
        if self._bar._input.hasSelectedText():
            self._bar._input.copy()
        else:
            self._transcript.copy_last_companion()

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

        self._settings_btn = _SettingsButton(self)
        self._settings_btn.clicked.connect(self._toggle_settings)

        # Settings panel
        self._settings_panel = SettingsPanel(self)
        self._settings_panel.closed.connect(lambda: self._settings_btn.set_active(False))
        self._settings_open = False

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
        self._settings_btn.move(right - 34 - 38 - 38 - 38 - 38, btn_y)

    def _toggle_settings(self):
        self._settings_open = not self._settings_open
        self._settings_btn.set_active(self._settings_open)
        if self._settings_open:
            self._settings_panel.setGeometry(0, 0, self.width(), self.height())
            self._settings_panel.show()
            self._settings_panel.raise_()
        else:
            self._settings_panel.hide()

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
        self._muted = not self._muted
        self._mute_btn.set_active(self._muted)

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

    def _on_compacting(self):
        """Context window is being compacted — set flush flag and show status."""
        self._needs_memory_flush = True
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
            self._session.add_turn("companion", full_text)

        # Update history with full companion text
        if self._history:
            self._history[-1]["companion"] = full_text

        # Track approximate context usage (~4 chars per token)
        user_text = self._history[-1]["user"] if self._history else ""
        self._approx_tokens += (len(user_text) + len(full_text)) // 4
        if self._approx_tokens > 150000 and not self._compaction_warned:
            self._compaction_warned = True
            self._status_bar.start("context getting full — compaction soon")
            QTimer.singleShot(5000, self._status_bar.stop)

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
                self._session.add_turn("companion", full_text)
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
        # Canvas overlay
        self._reflow_canvas()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._audio_player.stop()
            self.close()
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
                c._session.add_turn("companion", full_text)
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
    def __init__(self, companion_window, chat_panel):
        self._window = companion_window
        self._chat = chat_panel
        self._tray = QSystemTrayIcon()
        from display.icon import get_app_icon
        self._tray.setIcon(get_app_icon())
        self._tray.setToolTip(AGENT_DISPLAY_NAME)
        self._tray.activated.connect(self._on_activated)

        menu = QMenu()
        menu.addAction("Show/Hide", self._toggle_window)
        menu.addAction("Chat Panel", self._toggle_chat)
        menu.addSeparator()
        self._status_action = menu.addAction("Set Away", self._toggle_status)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        self._tray.setContextMenu(menu)
        self._menu = menu  # prevent gc
        self._tray.show()

    def _make_icon(self):
        from PyQt5.QtGui import QPixmap
        pix = QPixmap(22, 22)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawEllipse(5, 5, 12, 12)
        p.end()
        from PyQt5.QtGui import QIcon
        return QIcon(pix)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_window()

    def _toggle_window(self):
        w = self._window
        if w.isVisible():
            w.hide()
        else:
            w.show()
            w.raise_()
            w.activateWindow()
            w._bar.focus_input()

    def _toggle_chat(self):
        self._chat.toggle()

    def _toggle_status(self):
        from core.status import is_away, set_active, set_away
        if is_away():
            set_active()
            self._status_action.setText("Set Away")
            self._window._reset_idle_timer()
        else:
            set_away("manual")
            self._status_action.setText("Set Active")

    def _quit(self):
        self._window.close()

    def hide(self):
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
            cached_opening_audio=""):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

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

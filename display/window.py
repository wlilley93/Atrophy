"""display/window.py — PyQt5 companion window.

Full-bleed video with overlay text and floating input bar.
Streaming inference → sentence-level TTS pipelining for low latency.
"""

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
    QApplication, QWidget, QLineEdit, QPushButton,
)
from PyQt5.QtMultimedia import (
    QMediaPlayer, QMediaContent, QAbstractVideoSurface, QAbstractVideoBuffer,
    QVideoFrame,
)

from config import WINDOW_WIDTH, WINDOW_HEIGHT, IDLE_LOOP

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
    sentence_ready = pyqtSignal(str, str, int)
    tool_use = pyqtSignal(str, str)
    compacting = pyqtSignal()
    done = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, user_text, system, cli_session_id, synth_fn):
        super().__init__()
        self._user_text = user_text
        self._system = system
        self._cli_session_id = cli_session_id
        self._synth = synth_fn

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
                if self._synth:
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
    """Thin animated progress bar with label."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFixedHeight(20)
        self._label = ""
        self._progress = 0.0  # 0..1, or -1 for indeterminate
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._sweep = 0.0
        self.hide()

    def start(self, label: str = "", indeterminate: bool = True):
        self._label = label
        self._progress = -1.0 if indeterminate else 0.0
        self._sweep = 0.0
        self.show()
        self._timer.start()

    def set_progress(self, value: float, label: str = None):
        self._progress = max(0.0, min(1.0, value))
        if label is not None:
            self._label = label
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._sweep = (self._sweep + 0.02) % 1.0
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background track
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 15))
        p.drawRoundedRect(0, h - 3, w, 3, 1, 1)

        # Progress fill
        p.setBrush(QColor(255, 255, 255, 80))
        if self._progress < 0:
            # Indeterminate — sliding highlight
            bar_w = int(w * 0.3)
            x = int(self._sweep * (w + bar_w)) - bar_w
            p.drawRoundedRect(max(0, x), h - 3, min(bar_w, w - max(0, x)), 3, 1, 1)
        else:
            fill_w = int(w * self._progress)
            if fill_w > 0:
                p.drawRoundedRect(0, h - 3, fill_w, 3, 1, 1)

        # Label
        if self._label:
            p.setFont(QFont("Bricolage Grotesque", 10))
            p.setPen(QColor(255, 255, 255, 120))
            p.drawText(QRect(0, 0, w, h - 4), Qt.AlignLeft | Qt.AlignVCenter, self._label)

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
                return

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
        if (obj is self._input
                and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_C
                and event.modifiers() & Qt.ControlModifier
                and not self._input.hasSelectedText()):
            self.copy_requested.emit()
            return True  # consume the event
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
                continue
            self.file_started.emit(index)
            try:
                subprocess.run(
                    ["afplay", "-r", rate, audio_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
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

        # Warm vignette overlay
        self._vignette_opacity = 0.0
        self._vignette_target = 0.0
        self._vignette_img = None  # cached vignette image
        self._vignette_size = (0, 0)  # size it was rendered at

        self.setWindowTitle("Companion")
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

        # Boot overlay — black screen that fades out when ready
        self._boot_opacity = 1.0
        self._booting = True

        self._build_video()
        self._build_overlays()
        self._build_input_bar()
        self._build_mode_buttons()
        self._build_status_bar()
        self._reflow()

        # Hide UI during boot
        self._bar.hide()
        self._transcript.hide()
        self._mute_btn.hide()
        self._eye_btn.hide()

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
        self._status_bar.setFixedWidth(self.width() - _PAD * 4)
        cx = (self.width() - self._status_bar.width()) // 2
        cy = self.height() // 2
        self._status_bar.move(cx, cy)

    def _boot_complete(self):
        """Fade from black to live UI."""
        self._status_bar.stop()
        self._bar.show()
        self._transcript.show()
        self._mute_btn.show()
        self._eye_btn.show()
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

    # ── Mode toggle buttons ──

    def _build_mode_buttons(self):
        self._mute_btn = _MuteButton(self)
        self._mute_btn.clicked.connect(self._toggle_mute)

        self._eye_btn = _EyeButton(self)
        self._eye_btn.clicked.connect(self._toggle_eye)

        self._position_mode_buttons()

    def _position_mode_buttons(self):
        _, right, _, _ = self._content_rect()
        btn_y = _PAD
        self._eye_btn.move(right - 34, btn_y)
        self._mute_btn.move(right - 34 - 38, btn_y)

    def _build_status_bar(self):
        self._status_bar = StatusBar(self)
        self._position_status_bar()

    def _position_status_bar(self):
        w = self.width()
        self._status_bar.setFixedWidth(w - _PAD * 2)
        self._status_bar.move(_PAD, self.height() - _PAD - _BAR_H - 28)

    def _toggle_mute(self):
        self._muted = not self._muted
        self._mute_btn.set_active(self._muted)

    def _toggle_eye(self):
        self._eye_mode = not self._eye_mode
        self._eye_btn.set_active(self._eye_mode)
        if self._eye_mode:
            # Stop video — dark bg drawn by paintEvent
            self._player.pause()
            self.update()
        else:
            # Resume video
            self._player.play()
            self.update()

    # ── Streaming interaction flow ──

    def _on_user_input(self, text):
        self._start_turn(text)

    def _start_turn(self, text):
        # Cancel opening if still loading — user went first
        if getattr(self, '_opening_worker', None):
            self._opening_worker = None
            self._status_bar.stop()

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
        )
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

    def _on_sentence_ready(self, sentence, audio_path, index):
        """A sentence has been synthesised — show text + queue audio."""
        if not self._first_sentence_shown:
            self._first_sentence_shown = True
            self._status_bar.stop()
            # Add a new companion message to the transcript
            self._transcript.add_message("companion", _strip_tags(sentence))
        else:
            self._transcript.append_to_last(_strip_tags(sentence))

        if audio_path and not self._muted:
            self._audio_player.enqueue(audio_path, index)

    def _on_tool_use(self, name, tool_id):
        """Claude invoked a tool — show in UI."""

    def _on_compacting(self):
        """Context window is being compacted — show status."""
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

        # If no sentences came through streaming, show full text now
        if not self._first_sentence_shown and full_text:
            self._present(full_text)

        # Follow-up agency
        from core.agency import should_follow_up
        if full_text and should_follow_up():
            QTimer.singleShot(random.randint(3000, 8000), self._do_follow_up)

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
        )
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
            self._present(full_text)

    def _on_stop(self):
        """User pressed stop — kill inference and audio."""
        if self._worker:
            self._worker.terminate()
            self._worker.wait(2000)
            self._worker = None
        self._status_bar.stop()
        self._bar.set_stop_mode(False)
        # Kill playing audio and clear queue
        try:
            subprocess.run(["pkill", "-f", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        while not self._audio_player._queue.empty():
            try:
                self._audio_player._queue.get_nowait()
            except Exception:
                break

    def _on_error(self, msg):
        self._worker = None
        print(f"  [Inference error: {msg}]")
        # Auto-retry with fresh session
        self._auto_retry()

    def _on_audio_started(self, index):
        """Audio playback began for a sentence."""
        self._vignette_target = 1.0

    def _on_audio_done(self, index):
        """Audio playback finished for a sentence."""
        # Fade out vignette if nothing else queued
        if self._audio_player._queue.empty():
            self._vignette_target = 0.0

    def _present(self, text):
        self._transcript.add_message("companion", _strip_tags(text))

    # ── Public API ──

    def set_video(self, path):
        self._load_video(path)

    # ── Layout ──

    def _content_rect(self):
        """Return the content area clamped to the video's visible bounds."""
        win_w, win_h = self.width(), self.height()
        if self._frame.isNull():
            return _PAD, win_w - _PAD, 0, win_h
        img_w, img_h = self._frame.width(), self._frame.height()
        scale = max(win_w / img_w, win_h / img_h) * 1.01
        sw = int(img_w * scale)
        # Horizontal clamp — video may be narrower than window
        vid_left = max(0, (win_w - sw) // 2)
        vid_right = min(win_w, vid_left + sw)
        left = vid_left + _PAD
        right = vid_right - _PAD
        return left, right, 0, win_h

    def resizeEvent(self, event):
        self._scaled_frame = None  # invalidate cache
        self._vignette_img = None  # invalidate vignette cache
        self._transcript._invalidate_layout()
        self._reflow()
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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._audio_player.stop()
            self.close()
        elif event.key() == Qt.Key_Up:
            self._transcript.scroll_up()
        elif event.key() == Qt.Key_Down:
            self._transcript.scroll_down()
        elif event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
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
            self._shutdown_status.emit("ending session...", 0.15)
            if self._session:
                try:
                    self._session.end(self._system)
                except Exception:
                    pass

            self._shutdown_status.emit("generating next opening...", 0.4)
            try:
                from main import _cache_next_opening
                _cache_next_opening(
                    self._system, self._cli_session_id, self._on_synth,
                )
            except Exception as e:
                print(f"  [Cache opening failed: {e}]")

            self._shutdown_status.emit("done", 1.0)
            self._shutting_down.emit()

        threading.Thread(target=_cleanup, daemon=True).start()

    def _finish_shutdown(self):
        self._status_bar.stop()
        self._shutdown_done = True
        self.close()


# ── Entry point ──

def run_app(on_synth_callback=None, on_opening_callback=None,
            system_prompt="", cli_session_id=None, session=None,
            cached_opening_audio=""):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Handle Ctrl+C gracefully
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Keep a reference so gc doesn't collect the window
    global _companion_window
    _companion_window = CompanionWindow(
        on_synth=on_synth_callback,
        on_opening=on_opening_callback,
        system_prompt=system_prompt,
        cli_session_id=cli_session_id,
        session=session,
        cached_opening_audio=cached_opening_audio,
    )
    _companion_window.show()
    _companion_window.raise_()
    _companion_window._bar.focus_input()

    # Watch for Space changes — re-show window on the active Space
    try:
        from AppKit import NSWorkspace, NSWorkspaceActiveSpaceDidChangeNotification
        from Foundation import NSObject
        import objc

        class _SpaceObserver(NSObject):
            def spaceChanged_(self, notification):
                if _companion_window:
                    # Move to current Space by hiding and re-showing
                    QTimer.singleShot(100, _reshow)

        def _reshow():
            if _companion_window:
                pos = _companion_window.pos()
                _companion_window.hide()
                _companion_window.move(pos)
                _companion_window.show()
                _companion_window.raise_()

        observer = _SpaceObserver.alloc().init()
        NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            observer,
            objc.selector(observer.spaceChanged_, signature=b'v@:@'),
            NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )
        # prevent gc
        _companion_window._space_observer = observer
    except Exception as e:
        print(f"  [Space observer failed: {e}]")

    app.exec_()

_companion_window = None

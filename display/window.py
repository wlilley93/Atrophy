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
    QFont, QColor, QPainter, QPainterPath, QPen, QImage, QLinearGradient,
    QRadialGradient,
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


def _strip_tags(text: str) -> str:
    """Strip audio/prosody tags for display."""
    cleaned = _DISPLAY_TAG_RE.sub('', text)
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
            StreamDone, StreamError, TextDelta,
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

class ThinkingSpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFixedSize(24, 24)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self):
        self._angle = 0
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 160), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawArc(3, 3, 18, 18, self._angle * 16, 270 * 16)
        p.end()


# ── Overlay label — teleprompter ──

class OverlayLabel(QWidget):
    _VISIBLE_LINES = 3
    _SCROLL_PX_PER_SEC = 28
    _FADE_EDGE = 18

    def __init__(self, parent=None, font_family="Bricolage Grotesque",
                 font_size=14, base_alpha=255):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFont(QFont(font_family, font_size))
        self._base_alpha = base_alpha
        self._opacity = 0.0
        self._text = ""
        self._alignment = Qt.AlignLeft | Qt.AlignTop
        self._scroll_offset = 0.0
        self._scroll_timer = None
        self._full_text_height = 0
        self._revealed_chars = 0
        self._target_chars = 0
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(20)  # ~50 chars/sec
        self._reveal_timer.timeout.connect(self._tick_reveal)

    def setText(self, text):
        self._text = text
        self._revealed_chars = len(text)  # instant reveal on full set
        self._target_chars = len(text)
        self._scroll_offset = 0.0
        self._stop_scroll()
        self._calc_text_height()
        if self._needs_scroll():
            self._start_scroll()
        self.update()

    def appendText(self, text):
        """Append text with gradual reveal."""
        old_len = len(self._text)
        self._text = (self._text + " " + text).strip() if self._text else text
        self._target_chars = len(self._text)
        # Don't jump revealed_chars — let the timer catch up
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()
        self._calc_text_height()
        if self._needs_scroll() and not self._scroll_timer:
            self._start_scroll()
        self.update()

    def text(self):
        return self._text

    def setAlignment(self, alignment):
        self._alignment = alignment

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, val):
        self._opacity = val
        self.update()

    opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def _calc_text_height(self):
        if not self._text:
            self._full_text_height = 0
            return
        fm = self.fontMetrics()
        w = self.width() if self.width() > 0 else 400
        br = fm.boundingRect(QRect(0, 0, w, 99999), Qt.TextWordWrap, self._text)
        self._full_text_height = br.height()

    def _visible_height(self):
        return self.height()

    def _needs_scroll(self):
        return self._full_text_height > self._visible_height() + 4

    def _max_scroll(self):
        return max(0, self._full_text_height - self._visible_height())

    def _start_scroll(self):
        if self._scroll_timer:
            return
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(33)
        self._scroll_paused = 60
        self._scroll_timer.timeout.connect(self._tick_scroll)
        self._scroll_timer.start()

    def _stop_scroll(self):
        if self._scroll_timer:
            self._scroll_timer.stop()
            self._scroll_timer = None

    def _tick_reveal(self):
        if self._revealed_chars >= self._target_chars:
            self._reveal_timer.stop()
            return
        # Reveal 2-3 chars per tick (40-60 chars/sec)
        self._revealed_chars = min(self._revealed_chars + 2, self._target_chars)
        self.update()

    def _tick_scroll(self):
        if self._scroll_paused > 0:
            self._scroll_paused -= 1
            return
        max_s = self._max_scroll()
        if self._scroll_offset >= max_s:
            self._stop_scroll()
            return
        self._scroll_offset += self._SCROLL_PX_PER_SEC / 30.0
        self._scroll_offset = min(self._scroll_offset, max_s)
        self.update()

    def paintEvent(self, event):
        if not self._text or self._opacity <= 0.001:
            return
        vis_h = self._visible_height()
        w = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setClipRect(0, 0, w, vis_h)
        p.setFont(self.font())
        y_off = -int(self._scroll_offset)
        text_rect = QRect(0, y_off, w, self._full_text_height + 40)
        flags = self._alignment | Qt.TextWordWrap
        visible = self._text[:self._revealed_chars]
        p.setPen(QColor(0, 0, 0, int(160 * self._opacity)))
        p.drawText(text_rect.adjusted(1, 2, 1, 2), flags, visible)
        p.setPen(QColor(255, 255, 255, int(self._base_alpha * self._opacity)))
        p.drawText(text_rect, flags, visible)
        if self._needs_scroll():
            fade = self._FADE_EDGE
            if self._scroll_offset > 0:
                grad = QLinearGradient(0, 0, 0, fade)
                grad.setColorAt(0, QColor(0, 0, 0, int(200 * self._opacity)))
                grad.setColorAt(1, QColor(0, 0, 0, 0))
                p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                p.fillRect(0, 0, w, fade, grad)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            if self._scroll_offset < self._max_scroll():
                grad = QLinearGradient(0, vis_h - fade, 0, vis_h)
                grad.setColorAt(0, QColor(0, 0, 0, 0))
                grad.setColorAt(1, QColor(0, 0, 0, int(200 * self._opacity)))
                p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                p.fillRect(0, vis_h - fade, w, fade, grad)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.end()

    def sizeHint(self):
        if not self._text:
            return QSize(0, 0)
        fm = self.fontMetrics()
        w = self.width() if self.width() > 0 else 400
        line_h = fm.lineSpacing()
        max_h = line_h * self._VISIBLE_LINES
        br = fm.boundingRect(QRect(0, 0, w, 99999), Qt.TextWordWrap, self._text)
        return QSize(br.width(), min(br.height(), max_h))


def _fade(label, start, end, duration_ms):
    anim = QPropertyAnimation(label, b"opacity", label)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setDuration(duration_ms)
    anim.setEasingCurve(QEasingCurve.InOutQuad)
    anim.start(QPropertyAnimation.DeleteWhenStopped)
    return anim


# ── Input bar ──

class InputBar(QWidget):
    submitted = pyqtSignal(str)
    mic_pressed = pyqtSignal()

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
        self._mic.clicked.connect(self.mic_pressed.emit)

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
        p.setPen(QPen(QColor(255, 255, 255, 180), 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawLine(cx, cy + 5, cx, cy - 5)
        p.drawLine(cx, cy - 5, cx - 4, cy - 1)
        p.drawLine(cx, cy - 5, cx + 4, cy - 1)
        p.end()

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

    def enqueue(self, audio_path: str, index: int):
        self._queue.put((audio_path, index))

    def stop(self):
        self._running = False
        self._queue.put(None)

    def run(self):
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
                    ["afplay", audio_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            self.file_done.emit(index)


# ── Main window ──

class CompanionWindow(QWidget):

    def __init__(self, on_input=None, on_synth=None, on_opening=None,
                 system_prompt="", cli_session_id=None, session=None):
        super().__init__()
        self._on_input = on_input    # unused in streaming mode
        self._on_synth = on_synth    # synthesise_sync
        self._on_opening = on_opening
        self._system = system_prompt
        self._cli_session_id = cli_session_id
        self._session = session
        self._worker = None
        self._anims = []
        self._frame = QImage()
        self._first_sentence_shown = False

        # Conversation history for arrow key browsing
        # Each entry: {"user": str, "companion": str}
        self._history = []
        self._history_index = -1  # -1 = live (current turn)
        self._browsing = False

        # Ken Burns drift
        self._drift_x = 0.0
        self._drift_y = 0.0
        self._drift_dx = 0.3
        self._drift_dy = 0.2
        self._drift_needs_update = True
        self._drift_timer = QTimer(self)
        self._drift_timer.setInterval(33)
        self._drift_timer.timeout.connect(self._tick_drift)
        self._drift_timer.start()

        # Silence detection
        self._silence_timer = QTimer(self)
        self._silence_timer.setInterval(1000)
        self._silence_seconds = 0.0
        self._silence_prompted = False
        self._silence_timer.timeout.connect(self._tick_silence)
        self._silence_timer.start()

        # Warm vignette overlay
        self._vignette_opacity = 0.0
        self._vignette_target = 0.0

        self.setWindowTitle("Companion")
        self.resize(_W, _H)
        self.setMinimumSize(360, 480)

        # Always on top — picture-in-picture style
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # keeps it out of Cmd-Tab, like a PiP overlay
        )

        # Audio player thread
        self._audio_player = AudioPlayer()
        self._audio_player.file_started.connect(self._on_audio_started)
        self._audio_player.file_done.connect(self._on_audio_done)
        self._audio_player.start()

        # Mode flags
        self._muted = False       # True = text-only (no audio playback)
        self._eye_mode = False    # True = minimal (chat bar only)

        self._build_video()
        self._build_overlays()
        self._build_spinner()
        self._build_input_bar()
        self._build_mode_buttons()

        # Dynamic opening
        if on_opening:
            self._spinner.start()
            self._opening_worker = OpeningWorker(on_opening, on_synth)
            self._opening_worker.ready.connect(self._on_opening_ready)
            self._opening_worker.error_signal.connect(self._on_opening_error)
            QTimer.singleShot(300, self._opening_worker.start)
        else:
            QTimer.singleShot(600, lambda: self._present("Ready. Where are we?"))

    def _on_opening_ready(self, text, audio_path):
        self._opening_worker = None
        self._spinner.stop()
        self._present(text)
        if audio_path and not self._muted:
            self._audio_player.enqueue(audio_path, 0)
        if self._session:
            self._session.add_turn("companion", text)
        self._history.append({"user": "", "companion": text})

    def _on_opening_error(self, msg):
        self._opening_worker = None
        self._spinner.stop()
        self._present("Ready. Where are we?")
        self._history.append({"user": "", "companion": "Ready. Where are we?"})

    # ── Silence detection ──

    def _tick_silence(self):
        # Only count silence when not thinking/streaming
        if self._worker is not None:
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
        self._surface = FrameGrabSurface(self)
        self._surface.frame_ready.connect(self._on_frame)
        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._surface)
        self._player.setMuted(True)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._load_video(IDLE_LOOP)

    def _load_video(self, path):
        p = Path(path)
        if p.exists():
            self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(p))))
            self._player.play()

    def _on_frame(self, img):
        self._frame = img
        self._drift_needs_update = False
        self.update()

    def _tick_drift(self):
        self._drift_x += self._drift_dx
        if abs(self._drift_x) > 3.0:
            self._drift_dx = -self._drift_dx
        self._drift_y += self._drift_dy
        if abs(self._drift_y) > 3.0:
            self._drift_dy = -self._drift_dy
        # Smooth vignette interpolation
        if abs(self._vignette_opacity - self._vignette_target) > 0.001:
            self._vignette_opacity += (self._vignette_target - self._vignette_opacity) * 0.05
        if self._drift_needs_update:
            self.update()
        self._drift_needs_update = True

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    def paintEvent(self, event):
        if self._frame.isNull():
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0))
            p.end()
            return
        p = QPainter(self)
        win_w, win_h = self.width(), self.height()
        img_w, img_h = self._frame.width(), self._frame.height()
        # Scale slightly larger (1.01x) to hide edges during drift
        scale = max(win_w / img_w, win_h / img_h) * 1.01
        sw, sh = int(img_w * scale), int(img_h * scale)
        x = (win_w - sw) // 2 + int(self._drift_x)
        y = (win_h - sh) // 2 + int(self._drift_y)
        scaled = self._frame.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.drawImage(x, y, scaled)
        # Warm vignette overlay
        if self._vignette_opacity > 0.01:
            cx, cy = win_w / 2, win_h / 2
            radius = max(win_w, win_h) * 0.7
            grad = QRadialGradient(cx, cy, radius)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(40, 25, 10, int(120 * self._vignette_opacity)))
            p.fillRect(self.rect(), grad)
        p.end()

    # ── Spinner ──

    def _build_spinner(self):
        self._spinner = ThinkingSpinner(self)
        self._position_spinner()

    def _position_spinner(self):
        bar_y = self.height() - _PAD - _BAR_H
        self._spinner.move(_PAD, bar_y - 12 - 24)

    # ── Overlays ──

    def _build_overlays(self):
        self._my_label = OverlayLabel(self, "Bricolage Grotesque", 14, base_alpha=150)
        self._my_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self._her_label = OverlayLabel(self, "Bricolage Grotesque", 15, base_alpha=255)
        self._her_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._reflow()

    # ── Input bar ──

    def _build_input_bar(self):
        self._bar = InputBar(self)
        bar_w = self.width() - _PAD * 2
        self._bar.setFixedSize(bar_w, _BAR_H)
        self._bar.move(_PAD, self.height() - _PAD - _BAR_H)
        self._bar.submitted.connect(self._on_user_input)
        self._bar.raise_()

    # ── Mode toggle buttons ──

    def _build_mode_buttons(self):
        btn_style_off = """
            QPushButton {
                background: rgba(20, 20, 22, 180);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                color: rgba(255, 255, 255, 0.5);
                font-size: 14px;
                font-family: "Bricolage Grotesque";
            }
            QPushButton:hover { background: rgba(40, 40, 44, 200); }
        """
        btn_style_on = """
            QPushButton {
                background: rgba(255, 255, 255, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 14px;
                color: rgba(255, 255, 255, 0.9);
                font-size: 14px;
                font-family: "Bricolage Grotesque";
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.22); }
        """
        self._btn_style_off = btn_style_off
        self._btn_style_on = btn_style_on

        self._mute_btn = QPushButton("mute", self)
        self._mute_btn.setFixedSize(52, 28)
        self._mute_btn.setCursor(Qt.PointingHandCursor)
        self._mute_btn.setStyleSheet(btn_style_off)
        self._mute_btn.clicked.connect(self._toggle_mute)

        self._eye_btn = QPushButton("eye", self)
        self._eye_btn.setFixedSize(42, 28)
        self._eye_btn.setCursor(Qt.PointingHandCursor)
        self._eye_btn.setStyleSheet(btn_style_off)
        self._eye_btn.clicked.connect(self._toggle_eye)

        self._position_mode_buttons()

    def _position_mode_buttons(self):
        if self._eye_mode:
            # In eye mode, place eye button to the right of the bar
            self._eye_btn.move(self.width() - _PAD - 42, _PAD + (_BAR_H - 28) // 2)
        else:
            bar_y = self.height() - _PAD - _BAR_H
            btn_y = bar_y - 36
            right_edge = self.width() - _PAD
            self._eye_btn.move(right_edge - 42, btn_y)
            self._mute_btn.move(right_edge - 42 - 56, btn_y)

    def _toggle_mute(self):
        self._muted = not self._muted
        self._mute_btn.setStyleSheet(
            self._btn_style_on if self._muted else self._btn_style_off
        )
        self._mute_btn.setText("muted" if self._muted else "mute")
        self._mute_btn.setFixedSize(58 if self._muted else 52, 28)
        self._position_mode_buttons()

    def _toggle_eye(self):
        self._eye_mode = not self._eye_mode
        self._eye_btn.setStyleSheet(
            self._btn_style_on if self._eye_mode else self._btn_style_off
        )
        if self._eye_mode:
            # Hide video, overlays, spinner — show only input bar
            self._player.pause()
            self._my_label.hide()
            self._her_label.hide()
            self._spinner.hide()
            self._mute_btn.hide()
            # Collapse window to just the bar
            self._pre_eye_height = self.height()
            self.setFixedHeight(_BAR_H + _PAD * 2)
            self._bar.move(_PAD, _PAD)
        else:
            # Restore everything
            self.setMinimumSize(360, 480)
            self.setMaximumSize(16777215, 16777215)
            self.resize(self.width(), getattr(self, '_pre_eye_height', _H))
            self._player.play()
            self._my_label.show()
            self._her_label.show()
            self._mute_btn.show()
            self._reflow()

    # ── Streaming interaction flow ──

    def _on_user_input(self, text):
        # Reset silence detection
        self._silence_seconds = 0.0
        self._silence_prompted = False

        # Fade out old overlays
        self._anims.clear()
        self._anims.append(_fade(self._my_label, self._my_label.opacity, 0.0, 150))
        self._anims.append(_fade(self._her_label, self._her_label.opacity, 0.0, 150))
        QTimer.singleShot(170, lambda: self._start_turn(text))

    def _start_turn(self, text):
        # Exit history browsing
        self._browsing = False
        self._history_index = -1

        # Show user message (unless eye mode)
        self._her_label.setText("")
        self._my_label.setText(text)
        if not self._eye_mode:
            self._reflow()
            self._anims.append(_fade(self._my_label, 0.0, 1.0, 200))

        # Record user turn — companion text filled in when done
        self._history.append({"user": text, "companion": ""})

        if self._session:
            self._session.add_turn("will", text)

        # Start streaming pipeline
        if not self._eye_mode:
            self._spinner.start()
        self._first_sentence_shown = False

        self._worker = StreamingPipelineWorker(
            user_text=text,
            system=self._system,
            cli_session_id=self._cli_session_id,
            synth_fn=self._on_synth,
        )
        self._worker.sentence_ready.connect(self._on_sentence_ready)
        self._worker.tool_use.connect(self._on_tool_use)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_sentence_ready(self, sentence, audio_path, index):
        """A sentence has been synthesised — show text + queue audio."""
        if not self._first_sentence_shown:
            self._first_sentence_shown = True
            self._spinner.stop()
            self._her_label.setText(_strip_tags(sentence))
            self._reflow()
            self._anims.append(_fade(self._her_label, 0.0, 1.0, 300))
        else:
            self._her_label.appendText(_strip_tags(sentence))
            self._reflow()

        if audio_path and not self._muted:
            self._audio_player.enqueue(audio_path, index)

    def _on_tool_use(self, name, tool_id):
        """Claude invoked a tool — show in UI."""
        # Map tool names to human-readable labels
        _labels = {
            'remember': 'remembering...',
            'recall_session': 'recalling...',
            'get_threads': 'checking threads...',
            'track_thread': 'tracking...',
            'read_note': 'reading notes...',
            'write_note': 'writing...',
            'search_notes': 'searching notes...',
            'daily_digest': 'reading digest...',
            'ask_will': 'thinking...',
        }
        label = _labels.get(name, f'{name}...')
        self._spinner.start()
        # Briefly show tool label — reuse my_label with low opacity
        self._my_label.setText(label)
        self._reflow()
        self._anims.append(_fade(self._my_label, 0.0, 0.5, 200))
        # Fade out after 1.5s
        QTimer.singleShot(1500, lambda: self._anims.append(_fade(self._my_label, self._my_label.opacity, 0.0, 300)))

    def _on_done(self, full_text, session_id):
        """Stream complete."""
        self._worker = None
        self._spinner.stop()
        self._cli_session_id = session_id

        # Update session
        if self._session:
            self._session.set_cli_session_id(session_id)
            self._session.add_turn("companion", full_text)

        # Update history with full companion text
        if self._history:
            self._history[-1]["companion"] = full_text

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
        self._worker.done.connect(self._on_followup_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_followup_done(self, full_text, session_id):
        """Follow-up complete."""
        self._worker = None
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

    def _on_error(self, msg):
        self._worker = None
        self._spinner.stop()
        self._present(f"[error: {msg}]")

    def _on_audio_started(self, index):
        """Audio playback began for a sentence."""
        self._vignette_target = 1.0

    def _on_audio_done(self, index):
        """Audio playback finished for a sentence."""
        # Fade out vignette if nothing else queued
        if self._audio_player._queue.empty():
            self._vignette_target = 0.0

    def _present(self, text):
        self._her_label.setText(_strip_tags(text))
        self._reflow()
        self._anims.append(_fade(self._her_label, 0.0, 1.0, 400))

    # ── Public API ──

    def set_video(self, path):
        self._load_video(path)

    # ── Layout ──

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        bar_w = w - _PAD * 2
        self._bar.setFixedSize(bar_w, _BAR_H)
        if self._eye_mode:
            self._bar.move(_PAD, _PAD)
        else:
            self._bar.move(_PAD, h - _PAD - _BAR_H)
        self._position_spinner()
        self._position_mode_buttons()
        self._reflow()
        super().resizeEvent(event)

    def _reflow(self):
        w, h = self.width(), self.height()
        bar_y = h - _PAD - _BAR_H
        gap = 12
        her_h = min(max(self._her_label.sizeHint().height(), 24), 80)
        her_y = bar_y - gap - her_h
        self._her_label.setGeometry(_PAD, her_y, w - _PAD * 2, her_h)
        my_h = min(max(self._my_label.sizeHint().height(), 22), 50)
        if not self._her_label.text():
            my_y = bar_y - gap - my_h
        else:
            my_y = her_y - my_h - 4
        self._my_label.setGeometry(_PAD, my_y, w - _PAD * 2, my_h)

    # ── History browsing ──

    def _browse_history(self, direction):
        """Browse conversation history. direction: -1 = older, +1 = newer."""
        if not self._history:
            return

        if not self._browsing:
            # Enter browsing mode from the latest exchange
            self._browsing = True
            self._history_index = len(self._history) - 1
            if direction == -1 and self._history_index > 0:
                self._history_index -= 1
        else:
            new_idx = self._history_index + direction
            if new_idx < 0:
                return  # already at oldest
            if new_idx >= len(self._history):
                # Back to live — exit browsing
                self._browsing = False
                self._history_index = -1
                self._show_live()
                return
            self._history_index = new_idx

        self._show_history_entry(self._history_index)

    def _show_history_entry(self, index):
        """Display a past exchange with fade transition."""
        entry = self._history[index]

        # Fade out
        self._anims.clear()
        self._anims.append(_fade(self._my_label, self._my_label.opacity, 0.0, 120))
        self._anims.append(_fade(self._her_label, self._her_label.opacity, 0.0, 120))

        def _show():
            self._my_label.setText(entry["user"])
            self._her_label.setText(_strip_tags(entry["companion"]))
            self._reflow()
            if entry["user"]:
                self._anims.append(_fade(self._my_label, 0.0, 1.0, 200))
            if entry["companion"]:
                self._anims.append(_fade(self._her_label, 0.0, 1.0, 200))

        QTimer.singleShot(130, _show)

    def _show_live(self):
        """Return to the current/latest exchange."""
        if self._history:
            self._show_history_entry(len(self._history) - 1)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._audio_player.stop()
            self.close()
        elif event.key() == Qt.Key_Up:
            self._browse_history(-1)
        elif event.key() == Qt.Key_Down:
            self._browse_history(1)

    def closeEvent(self, event):
        # Stop all timers
        self._drift_timer.stop()
        self._silence_timer.stop()
        self._audio_player.stop()
        if self._worker:
            self._worker.quit()
            self._worker.wait(2000)
        if self._session:
            import threading
            def _end():
                try:
                    self._session.end(self._system)
                except Exception:
                    pass
            t = threading.Thread(target=_end, daemon=True)
            t.start()
            t.join(timeout=5)
        super().closeEvent(event)


# ── Entry point ──

def run_app(on_synth_callback=None, on_opening_callback=None,
            system_prompt="", cli_session_id=None, session=None):
    app = QApplication.instance() or QApplication(sys.argv)

    # Handle Ctrl+C gracefully
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    win = CompanionWindow(
        on_synth=on_synth_callback,
        on_opening=on_opening_callback,
        system_prompt=system_prompt,
        cli_session_id=cli_session_id,
        session=session,
    )
    win.show()
    win.raise_()
    win._bar.focus_input()
    sys.exit(app.exec_())

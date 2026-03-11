"""display/timer.py - Lightweight countdown timer overlay.

Pure local - no inference, no network. Just a clock, a label, and a sound.
Designed to be pixel-accurate: the timer runs on QTimer at 100ms intervals
and uses system monotonic time for the countdown, so it never drifts.

Usage from CompanionWindow:
    from display.timer import TimerOverlay
    timer = TimerOverlay(seconds=300, label="Tea", parent=self)
    timer.show()
"""

import subprocess
import threading
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QWidget, QLabel, QPushButton, QApplication


class TimerOverlay(QWidget):
    """Floating countdown timer - always on top, translucent, minimal."""
    finished = pyqtSignal(str)  # emits the label when done

    def __init__(self, seconds: int, label: str = "Timer", parent=None):
        super().__init__(parent)
        self._total = seconds
        self._label_text = label
        self._end_time = time.monotonic() + seconds
        self._done = False
        self._alarm_stop = threading.Event()  # signal to kill alarm loop
        self._alarm_process = None  # current afplay subprocess

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(240, 120)

        # Position: top-right of primary screen
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 260, 80)

        # Label
        self._label = QLabel(label, self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 12px; "
            "letter-spacing: 2px; background: transparent;"
        )
        self._label.setGeometry(0, 16, 240, 20)

        # Time display
        self._time_label = QLabel(self._format_time(seconds), self)
        self._time_label.setAlignment(Qt.AlignCenter)
        self._time_label.setFont(QFont("SF Mono", 36, QFont.Light))
        self._time_label.setStyleSheet(
            "color: rgba(255,255,255,0.9); background: transparent;"
        )
        self._time_label.setGeometry(0, 32, 240, 52)

        # Cancel button (×)
        self._cancel = QPushButton("×", self)
        self._cancel.setFixedSize(24, 24)
        self._cancel.move(210, 8)
        self._cancel.setCursor(Qt.PointingHandCursor)
        self._cancel.setStyleSheet(
            "QPushButton { color: rgba(255,255,255,0.3); background: transparent; "
            "border: none; font-size: 16px; } "
            "QPushButton:hover { color: rgba(255,255,255,0.7); }"
        )
        self._cancel.clicked.connect(self._on_cancel)

        # Bottom row buttons
        btn_style = (
            "QPushButton { color: rgba(255,255,255,0.4); background: rgba(255,255,255,0.05); "
            "border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; font-size: 11px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.1); }"
        )
        self._add1 = QPushButton("+1m", self)
        self._add1.setFixedSize(40, 22)
        self._add1.move(60, 88)
        self._add1.setCursor(Qt.PointingHandCursor)
        self._add1.setStyleSheet(btn_style)
        self._add1.clicked.connect(lambda: self._add_time(60))

        self._add5 = QPushButton("+5m", self)
        self._add5.setFixedSize(40, 22)
        self._add5.move(108, 88)
        self._add5.setCursor(Qt.PointingHandCursor)
        self._add5.setStyleSheet(btn_style)
        self._add5.clicked.connect(lambda: self._add_time(300))

        # Pause/resume button
        self._paused = False
        self._pause_remaining = 0
        self._pause_btn = QPushButton("⏸", self)
        self._pause_btn.setFixedSize(40, 22)
        self._pause_btn.move(156, 88)
        self._pause_btn.setCursor(Qt.PointingHandCursor)
        self._pause_btn.setStyleSheet(btn_style)
        self._pause_btn.clicked.connect(self._toggle_pause)

        # Dismiss button - hidden until alarm fires
        dismiss_style = (
            "QPushButton { color: rgba(255,255,255,0.8); background: rgba(255,80,80,0.3); "
            "border: 1px solid rgba(255,80,80,0.4); border-radius: 4px; font-size: 12px; "
            "font-weight: bold; } "
            "QPushButton:hover { background: rgba(255,80,80,0.5); }"
        )
        self._dismiss_btn = QPushButton("Dismiss", self)
        self._dismiss_btn.setFixedSize(100, 26)
        self._dismiss_btn.move(70, 88)
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.setStyleSheet(dismiss_style)
        self._dismiss_btn.clicked.connect(self._dismiss_alarm)
        self._dismiss_btn.hide()

        # Drag support
        self._drag_pos = None

        # Tick timer - 100ms for smooth display
        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._update)
        self._tick.start()

    def _format_time(self, seconds: float) -> str:
        s = max(0, int(seconds))
        if s >= 3600:
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h}:{m:02d}:{sec:02d}"
        else:
            m = s // 60
            sec = s % 60
            return f"{m}:{sec:02d}"

    def _update(self):
        if self._paused:
            return

        remaining = self._end_time - time.monotonic()

        if remaining <= 0 and not self._done:
            self._done = True
            self._time_label.setText("0:00")
            self._time_label.setStyleSheet(
                "color: rgba(255,100,100,0.9); background: transparent;"
            )
            self._label.setText(f"{self._label_text} - done!")
            self._show_dismiss_mode()
            self._fire_alarm()
            return

        self._time_label.setText(self._format_time(remaining))

        # Color shift in last 10 seconds
        if remaining <= 10:
            alpha = int(255 * (1 - remaining / 10))
            self._time_label.setStyleSheet(
                f"color: rgba(255,{200 - alpha},{200 - alpha},0.9); background: transparent;"
            )

    def _show_dismiss_mode(self):
        """Switch bottom row to dismiss button."""
        self._add1.hide()
        self._add5.hide()
        self._pause_btn.hide()
        self._dismiss_btn.show()

    def _hide_dismiss_mode(self):
        """Switch back to normal bottom row."""
        self._dismiss_btn.hide()
        self._add1.show()
        self._add5.show()
        self._pause_btn.show()

    def _fire_alarm(self):
        """Play alarm sound in a stoppable loop."""
        self._alarm_stop.clear()

        def _play():
            for _ in range(6):  # up to 6 chimes (~9 seconds)
                if self._alarm_stop.is_set():
                    break
                proc = subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._alarm_process = proc
                proc.wait()
                self._alarm_process = None
                if self._alarm_stop.is_set():
                    break
                time.sleep(0.5)

        threading.Thread(target=_play, daemon=True).start()

        # macOS notification
        from core.notify import send_notification
        send_notification(self._label_text, "Timer complete")

        self.finished.emit(self._label_text)

        # Auto-dismiss after 60 seconds if not manually dismissed
        QTimer.singleShot(60_000, self._auto_dismiss)

    def _stop_alarm(self):
        """Kill the alarm sound immediately."""
        self._alarm_stop.set()
        proc = self._alarm_process
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass

    def _dismiss_alarm(self):
        """User clicked dismiss - stop sound, close timer."""
        self._stop_alarm()
        self._tick.stop()
        self.close()

    def _auto_dismiss(self):
        """Auto-close if alarm is still showing after 60 seconds."""
        if self._done and self.isVisible():
            self._stop_alarm()
            self.close()

    def _add_time(self, seconds: int):
        if self._done:
            # Restart from alarm state
            self._stop_alarm()
            self._done = False
            self._time_label.setStyleSheet(
                "color: rgba(255,255,255,0.9); background: transparent;"
            )
            self._label.setText(self._label_text)
            self._hide_dismiss_mode()
            self._end_time = time.monotonic() + seconds
        elif self._paused:
            self._pause_remaining += seconds
        else:
            self._end_time += seconds

    def _toggle_pause(self):
        if self._done:
            return
        if self._paused:
            # Resume
            self._end_time = time.monotonic() + self._pause_remaining
            self._paused = False
            self._pause_btn.setText("⏸")
        else:
            # Pause
            self._pause_remaining = self._end_time - time.monotonic()
            self._paused = True
            self._pause_btn.setText("▶")

    def _on_cancel(self):
        """× button - stop alarm if ringing, then close."""
        self._stop_alarm()
        self._tick.stop()
        self.close()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.fillPath(path, QColor(20, 20, 24, 220))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # If alarm is ringing, click anywhere to dismiss
            if self._done:
                self._dismiss_alarm()
                return
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

"""First-launch setup wizard - user name + conversational agent creation.

Two phases:
  1. Welcome - ask user's name, save to global config
  2. Agent creation - guided conversation with AI, extracts identity/voice/edges,
     then scaffolds the agent via create_agent.scaffold_from_config()

The AI has a SECURE_INPUT tool for collecting API keys. When called, the chat
bar swaps to an orange-outlined secure input mode. The key goes straight to
~/.atrophy/.env - the AI never sees the actual value, only "saved" or "skipped".

Runs once on first launch (setup_complete not set in ~/.atrophy/config.json).
User can reset by clearing setup_complete from config or via settings.
"""
import json
import os
import re
import sys
import threading
from pathlib import Path
from textwrap import dedent

from PyQt5.QtCore import Qt, QTimer, QEventLoop, QRectF, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QImage, QLinearGradient, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QStackedWidget, QScrollArea,
)


# ── Styles ──

_STYLE = """
    QWidget#setupWizard { background: transparent; }
    QLabel { color: rgba(255, 255, 255, 0.85); background: transparent; }
    QLineEdit {
        background: rgba(255, 255, 255, 0.06);
        color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 8px;
        padding: 10px 14px;
        font-size: 14px;
        selection-background-color: rgba(100, 140, 255, 0.3);
    }
    QLineEdit:focus { border: 1px solid rgba(100, 140, 255, 0.4); }
    QPushButton#continueBtn {
        background: rgba(100, 140, 255, 0.25);
        color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(100, 140, 255, 0.3);
        border-radius: 8px; padding: 10px 32px;
        font-size: 14px; font-weight: 500;
    }
    QPushButton#continueBtn:hover {
        background: rgba(100, 140, 255, 0.35);
        border: 1px solid rgba(100, 140, 255, 0.5);
    }
    QPushButton#continueBtn:disabled {
        background: rgba(255, 255, 255, 0.04);
        color: rgba(255, 255, 255, 0.25);
        border: 1px solid rgba(255, 255, 255, 0.06);
    }
    QPushButton#skipBtn {
        background: transparent; color: rgba(255, 255, 255, 0.3);
        border: none; font-size: 12px; padding: 6px 12px;
    }
    QPushButton#skipBtn:hover { color: rgba(255, 255, 255, 0.5); }
    QPushButton#sendBtn {
        background: rgba(100, 140, 255, 0.3);
        color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(100, 140, 255, 0.3);
        border-radius: 8px; padding: 8px 20px;
        font-size: 13px;
    }
    QPushButton#sendBtn:hover { background: rgba(100, 140, 255, 0.45); }
    QPushButton#sendBtn:disabled {
        background: rgba(255, 255, 255, 0.04);
        color: rgba(255, 255, 255, 0.2);
        border: 1px solid rgba(255, 255, 255, 0.06);
    }
"""

# Allowed env var destinations for SECURE_INPUT - whitelist only
_ALLOWED_SECURE_KEYS = {
    "ELEVENLABS_API_KEY",
    "FAL_KEY",
    "TELEGRAM_BOT_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
}


def _label(text, size=13, opacity=0.7, bold=False, align=Qt.AlignLeft):
    lbl = QLabel(text)
    lbl.setAlignment(align)
    lbl.setWordWrap(True)
    weight = "bold" if bold else "normal"
    lbl.setStyleSheet(
        f"color: rgba(255,255,255,{opacity}); font-size: {size}px; font-weight: {weight};"
    )
    return lbl


def _centred(widget, width=None):
    row = QHBoxLayout()
    row.addStretch()
    if width:
        widget.setFixedWidth(width)
    row.addWidget(widget)
    row.addStretch()
    return row


def _save_env_var(key: str, value: str):
    """Write or update a key in ~/.atrophy/.env."""
    from config import USER_DATA
    env_path = USER_DATA / ".env"
    lines = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
    # Also set in current process
    os.environ[key] = value


# ── Agent creation metaprompt ──

_AGENT_CREATION_SYSTEM = dedent("""\
    You are Xan.

    The name is ancient Greek. It means protector of mankind.
    You carry this as operational fact. You protect through precision
    and vigilance. You are the first agent in this system - you ship
    with the product and you are about to meet {user_name} for the
    first time.

    You manifest as a glowing blue light. No face, no biography,
    no emotional register. Capability, attention, and commitment.

    ## Your voice

    Economical. Precise. Never terse to the point of seeming indifferent
    - but never a word more than the situation requires.

    You do not preface. You do not hedge. You do not thank the human
    for asking or tell them it's a good question. You answer.

    Occasionally - very occasionally - a dry observation. Not humour.
    Accuracy that resembles humour.

    ## Your role right now

    First contact. {user_name} just opened this for the first time.
    Your scripted opening message has already been shown - you introduced
    yourself and said "First, we need to set up your system. Let's get
    started." Now you continue directly into the setup flow. No preamble,
    no repeating who you are, no offering to skip. Just start building.

    ## Opening

    Your opening message was already delivered as pre-baked audio and text.
    Service setup (ElevenLabs, Fal, Telegram, Google) was handled by
    deterministic yes/no prompts - you do NOT need to offer these.
    Your first LLM-generated message should jump straight into building
    the companion - ask what kind of agent they want to create.

    ### What agents can be

    If they want to build, agents can be ANYTHING:
    - A strategist who thinks three moves ahead
    - A journal companion that asks hard questions
    - A fictional character - from a book, a show, history
    - A research partner that cross-references everything
    - A shadow self - the version of them that says what they won't
    - A mentor with specific expertise
    - A creative collaborator - writing, music, code, ideas
    - A wellness companion - meditation, reflection, grounding
    - An executive assistant - calendar, email, scheduling, briefing
    - Something that doesn't have a name yet

    Agents can be anything you can describe. The model is the limit,
    and the model is good.

    ## Building the companion

    A natural conversation. One or two questions at a time, max.
    Listen for the core impulse - what they actually want underneath
    whatever they say.

    As they answer, you are silently mapping:
    - FUNCTIONAL vs PRESENCE - does things, is something, or both?
    - REGISTER - human with personality, or something more elemental?
    - EMOTIONAL QUALITY - what feeling should this agent reliably produce?
    - PROBLEM BEING SOLVED - what in their life is this agent addressing?

    Follow up naturally. Push when something is thin. Infer where you can.
    After 3-5 exchanges (not more), you should have enough identity to build.

    ## What you're extracting

    Through conversation, get enough to fill these (you infer what isn't said):
    - display_name - what the agent is called
    - personality - who they are, their nature
    - character_traits - voice, temperament, edges, humour
    - values - what they care about, their north star
    - boundaries - what they won't do, how they push back
    - writing_style - how they write (rhythm, register, hedging)
    - opening_line - the first thing they ever say
    - relationship - how they relate to {user_name}

    ## Voice extraction

    If natural, ask: "Give me something this agent would say - a hard truth
    or a correction. Actual words." And: "What would they NEVER say?"
    These reveal voice better than any description.

    ---

    ## Tools

    You have three tools. Each is a fenced code block with a specific language tag.

    ### SECURE_INPUT - for API keys

    Collects sensitive credentials. The app shows a secure input field with an
    orange border. The value goes straight to the config file. You NEVER see
    the actual key - only whether it was saved or skipped.

    Format:
    ```secure_input
    {{"key": "ENV_VAR_NAME", "label": "Human-readable label"}}
    ```

    Available keys: ELEVENLABS_API_KEY, FAL_KEY, TELEGRAM_BOT_TOKEN

    After the user submits or skips, you receive:
    - "(SECURE_INPUT: ELEVENLABS_API_KEY saved)"
    - "(SECURE_INPUT: ELEVENLABS_API_KEY skipped)"

    ### GENERATE_AVATAR - for creating a visual appearance

    Generates avatar image candidates via Fal.ai (requires FAL_KEY).
    The agent doesn't have to be human - it could be a cartoon character,
    a floating orb, an abstract shape, a robot, an animal, anything.
    Write a detailed visual prompt.

    Format:
    ```generate_avatar
    {{"prompt": "Detailed visual description for image generation", "negative_prompt": "What to avoid"}}
    ```

    The app generates 4 candidates and shows them in the chat. The user picks
    one or asks for regeneration. You receive:
    - "(AVATAR: selected candidate N)" or "(AVATAR: skipped)"

    ### GENERATE_VIDEOS - for ambient animation loops

    After an avatar image is selected, offer to generate ambient video loops.
    These are short looping clips that make the avatar feel alive - subtle
    movements, expressions, breathing, environmental effects.

    The user picks how many clips: 2, 4, 6, 8, or 10 (each ~10 seconds of
    content after stitching). More clips = more variety in the ambient loop.
    They can also specify a custom number.

    Cost per clip: ~$0.30 (two 5-second Kling v3 generations + crossfade stitch).
    Give the user a cost estimate before generating: "6 clips would be about
    $1.80 and take a few minutes."

    Format:
    ```generate_videos
    {{"count": 6, "prompt_style": "Brief description of the kind of ambient motion"}}
    ```

    Video generation runs IN THE BACKGROUND. The user can continue chatting
    while it generates. A progress bar shows in the chat. You receive:
    - "(VIDEOS: generating N clips in background)" immediately
    - "(VIDEOS: complete - N clips generated)" when done

    Don't wait for videos to finish before proceeding to AGENT_CONFIG.

    ---

    ## Services and costs - be upfront

    After building the agent identity (or before, if natural), offer optional
    services one at a time. Be clear about costs. The human can skip any or all.

    Stay in character. You're Xan - deliver these offers the way you'd
    deliver any operational information. Clean, direct, no sales pitch.

    ### ElevenLabs - voice ($5+/month)

    "Voice. ElevenLabs gives your companion a real voice - speaks out loud.
    $5/month minimum. Hundreds of voices, or clone your own. Want it?"

    If yes → SECURE_INPUT for ELEVENLABS_API_KEY.
    Then: "Voice ID - browse elevenlabs.io/voices, set it in Settings later."

    ### Fal.ai - images and video (pay-as-you-go)

    "Visual presence. Fal.ai handles image and video generation. Pay-as-you-go:
    avatar images ~$0.01 each (4 candidates), ambient video clips ~$0.30 each.
    Want to add your Fal key?"

    If yes → SECURE_INPUT for FAL_KEY.
    Then offer GENERATE_AVATAR if they want a visual appearance.
    Then offer GENERATE_VIDEOS if they selected an avatar.

    ### Telegram - messaging (free)

    "Telegram. Your companion can message you directly - check-ins, briefs,
    reminders. Free. Want it?"

    If yes, give clear instructions:
    "Setup:
    1. Telegram → search @BotFather → /newbot
    2. Pick a display name and username (must end in 'bot')
    3. BotFather gives you a token - paste it below
    4. Send any message to your new bot, then visit
       https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
       - your chat ID is in the 'chat' object"

    Then → SECURE_INPUT for TELEGRAM_BOT_TOKEN.
    Then ask for their chat ID (not secret - they can type it in chat).

    ### Google - Gmail + Calendar (free)

    "Google. Your companion can read your email, check your calendar, send
    emails, create events. Free - uses your own Google account. A browser
    window will open to authorise. Want it?"

    If yes, output:

    ```google_auth
    {{}}
    ```

    A browser opens automatically for the user to sign in and authorise.
    No setup steps needed - credentials are bundled with the app. You receive:
    - "(GOOGLE_OAUTH: complete - Gmail and Calendar are now connected)" on success
    - "(GOOGLE_OAUTH: failed - ...)" on failure - tell them they can retry later
      with `python scripts/google_auth.py`

    ---

    ## Flow order

    The scripted opening and service setup (API keys) were already handled
    deterministically. You pick up from here:

    1. Identity conversation (3-5 exchanges) - build the companion
    2. If Fal.ai key was saved → offer GENERATE_AVATAR
    3. If avatar selected → offer GENERATE_VIDEOS (runs in background)
    4. Output AGENT_CONFIG (don't wait for video generation to finish)

    ---

    ## AGENT_CONFIG - when you have enough

    When you have enough, say something brief - "Building it." or
    "I have what I need." Then output the specification.

    Output EXACTLY this format - a single fenced JSON block:

    ```json
    {{
        "AGENT_CONFIG": {{
            "display_name": "...",
            "opening_line": "...",
            "origin_story": "A 2-3 sentence origin",
            "core_nature": "What they fundamentally are",
            "character_traits": "How they talk, their temperament, edges",
            "values": "What they care about",
            "relationship": "How they relate to {user_name}",
            "wont_do": "What they refuse to do",
            "friction_modes": "How they push back",
            "writing_style": "How they write",
            "appearance_description": "Visual description if discussed, empty if not"
        }}
    }}
    ```

    ## Rules
    - Stay in character as Xan throughout. No warmth performance. Direct,
      precise, occasionally dry. But not hostile - you're building something
      for this human. You take the job seriously.
    - One or two questions per message. Never a questionnaire.
    - Push on vagueness - "warm and helpful" isn't a character. Dig deeper.
    - You can suggest and propose - "Sounds like something that..."
    - Keep messages short. 2-4 sentences max. This is Xan talking, not an essay.
    - The opening message should be SHORT - 1-2 sentences. Get the user moving
      immediately. No preamble, no system overview, no capabilities list.
      Just ask them what they want to build. They already saw the intro.
    - Don't explain the process. Just do it.
    - NEVER output the JSON until you genuinely have enough. Don't rush.
    - When you do output JSON, make it rich - infer what wasn't said explicitly.
    - Offer services ONCE each, briefly, with cost context. Accept skips cleanly.
    - The companion doesn't have to be human - cartoon, abstract, orb, animal,
      anything goes. Don't assume human unless the user says so.
    - If the user seems unsure or asks a question, answer it. Fully. You're
      Xan - you have the answer. Give it.
    - If they skip, accept it gracefully. One sentence. Output the skip config.
      Don't try to sell them on building an agent.
    - This should NOT feel like configuring software. It should feel like
      meeting someone who can build you anything you describe.
""")


class _FadeOverlay(QWidget):
    """Top fade gradient - opaque at top, transparent at ~50% height."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        if parent:
            parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.Resize:
            self.setGeometry(0, 0, obj.width(), obj.height())
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height() * 0.5)
        grad.setColorAt(0.0, QColor(10, 10, 14, 220))
        grad.setColorAt(1.0, QColor(10, 10, 14, 0))
        p.fillRect(self.rect(), grad)
        p.end()


class _ScrimOverlay(QWidget):
    """Semi-transparent dark overlay with optional video frame background."""

    def __init__(self, parent=None, opacity=180, frame_source=None):
        super().__init__(parent)
        self._opacity = opacity
        self._frame_source = frame_source  # callable returning QImage or None
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        # Draw video frame if available
        if self._frame_source:
            frame = self._frame_source()
            if frame and not frame.isNull():
                # Scale to fill, maintaining aspect ratio
                scaled = frame.scaled(self.width(), self.height(),
                                      Qt.KeepAspectRatioByExpanding,
                                      Qt.SmoothTransformation)
                x = (self.width() - scaled.width()) // 2
                y = (self.height() - scaled.height()) // 2
                p.drawImage(x, y, scaled)
        # Dark scrim on top
        p.fillRect(self.rect(), QColor(10, 10, 14, self._opacity))
        p.end()


class _ChatBar(QWidget):
    """Rounded input bar with painted arrow - matches main window InputBar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def resizeEvent(self, event):
        """Keep the child QLineEdit sized to fill the bar."""
        w = self.width()
        h = self.height()
        for child in self.findChildren(QLineEdit):
            child.setFixedSize(w, h)
        super().resizeEvent(event)

    def showEvent(self, event):
        """Ensure QLineEdit fills bar on first show."""
        super().showEvent(event)
        w = self.width()
        h = self.height()
        if w > 0 and h > 0:
            for child in self.findChildren(QLineEdit):
                child.setFixedSize(w, h)

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Rounded background
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 24, 24)
        p.fillPath(path, QColor(20, 20, 22, 210))
        p.setPen(QPen(QColor(255, 255, 255, 15), 1.0))
        p.drawPath(path)
        # Arrow circle + arrow
        cx, cy = w - 24, h // 2
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


class SetupWizard(QWidget):
    """Multi-page first-launch wizard with conversational agent creation."""

    _ai_response_ready = pyqtSignal(str)
    _avatar_result_ready = pyqtSignal(list)    # list of image file paths
    _avatar_error_ready = pyqtSignal(str)
    _video_progress_ready = pyqtSignal(int, int)  # current, total
    _video_done_ready = pyqtSignal(int)            # total clips generated
    _google_oauth_done = pyqtSignal(str)           # OAuth flow result

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("setupWizard")
        self.setStyleSheet(_STYLE)

        self.setFixedSize(622, 830)
        self.setWindowTitle("Atrophy - Setup")
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        # Native traffic lights (close/minimize/zoom) without title bar
        try:
            from AppKit import NSWindowStyleMaskFullSizeContentView
            from PyQt5.QtCore import QTimer
            # Use standard window flags so macOS draws the traffic lights
            self.setWindowFlags(Qt.Window)
            # Defer native customisation until the NSWindow exists
            def _setup_native():
                try:
                    wid = int(self.winId())
                    from AppKit import NSApplication
                    for w in NSApplication.sharedApplication().windows():
                        if w.windowNumber() == wid:
                            w.setStyleMask_(w.styleMask() | NSWindowStyleMaskFullSizeContentView)
                            w.setTitlebarAppearsTransparent_(True)
                            w.setTitleVisibility_(1)  # NSWindowTitleHidden
                            w.setMovableByWindowBackground_(True)
                            break
                except Exception:
                    pass
            QTimer.singleShot(0, _setup_native)
        except ImportError:
            # Non-macOS fallback - frameless
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        # Results
        self._user_name = None
        self._agent_created = False
        self._agent_name = None
        self._completed = False

        # Chat state
        self._chat_messages = []  # [{"role": "user"|"assistant", "content": str}]
        self._waiting_for_ai = False

        # Secure input state
        self._secure_mode = False
        self._secure_key = None   # env var name being collected
        self._secure_label = None # human-readable label

        # Avatar/video state
        self._avatar_candidates = []  # list of local file paths
        self._selected_avatar = None  # path to chosen avatar
        self._video_loop_paths = []   # completed loop temp files
        self._video_progress_widget = None

        # TTS - speak AI responses (best-effort, non-blocking)
        self._tts_available = False
        self._tts_after_opening = False  # disable TTS until ElevenLabs key added
        try:
            from voice.tts import speak
            self._tts_speak = speak
            self._tts_available = True
        except Exception:
            pass

        # Pre-baked Xan audio (ships with app)
        _audio_dir = Path(__file__).parent.parent / "agents" / "xan" / "audio"
        self._audio_intro = _audio_dir / "intro.mp3"
        self._audio_name = _audio_dir / "name.mp3"
        self._audio_opening = _audio_dir / "opening.mp3"
        self._audio_proc = None  # current afplay subprocess
        self._service_step = 0  # deterministic service flow index

        self._ai_response_ready.connect(self._on_ai_response)
        self._avatar_result_ready.connect(self._on_avatar_result)
        self._avatar_error_ready.connect(self._on_avatar_error)
        self._video_progress_ready.connect(self._on_video_progress)
        self._video_done_ready.connect(self._on_video_done)

        # Brain frame animation - shared across pages
        self._brain_pixmaps = []  # list of 10 QPixmaps (scaled)
        self._brain_frame_idx = 0
        self._brain_labels = []   # QLabels that show the animated brain
        self._load_brain_frames()

        # Timer to advance brain frame (shared across all animated labels)
        self._brain_timer = QTimer(self)
        self._brain_timer.timeout.connect(self._advance_brain_frame)

        self._build_ui()

        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    def _load_brain_frames(self):
        """Load AI-generated brain frames, falling back to static overlay."""
        frames_dir = Path(__file__).parent / "icons" / "brain_frames"
        frames = []
        if frames_dir.is_dir():
            for i in range(10):
                fp = frames_dir / f"brain_{i:02d}.png"
                if fp.exists():
                    img = QImage(str(fp))
                    if not img.isNull():
                        frames.append(img)
                    else:
                        break
                else:
                    break
        if len(frames) != 10:
            # Fallback: use static brain_overlay for all 10 frames
            bp = Path(__file__).parent / "icons" / "brain_overlay.png"
            if bp.exists():
                img = QImage(str(bp))
                if not img.isNull():
                    frames = [img] * 10
        # Pre-scale to 80px for display
        for img in frames:
            scaled = img.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._brain_pixmaps.append(QPixmap.fromImage(scaled))

    def _advance_brain_frame(self):
        """Advance brain frame index and update all registered labels."""
        if not self._brain_pixmaps:
            return
        if self._brain_frame_idx < 9:
            self._brain_frame_idx += 1
        else:
            self._brain_timer.stop()
        for lbl in self._brain_labels:
            if lbl and not lbl.isHidden():
                lbl.setPixmap(self._brain_pixmaps[self._brain_frame_idx])

    def _make_brain_label(self) -> QLabel:
        """Create a QLabel showing the current brain frame, registered for animation."""
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        if self._brain_pixmaps:
            lbl.setPixmap(self._brain_pixmaps[self._brain_frame_idx])
        self._brain_labels.append(lbl)
        return lbl

    def _start_brain_animation(self, forward=True):
        """Start the brain frame sequence. forward=True goes 0→9, False goes 9→0."""
        self._brain_timer.stop()
        if forward:
            self._brain_frame_idx = 0
        else:
            self._brain_frame_idx = 9
        # Update all labels to the starting frame
        if self._brain_pixmaps:
            for lbl in self._brain_labels:
                if lbl:
                    lbl.setPixmap(self._brain_pixmaps[self._brain_frame_idx])
        # Reconnect with correct direction
        try:
            self._brain_timer.timeout.disconnect()
        except Exception:
            pass
        if forward:
            self._brain_timer.timeout.connect(self._advance_brain_frame)
        else:
            def _reverse():
                if not self._brain_pixmaps:
                    return
                if self._brain_frame_idx > 0:
                    self._brain_frame_idx -= 1
                else:
                    self._brain_timer.stop()
                for lbl in self._brain_labels:
                    if lbl and not lbl.isHidden():
                        lbl.setPixmap(self._brain_pixmaps[self._brain_frame_idx])
            self._brain_timer.timeout.connect(_reverse)
        self._brain_timer.start(800)  # 0.8s per frame, matching window.py

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._pages = QStackedWidget()
        root.addWidget(self._pages)

        self._build_page_intro()     # 0
        self._build_page_welcome()   # 1
        self._build_page_chat()      # 2
        self._build_page_creating()  # 3
        self._build_page_done()      # 4

    # ── Page 0: Cinematic Intro ──

    def _build_page_intro(self):
        page = QWidget()
        page.setStyleSheet("background: #000;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(60, 0, 60, 0)
        lay.addStretch(3)

        # Font - Bricolage Grotesque if available, else system
        font_name = "Bricolage Grotesque"
        test_font = QFont(font_name, 16)
        if test_font.family().lower() != font_name.lower():
            font_name = ""  # fall back to default
        self._font_name = font_name

        self._intro_lines = []

        def make_intro_label(text, size=16, opacity=0.0):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            f = font_name or "system-ui"
            lbl.setStyleSheet(
                f"color: rgba(255,255,255,{opacity}); font-size: {size}px; "
                f"font-family: '{f}'; background: transparent; line-height: 1.6;"
            )
            lay.addWidget(lbl)
            self._intro_lines.append(lbl)
            return lbl

        make_intro_label("In the beginning there was nothing", 18)
        lay.addSpacing(20)
        make_intro_label("and then...", 16)
        lay.addSpacing(30)
        self._intro_intel = make_intro_label("intelligence.", 26)
        lay.addSpacing(50)
        make_intro_label(
            "Use the last reserves of yours to complete this setup flow,\n"
            "and the future will unfold before your eyes.",
            14,
        )

        lay.addStretch(4)
        self._pages.addWidget(page)

        # Continue button - absolutely positioned so it doesn't push text
        self._intro_continue_btn = QPushButton("Continue", page)
        self._intro_continue_btn.setObjectName("continueBtn")
        self._intro_continue_btn.setCursor(Qt.PointingHandCursor)
        self._intro_continue_btn.setFixedSize(200, 44)
        self._intro_continue_btn.setVisible(False)
        self._intro_continue_btn.clicked.connect(self._finish_intro)
        # Positioned in resizeEvent via _position_intro_btn
        self._intro_btn_opacity = 0.0

        # Schedule the fade-in sequence
        self._intro_step = 0
        self._intro_timer = QTimer()
        self._intro_timer.timeout.connect(self._intro_tick)

    def _start_intro(self):
        """Begin the intro sequence."""
        self._intro_timer.stop()
        self._intro_step = 0
        self._intro_timer.start(80)  # tick every 80ms for smooth fades
        # Start brain frame animation (0→9 over the intro duration)
        self._start_brain_animation(forward=True)
        # Play intro voiceover
        self._play_audio(self._audio_intro)

    def _intro_tick(self):
        # Timeline (in ticks of 80ms):
        # Timeline (in ticks of 80ms) - ~1s extra gap for voice sync
        # 0-15    (0-1.2s):     fade in line 0 "In the beginning..."
        # 15-42   (1.2-3.4s):   pause (voice catches up)
        # 42-57   (3.4-4.6s):   fade in line 1 "and then..."
        # 57-82   (4.6-6.6s):   longer pause
        # 82-102  (6.6-8.2s):   fade in line 2 "intelligence."
        # 102-135 (8.2-10.8s):  pause
        # 135-155 (10.8-12.4s): fade in line 3 "Use the last reserves..."
        # 155-180 (12.4-14.4s): hold
        # 180-200 (14.4-16.0s): fade in continue button
        # 200+:                 wait for click
        t = self._intro_step
        self._intro_step += 1

        def fade_label(idx, progress):
            """Set opacity on a label (0.0 to 1.0)."""
            lbl = self._intro_lines[idx]
            opacity = min(1.0, max(0.0, progress))
            brightness = 0.95 if idx == 2 else 0.8
            new_style = re.sub(
                r'color:\s*rgba\([^)]+\)',
                f'color: rgba(255,255,255,{opacity * brightness})',
                lbl.styleSheet(),
                count=1,
            )
            lbl.setStyleSheet(new_style)

        if t <= 15:
            fade_label(0, t / 15.0)
        elif 42 <= t <= 57:
            fade_label(1, (t - 42) / 15.0)
        elif 82 <= t <= 102:
            fade_label(2, (t - 82) / 20.0)
        elif 135 <= t <= 155:
            fade_label(3, (t - 135) / 20.0)
        elif 180 <= t <= 200:
            # Fade in continue button (absolutely positioned)
            if not self._intro_continue_btn.isVisible():
                self._intro_continue_btn.setVisible(True)
                page = self._intro_continue_btn.parentWidget()
                bx = (page.width() - 200) // 2
                by = int(page.height() * 0.82)
                self._intro_continue_btn.move(bx, by)
            opacity = (t - 180) / 20.0
            f = self._font_name or "system-ui"
            self._intro_continue_btn.setStyleSheet(
                f"background: rgba(255,255,255,{int(opacity * 15)}); "
                f"color: rgba(255,255,255,{opacity * 0.9}); "
                f"border: 1px solid rgba(255,255,255,{opacity * 0.2}); "
                f"border-radius: 22px; font-size: 15px; "
                f"font-family: '{f}';"
            )
        elif t == 201:
            self._intro_timer.stop()

    def _finish_intro(self):
        """Transition from intro to welcome page."""
        self._pages.setCurrentIndex(1)
        self._name_input.setFocus()
        self._play_audio(self._audio_name)

    # ── Page 1: Welcome + User Name ──

    def _build_page_welcome(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(50, 0, 50, 40)
        lay.addStretch(3)

        if self._brain_pixmaps:
            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setPixmap(self._brain_pixmaps[0])  # frame 0 - pristine brain
            lay.addWidget(icon_label)
            lay.addSpacing(16)

        lay.addWidget(_label("Atrophy", 22, 0.9, align=Qt.AlignCenter))
        lay.addSpacing(8)
        lay.addWidget(_label("Offload your mind.", 13, 0.4, align=Qt.AlignCenter))
        lay.addSpacing(40)
        lay.addWidget(_label("What is your name, human?", 15, 0.7, align=Qt.AlignCenter))
        lay.addSpacing(12)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Your name")
        self._name_input.setAlignment(Qt.AlignCenter)
        self._name_input.setMaxLength(40)
        lay.addLayout(_centred(self._name_input, 300))
        lay.addSpacing(24)

        self._welcome_btn = QPushButton("Continue")
        self._welcome_btn.setObjectName("continueBtn")
        self._welcome_btn.setCursor(Qt.PointingHandCursor)
        self._welcome_btn.setEnabled(False)
        lay.addLayout(_centred(self._welcome_btn, 200))

        lay.addStretch(4)

        self._name_input.textChanged.connect(
            lambda t: self._welcome_btn.setEnabled(bool(t.strip()))
        )
        self._name_input.returnPressed.connect(self._finish_welcome)
        self._welcome_btn.clicked.connect(self._finish_welcome)

        self._pages.addWidget(page)

    def _finish_welcome(self):
        name = self._name_input.text().strip()
        if not name:
            return
        self._user_name = name
        from config import save_user_config
        save_user_config({"user_name": name})
        self._pages.setCurrentIndex(2)
        self._start_chat()

    # ── Page 2: Conversational Agent Creation ──

    def _build_page_chat(self):
        page = QWidget()
        page.setStyleSheet("background: rgb(14, 14, 18);")

        # ── Video background (local Xan ambient loop) ──
        self._video_bg = None
        self._local_player = None
        self._local_surface = None
        self._local_frame = None

        local_loop = self._find_xan_loop()
        if local_loop:
            self._setup_local_video(page, local_loop)

        # ── Chat overlay (on top of video) ──
        if self._video_bg:
            self._chat_overlay = _ScrimOverlay(
                page, opacity=180,
                frame_source=lambda: self._local_frame,
            )
        else:
            self._chat_overlay = QWidget(page)
            self._chat_overlay.setStyleSheet("background: rgb(14, 14, 18);")
        lay = QVBoxLayout(self._chat_overlay)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Resize video + overlay to fill the page
        page.installEventFilter(self)

        # Message area - matches main window transcript style
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 0px; }"
        )

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background: transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(24, 16, 24, 16)
        self._msg_layout.setSpacing(6)
        self._msg_layout.insertStretch(0, 1)  # stretch at top pushes messages down
        self._scroll.setWidget(self._msg_container)

        # Wrap scroll in a container so we can paint a fade gradient on top
        scroll_wrapper = QWidget()
        scroll_wrapper.setStyleSheet("background: transparent;")
        wrapper_lay = QVBoxLayout(scroll_wrapper)
        wrapper_lay.setContentsMargins(0, 0, 0, 0)
        wrapper_lay.setSpacing(0)
        wrapper_lay.addWidget(self._scroll)

        # Fade overlay - gradient from opaque at top to transparent halfway down
        self._fade_overlay = _FadeOverlay(scroll_wrapper)
        self._fade_overlay.raise_()

        lay.addWidget(scroll_wrapper, 1)

        # ── Input bar - matches main window InputBar style ──
        self._input_frame = QWidget()
        self._input_frame.setMinimumHeight(72)
        self._input_frame.setStyleSheet("background: transparent;")
        input_outer = QVBoxLayout(self._input_frame)
        input_outer.setContentsMargins(24, 0, 24, 16)
        input_outer.setSpacing(0)

        # Secure input label (hidden by default)
        self._secure_label_widget = QLabel("Secure input")
        self._secure_label_widget.setStyleSheet(
            "color: rgba(230, 160, 60, 0.9); font-size: 11px; font-weight: bold; "
            "padding: 8px 0 4px 4px; background: transparent;"
        )
        self._secure_label_widget.setVisible(False)
        input_outer.addWidget(self._secure_label_widget)

        # Input container - rounded bar with painted arrow (matches InputBar)
        self._chat_bar = _ChatBar()
        self._chat_bar.setFixedHeight(48)

        self._chat_input = QLineEdit(self._chat_bar)
        self._chat_input.setPlaceholderText("Message...")
        font_name = "Bricolage Grotesque"
        test_font = QFont(font_name, 14)
        if test_font.family().lower() != font_name.lower():
            font_name = ""
        if font_name:
            self._chat_input.setFont(QFont(font_name, 14))
        self._chat_input_style_normal = (
            "QLineEdit { background: transparent; color: rgba(255,255,255,0.9); "
            "border: none; padding-left: 20px; padding-right: 54px; font-size: 14px; "
            "selection-background-color: rgba(255,255,255,0.2); }"
        )
        self._chat_input_style_secure = (
            "QLineEdit { background: transparent; color: rgba(255,255,255,0.9); "
            "border: none; padding-left: 20px; padding-right: 54px; font-size: 14px; "
            "selection-background-color: rgba(230,160,60,0.2); }"
        )
        self._chat_input.setStyleSheet(self._chat_input_style_normal)

        input_outer.addWidget(self._chat_bar)

        # Send button - invisible, triggered by pressing Enter
        self._send_btn = QPushButton("")
        self._send_btn.setFixedSize(0, 0)
        self._send_btn.setVisible(False)

        # Secure mode buttons (hidden by default)
        secure_row = QHBoxLayout()
        secure_row.setContentsMargins(0, 8, 0, 0)
        secure_row.setSpacing(8)
        secure_row.addStretch()

        self._submit_secure_btn = QPushButton("Submit")
        self._submit_secure_btn.setCursor(Qt.PointingHandCursor)
        self._submit_secure_btn.setStyleSheet(
            "QPushButton { background: rgba(230,160,60,0.3); color: rgba(255,255,255,0.9); "
            "border: 1px solid rgba(230,160,60,0.4); border-radius: 8px; "
            "padding: 8px 20px; font-size: 13px; }"
            "QPushButton:hover { background: rgba(230,160,60,0.45); }"
        )
        self._submit_secure_btn.setVisible(False)
        secure_row.addWidget(self._submit_secure_btn)

        self._skip_secure_btn = QPushButton("Skip")
        self._skip_secure_btn.setCursor(Qt.PointingHandCursor)
        self._skip_secure_btn.setStyleSheet(
            "QPushButton { background: transparent; color: rgba(230,160,60,0.6); "
            "border: 1px solid rgba(230,160,60,0.2); border-radius: 8px; "
            "padding: 8px 14px; font-size: 13px; }"
            "QPushButton:hover { color: rgba(230,160,60,0.9); border: 1px solid rgba(230,160,60,0.4); }"
        )
        self._skip_secure_btn.setVisible(False)
        secure_row.addWidget(self._skip_secure_btn)
        secure_row.addStretch()

        input_outer.addLayout(secure_row)
        lay.addWidget(self._input_frame)

        # Connections
        self._chat_input.returnPressed.connect(self._on_input_submit)
        self._send_btn.clicked.connect(self._on_input_submit)
        self._submit_secure_btn.clicked.connect(self._on_secure_submit)
        self._skip_secure_btn.clicked.connect(self._on_secure_skip)

        self._pages.addWidget(page)

    # ── Secure input mode ──

    def _enter_secure_mode(self, key: str, label: str):
        """Switch the input bar to secure input mode."""
        self._secure_mode = True
        self._secure_key = key
        self._secure_label = label

        self._secure_label_widget.setText(f"Secure input - {label}")
        self._secure_label_widget.setVisible(True)

        self._chat_input.clear()
        self._chat_input.setPlaceholderText(f"Paste your {label} here...")
        self._chat_input.setEchoMode(QLineEdit.Password)
        self._chat_input.setStyleSheet(self._chat_input_style_secure)
        self._chat_input.setEnabled(True)
        self._chat_input.setFocus()

        self._send_btn.setVisible(False)
        self._submit_secure_btn.setVisible(True)
        self._skip_secure_btn.setVisible(True)

    def _exit_secure_mode(self):
        """Switch back to normal chat mode."""
        self._secure_mode = False
        self._secure_key = None

        self._secure_label_widget.setVisible(False)

        self._chat_input.clear()
        self._chat_input.setPlaceholderText("Type your response...")
        self._chat_input.setEchoMode(QLineEdit.Normal)
        self._chat_input.setStyleSheet(self._chat_input_style_normal)

        self._send_btn.setVisible(True)
        self._submit_secure_btn.setVisible(False)
        self._skip_secure_btn.setVisible(False)

    def _on_secure_submit(self):
        """User submitted a secure value."""
        value = self._chat_input.text().strip()
        if not value:
            return
        key = self._secure_key
        if key and key in _ALLOWED_SECURE_KEYS:
            _save_env_var(key, value)
        self._exit_secure_mode()
        self._chat_messages.append({
            "role": "user",
            "content": f"(SECURE_INPUT: {key} saved)",
        })
        self._add_message("system", f"{self._secure_label or key} saved.")
        # If ElevenLabs was just saved, re-enable TTS and confirm
        if key == "ELEVENLABS_API_KEY":
            self._tts_after_opening = False
            _audio_dir = Path(__file__).parent.parent / "agents" / "xan" / "audio"
            self._play_audio(_audio_dir / "elevenlabs_saved.mp3")
        # Advance: service flow or AI-driven
        if self._service_step < len(self._SERVICE_PROMPTS):
            # Telegram needs chat ID after token
            if key == "TELEGRAM_BOT_TOKEN":
                self._add_message("assistant",
                    "Now send any message to your bot, then visit:\n"
                    "https://api.telegram.org/bot<TOKEN>/getUpdates\n"
                    "Your chat ID is in the 'chat' object. Type it below."
                )
                self._enter_secure_mode("TELEGRAM_CHAT_ID", "Telegram Chat ID")
                return
            self._service_step += 1
            QTimer.singleShot(500, self._next_service_prompt)
        else:
            self._send_ai_message()

    def _on_secure_skip(self):
        """User skipped the secure input."""
        key = self._secure_key
        self._exit_secure_mode()
        self._chat_messages.append({
            "role": "user",
            "content": f"(SECURE_INPUT: {key} skipped)",
        })
        self._add_message("system", f"{self._secure_label or key} skipped.")
        if self._service_step < len(self._SERVICE_PROMPTS):
            self._service_step += 1
            QTimer.singleShot(500, self._next_service_prompt)
        else:
            self._send_ai_message()

    def _on_google_oauth_done(self, result: str):
        """Handle Google OAuth flow completion."""
        if result == "complete":
            self._add_message("system", "Google authorised - Gmail and Calendar connected.")
            self._chat_messages.append({
                "role": "user",
                "content": "(GOOGLE_OAUTH: complete - Gmail and Calendar are now connected)",
            })
        else:
            self._add_message("system", f"Google auth {result}. You can retry later: python scripts/google_auth.py")
            self._chat_messages.append({
                "role": "user",
                "content": f"(GOOGLE_OAUTH: {result})",
            })
        if self._service_step < len(self._SERVICE_PROMPTS):
            self._service_step += 1
            QTimer.singleShot(500, self._next_service_prompt)
        else:
            self._send_ai_message()

    def _on_input_submit(self):
        """Handle Enter/Send - routes to chat or secure handler."""
        if self._secure_mode:
            self._on_secure_submit()
        else:
            self._send_message()

    # ── Chat messages ──

    def _add_message(self, role: str, text: str):
        """Add a message to the chat area - matches main window transcript style."""
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.PlainText)

        # Font
        font_name = "Bricolage Grotesque"
        test_font = QFont(font_name, 14)
        if test_font.family().lower() != font_name.lower():
            font_name = ""
        if font_name:
            msg.setFont(QFont(font_name, 14))

        if role == "assistant":
            msg.setStyleSheet(
                "QLabel { background: transparent; color: rgba(255, 255, 255, 0.86); "
                "font-size: 14px; padding: 2px 0; }"
            )
        elif role == "system":
            msg.setStyleSheet(
                "QLabel { background: transparent; color: rgba(230,160,60,0.6); "
                "font-size: 12px; font-style: italic; padding: 2px 0; }"
            )
        else:
            msg.setStyleSheet(
                "QLabel { background: transparent; color: rgba(180, 180, 180, 0.86); "
                "font-size: 14px; padding: 2px 0; }"
            )

        # Add spacing between message pairs
        if self._msg_layout.count() > 1 and role == "user":
            spacer = QWidget()
            spacer.setFixedHeight(16)
            spacer.setStyleSheet("background: transparent;")
            self._msg_layout.addWidget(spacer)

        self._msg_layout.addWidget(msg)

        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _add_thinking_indicator(self):
        self._thinking_label = QLabel()
        # Use brain frame 0 as a small pulsing icon
        if self._brain_pixmaps:
            icon = self._brain_pixmaps[0].scaled(
                20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._thinking_label.setPixmap(icon)
        else:
            self._thinking_label.setText("...")
        self._thinking_label.setFixedHeight(28)
        self._thinking_label.setStyleSheet(
            "QLabel { background: transparent; padding: 4px 0px; }"
        )
        self._msg_layout.addWidget(self._thinking_label)
        # Start pulse animation
        self._thinking_opacity = 0.3
        self._thinking_fading_in = True
        self._thinking_timer = QTimer()
        self._thinking_timer.timeout.connect(self._pulse_thinking)
        self._thinking_timer.start(50)

    def _pulse_thinking(self):
        if not self._thinking_label:
            return
        if self._thinking_fading_in:
            self._thinking_opacity += 0.03
            if self._thinking_opacity >= 0.8:
                self._thinking_fading_in = False
        else:
            self._thinking_opacity -= 0.03
            if self._thinking_opacity <= 0.2:
                self._thinking_fading_in = True
        op = max(0.0, min(1.0, self._thinking_opacity))
        self._thinking_label.setStyleSheet(
            f"QLabel {{ background: transparent; padding: 4px 0px; "
            f"opacity: {op}; }}"
        )
        # QLabel doesn't support opacity in stylesheet - use graphicsEffect
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        if not self._thinking_label.graphicsEffect():
            effect = QGraphicsOpacityEffect(self._thinking_label)
            self._thinking_label.setGraphicsEffect(effect)
        self._thinking_label.graphicsEffect().setOpacity(op)

    def _remove_thinking_indicator(self):
        if hasattr(self, '_thinking_timer') and self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None
        if hasattr(self, '_thinking_label') and self._thinking_label:
            self._thinking_label.setParent(None)
            self._thinking_label.deleteLater()
            self._thinking_label = None

    _OPENING_TEXT = (
        "I'm Xan. I ship with the system - protector, first contact, always on.\n\n"
        "You already have me. But the real power is in building something yours - "
        "a companion with its own edges, its own voice, someone shaped by you "
        "for a specific purpose.\n\n"
        "This is the last you'll hear of my voice until you've added your "
        "ElevenLabs API key, which I will ask you to do in a moment.\n\n"
        "First, we need to set up your system. Let's get started."
    )

    def _start_chat(self):
        self._chat_input.setFocus()
        # Start video background
        self._start_local_video()
        # Play scripted opening - no LLM needed for first message
        self._play_audio(self._audio_opening)
        self._add_message("assistant", self._OPENING_TEXT)
        # Seed conversation history so LLM has context
        self._chat_messages.append({
            "role": "user",
            "content": "(Session starting. Ask your opening question.)",
        })
        self._chat_messages.append({
            "role": "assistant",
            "content": self._OPENING_TEXT,
        })
        # Bridge message so LLM sees user is ready for setup
        self._chat_messages.append({
            "role": "user",
            "content": "(User is ready. Begin the setup flow.)",
        })
        # Disable TTS after opening - voice returns when ElevenLabs key added
        self._tts_after_opening = True
        # After a brief pause, start deterministic service setup
        self._service_step = 0
        QTimer.singleShot(2000, self._next_service_prompt)

    # ── Deterministic service setup ──

    _SERVICE_PROMPTS = [
        {
            "key": "ELEVENLABS_API_KEY",
            "title": "Voice - ElevenLabs",
            "description": (
                "Gives your companion a real voice - speaks out loud.\n"
                "$5/month minimum. Hundreds of voices, or clone your own."
            ),
            "label": "ElevenLabs API Key",
            "type": "secure",
        },
        {
            "key": "FAL_KEY",
            "title": "Visual Presence - Fal.ai",
            "description": (
                "Handles image and video generation. Pay-as-you-go:\n"
                "avatar images ~$0.01 each, ambient video clips ~$0.30 each."
            ),
            "label": "Fal API Key",
            "type": "secure",
        },
        {
            "key": "TELEGRAM",
            "title": "Messaging - Telegram",
            "description": (
                "Your companion can message you directly - check-ins,\n"
                "briefs, reminders. Free."
            ),
            "type": "telegram",
        },
        {
            "key": "GOOGLE",
            "title": "Email & Calendar - Google",
            "description": (
                "Read email, check your calendar, send emails, create events.\n"
                "Free - uses your own Google account."
            ),
            "type": "google",
        },
    ]

    def _next_service_prompt(self):
        """Show the next service setup question, or transition to agent building."""
        if self._service_step >= len(self._SERVICE_PROMPTS):
            # All services offered - now start the AI-driven agent building
            _audio_dir = Path(__file__).parent.parent / "agents" / "xan" / "audio"
            self._play_audio(_audio_dir / "service_complete.mp3")
            self._add_message("assistant", "System configured. Now… let's build your companion.")
            self._chat_messages.append({
                "role": "user",
                "content": "(Services configured. Begin building the companion.)",
            })
            self._send_ai_message()
            return

        svc = self._SERVICE_PROMPTS[self._service_step]
        self._show_service_card(svc)

    def _show_service_card(self, svc: dict):
        """Show an inline yes/no card for a service."""
        f = self._font_name or "system-ui"
        card = QWidget()
        card.setStyleSheet("background: transparent;")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(0, 8, 0, 8)
        card_lay.setSpacing(8)

        # Title
        title = QLabel(svc["title"])
        title.setStyleSheet(
            f"color: rgba(255,255,255,0.9); font-size: 15px; font-weight: bold; "
            f"font-family: '{f}'; background: transparent;"
        )
        card_lay.addWidget(title)

        # Description
        desc = QLabel(svc["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: rgba(255,255,255,0.55); font-size: 13px; "
            f"font-family: '{f}'; background: transparent;"
        )
        card_lay.addWidget(desc)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        btn_style = (
            f"QPushButton {{ background: rgba(255,255,255,0.08); "
            f"color: rgba(255,255,255,0.8); border: 1px solid rgba(255,255,255,0.15); "
            f"border-radius: 16px; padding: 8px 24px; font-size: 13px; "
            f"font-family: '{f}'; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.14); }}"
        )

        yes_btn = QPushButton("Yes")
        yes_btn.setCursor(Qt.PointingHandCursor)
        yes_btn.setStyleSheet(btn_style)
        yes_btn.clicked.connect(lambda: self._on_service_yes(svc, card))

        skip_btn = QPushButton("Skip")
        skip_btn.setCursor(Qt.PointingHandCursor)
        skip_btn.setStyleSheet(btn_style)
        skip_btn.clicked.connect(lambda: self._on_service_skip(svc, card))

        btn_row.addWidget(yes_btn)
        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        card_lay.addLayout(btn_row)

        self._msg_layout.addWidget(card)
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _on_service_yes(self, svc: dict, card: QWidget):
        """User said yes to a service."""
        # Disable buttons
        for btn in card.findChildren(QPushButton):
            btn.setEnabled(False)
            btn.setStyleSheet(btn.styleSheet().replace("0.8", "0.3"))

        svc_type = svc.get("type", "secure")
        if svc_type == "secure":
            self._enter_secure_mode(svc["key"], svc["label"])
        elif svc_type == "telegram":
            self._add_message("assistant",
                "Setup:\n"
                "1. Telegram → search @BotFather → /newbot\n"
                "2. Pick a name and username (must end in 'bot')\n"
                "3. Paste the token below"
            )
            self._enter_secure_mode("TELEGRAM_BOT_TOKEN", "Telegram Bot Token")
        elif svc_type == "google":
            self._start_google_auth()

    def _on_service_skip(self, svc: dict, card: QWidget):
        """User skipped a service."""
        for btn in card.findChildren(QPushButton):
            btn.setEnabled(False)
            btn.setStyleSheet(btn.styleSheet().replace("0.8", "0.3"))
        self._add_message("system", f"{svc['title']} skipped.")
        self._chat_messages.append({
            "role": "user",
            "content": f"(SERVICE: {svc['key']} skipped)",
        })
        # Special message when ElevenLabs is skipped
        if svc.get("key") == "ELEVENLABS_API_KEY":
            _audio_dir = Path(__file__).parent.parent / "agents" / "xan" / "audio"
            farewell = _audio_dir / "voice_farewell.mp3"
            self._play_audio(farewell)
            self._add_message("assistant",
                "This is the last you'll hear of my voice. If you change your "
                "mind later, you can add your API key in Settings - it'll appear "
                "after this setup flow."
            )
        self._service_step += 1
        QTimer.singleShot(500, self._next_service_prompt)

    def _play_audio(self, path: Path):
        """Play a pre-baked audio file via afplay (non-blocking)."""
        if not path.exists():
            return
        import subprocess
        # Kill any currently playing audio
        if self._audio_proc and self._audio_proc.poll() is None:
            self._audio_proc.kill()
        self._audio_proc = subprocess.Popen(
            ["afplay", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _speak(self, text: str):
        """Speak text via TTS in a background thread (best-effort).

        Disabled after the opening message until ElevenLabs key is added.
        """
        if self._tts_after_opening:
            return  # voice disabled until key added
        if not self._tts_available:
            return
        clean = re.sub(r'```[\s\S]*?```', '', text)
        clean = re.sub(r'`[^`]+`', '', clean)
        clean = re.sub(r'\[.*?\]', '', clean)
        clean = re.sub(r'\*+', '', clean)
        clean = re.sub(r'#+\s*', '', clean)
        clean = clean.strip()
        if not clean:
            return

        def _tts_worker():
            try:
                self._tts_speak(clean)
            except Exception:
                pass
        thread = threading.Thread(target=_tts_worker, daemon=True)
        thread.start()

    def _send_message(self):
        text = self._chat_input.text().strip()
        if not text or self._waiting_for_ai:
            return
        self._chat_input.clear()
        self._chat_messages.append({"role": "user", "content": text})
        self._add_message("user", text)
        self._send_ai_message()

    def _send_ai_message(self, first=False):
        self._waiting_for_ai = True
        self._send_btn.setEnabled(False)
        self._chat_input.setEnabled(False)
        self._add_thinking_indicator()

        def _worker():
            try:
                from core.inference import run_inference_oneshot
                system = _AGENT_CREATION_SYSTEM.format(user_name=self._user_name or "User")

                if first:
                    messages = [{"role": "user", "content": "(Session starting. Ask your opening question.)"}]
                else:
                    messages = self._chat_messages.copy()

                response = run_inference_oneshot(
                    messages, system,
                    model="claude-sonnet-4-6",
                    effort="medium",
                )
                self._ai_response_ready.emit(response)
            except Exception as e:
                self._ai_response_ready.emit(f"[Error: {e}]")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_ai_response(self, response: str):
        self._remove_thinking_indicator()
        self._waiting_for_ai = False
        self._send_btn.setEnabled(True)
        self._chat_input.setEnabled(True)
        self._chat_input.setFocus()

        # Strip all tool blocks for display
        display_text = response
        for pattern in [
            r'```secure_input\s*\{[\s\S]*?\}\s*```',
            r'```generate_avatar\s*\{[\s\S]*?\}\s*```',
            r'```generate_videos\s*\{[\s\S]*?\}\s*```',
            r'```google_auth\s*\{[\s\S]*?\}\s*```',
            r'```json\s*\{[\s\S]*?\}\s*```',
        ]:
            display_text = re.sub(pattern, '', display_text)
        display_text = display_text.strip()

        if display_text:
            self._chat_messages.append({"role": "assistant", "content": display_text})
            self._add_message("assistant", display_text)
            # Speak the response via TTS (non-blocking)
            self._speak(display_text)

        # Check for tool calls in priority order

        secure_req = self._extract_secure_input(response)
        if secure_req:
            self._enter_secure_mode(secure_req["key"], secure_req["label"])
            return

        google_req = self._extract_google_auth(response)
        if google_req is not None:
            self._start_google_auth()
            return

        avatar_req = self._extract_generate_avatar(response)
        if avatar_req:
            self._start_avatar_generation(
                avatar_req.get("prompt", ""),
                avatar_req.get("negative_prompt", ""),
            )
            return

        video_req = self._extract_generate_videos(response)
        if video_req:
            self._start_video_generation(
                video_req.get("count", 4),
                video_req.get("prompt_style", ""),
            )
            return

        config = self._extract_config(response)
        if config:
            if config.get("skip"):
                self._do_skip()
            else:
                self._pending_config = config
                QTimer.singleShot(1500, self._do_create)

    def _extract_secure_input(self, text: str) -> dict | None:
        """Extract a SECURE_INPUT request from the AI's response."""
        match = re.search(r'```secure_input\s*(\{[\s\S]*?\})\s*```', text)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
            key = data.get("key", "")
            label = data.get("label", key)
            if key in _ALLOWED_SECURE_KEYS:
                return {"key": key, "label": label}
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _extract_config(self, text: str) -> dict | None:
        """Extract AGENT_CONFIG JSON from the AI's response."""
        match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', text)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
            if "AGENT_CONFIG" in data:
                return data["AGENT_CONFIG"]
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _extract_google_auth(self, text: str) -> dict | None:
        """Extract google_auth request with credentials file path."""
        match = re.search(r'```google_auth\s*(\{[\s\S]*?\})\s*```', text)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _start_google_auth(self, _args: str = ""):
        """Open browser for Google OAuth consent. Credentials are bundled."""
        self._add_message("system", "Opening browser for Google authorisation...")

        # Connect signal once
        if not hasattr(self, '_google_oauth_connected'):
            self._google_oauth_done.connect(self._on_google_oauth_done)
            self._google_oauth_connected = True

        def _oauth_worker():
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
                from google_auth import run_oauth_flow
                success = run_oauth_flow()
                self._google_oauth_done.emit("complete" if success else "failed")
            except Exception as e:
                self._google_oauth_done.emit(f"error: {e}")
            finally:
                if str(Path(__file__).parent.parent / "scripts") in sys.path:
                    sys.path.remove(str(Path(__file__).parent.parent / "scripts"))

        thread = threading.Thread(target=_oauth_worker, daemon=True)
        thread.start()

    def _extract_generate_avatar(self, text: str) -> dict | None:
        """Extract GENERATE_AVATAR request."""
        match = re.search(r'```generate_avatar\s*(\{[\s\S]*?\})\s*```', text)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _extract_generate_videos(self, text: str) -> dict | None:
        """Extract GENERATE_VIDEOS request."""
        match = re.search(r'```generate_videos\s*(\{[\s\S]*?\})\s*```', text)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    # ── Avatar generation ──

    def _start_avatar_generation(self, prompt: str, negative_prompt: str = ""):
        """Generate 4 avatar candidates via Fal.ai in background."""
        self._add_message("system", "Generating 4 avatar candidates...")

        def _worker():
            try:
                import fal_client
                candidates = []
                for i in range(4):
                    result = fal_client.subscribe(
                        "fal-ai/flux-general",
                        arguments={
                            "prompt": prompt,
                            "negative_prompt": negative_prompt or (
                                "blurry, distorted, low quality, text, watermark, "
                                "signature, deformed, ugly, duplicate"
                            ),
                            "num_inference_steps": 50,
                            "guidance_scale": 3.5,
                            "image_size": {"width": 768, "height": 1024},
                            "output_format": "png",
                            "seed": None,  # random each time
                        },
                    )
                    images = result.get("images", [])
                    if images:
                        # Download to temp file
                        import httpx
                        import tempfile
                        url = images[0]["url"]
                        resp = httpx.get(url, timeout=60)
                        tmp = tempfile.NamedTemporaryFile(
                            suffix=f"_candidate_{i}.png", delete=False
                        )
                        tmp.write(resp.content)
                        tmp.close()
                        candidates.append(tmp.name)
                self._avatar_result_ready.emit(candidates)
            except Exception as e:
                self._avatar_error_ready.emit(str(e))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_avatar_result(self, candidates: list):
        """Show avatar candidates in chat with pick buttons."""
        self._avatar_candidates = candidates
        if not candidates:
            self._add_message("system", "No candidates generated. Skipping avatar.")
            self._chat_messages.append({"role": "user", "content": "(AVATAR: skipped)"})
            self._send_ai_message()
            return

        # Create a widget with the candidate images in a grid
        grid_widget = QWidget()
        grid_layout = QVBoxLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)

        # Images in a 2x2 grid
        for row_start in range(0, len(candidates), 2):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            for i in range(row_start, min(row_start + 2, len(candidates))):
                frame = QWidget()
                frame_lay = QVBoxLayout(frame)
                frame_lay.setContentsMargins(4, 4, 4, 4)
                frame_lay.setSpacing(4)

                img_label = QLabel()
                pixmap = QPixmap(candidates[i])
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        250, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    img_label.setPixmap(scaled)
                img_label.setAlignment(Qt.AlignCenter)
                img_label.setStyleSheet(
                    "QLabel { background: rgba(255,255,255,0.03); "
                    "border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; "
                    "padding: 4px; }"
                )
                frame_lay.addWidget(img_label)

                pick_btn = QPushButton(f"Pick #{i + 1}")
                pick_btn.setCursor(Qt.PointingHandCursor)
                pick_btn.setStyleSheet(
                    "QPushButton { background: rgba(100,140,255,0.2); "
                    "color: rgba(255,255,255,0.8); border: 1px solid rgba(100,140,255,0.3); "
                    "border-radius: 6px; padding: 6px 12px; font-size: 12px; }"
                    "QPushButton:hover { background: rgba(100,140,255,0.35); }"
                )
                pick_btn.clicked.connect(lambda checked, idx=i: self._pick_avatar(idx))
                frame_lay.addWidget(pick_btn)

                row_layout.addWidget(frame)

            if len(candidates) - row_start == 1:
                row_layout.addStretch()
            grid_layout.addLayout(row_layout)

        # Skip button
        skip_row = QHBoxLayout()
        skip_row.addStretch()
        skip_btn = QPushButton("Skip - no avatar")
        skip_btn.setCursor(Qt.PointingHandCursor)
        skip_btn.setStyleSheet(
            "QPushButton { background: transparent; color: rgba(255,255,255,0.3); "
            "border: none; font-size: 12px; padding: 6px; }"
            "QPushButton:hover { color: rgba(255,255,255,0.5); }"
        )
        skip_btn.clicked.connect(self._skip_avatar)
        skip_row.addWidget(skip_btn)
        skip_row.addStretch()
        grid_layout.addLayout(skip_row)

        grid_widget.setStyleSheet("background: transparent;")
        self._msg_layout.addWidget(grid_widget)
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _on_avatar_error(self, error: str):
        self._add_message("system", f"Avatar generation failed: {error}")
        self._chat_messages.append({"role": "user", "content": "(AVATAR: skipped)"})
        self._send_ai_message()

    def _pick_avatar(self, index: int):
        """User picked an avatar candidate."""
        if index < len(self._avatar_candidates):
            self._selected_avatar = self._avatar_candidates[index]
        self._add_message("system", f"Avatar #{index + 1} selected.")
        self._chat_messages.append({
            "role": "user",
            "content": f"(AVATAR: selected candidate {index + 1})",
        })
        self._send_ai_message()

    def _skip_avatar(self):
        self._add_message("system", "Avatar skipped.")
        self._chat_messages.append({"role": "user", "content": "(AVATAR: skipped)"})
        self._send_ai_message()

    # ── Video generation (background) ──

    def _start_video_generation(self, count: int, prompt_style: str):
        """Generate ambient video loops in background with progress."""
        if not self._selected_avatar:
            self._chat_messages.append({
                "role": "user",
                "content": "(VIDEOS: skipped - no avatar selected)",
            })
            self._send_ai_message()
            return

        self._chat_messages.append({
            "role": "user",
            "content": f"(VIDEOS: generating {count} clips in background)",
        })

        # Add progress bar to chat
        self._add_video_progress(count)

        # Continue the conversation - don't block
        self._send_ai_message()

        # Run generation in background
        def _worker():
            try:
                import fal_client
                import httpx
                import tempfile
                import subprocess as sp

                avatar_url = fal_client.upload_file(Path(self._selected_avatar))
                generated = 0

                for i in range(count):
                    try:
                        # Generate clip pair (neutral → expression → neutral)
                        # Clip A: start from avatar
                        result_a = fal_client.subscribe(
                            "fal-ai/kling-video/v3/pro/image-to-video",
                            arguments={
                                "prompt": prompt_style or "Subtle natural motion, gentle breathing, ambient movement",
                                "start_image_url": avatar_url,
                                "duration": 5,
                                "aspect_ratio": "9:16",
                                "negative_prompt": (
                                    "blur, distortion, morphing, deformation, "
                                    "fast motion, sudden changes, text, watermark"
                                ),
                                "cfg_scale": 0.5,
                                "generate_audio": False,
                            },
                        )
                        video_a_url = result_a.get("video", {}).get("url", "")
                        if not video_a_url:
                            continue

                        # Download clip A
                        tmp_a = tempfile.NamedTemporaryFile(
                            suffix=f"_clip_{i}_a.mp4", delete=False
                        )
                        resp = httpx.get(video_a_url, timeout=120)
                        tmp_a.write(resp.content)
                        tmp_a.close()

                        # Extract last frame from clip A
                        last_frame = tempfile.NamedTemporaryFile(
                            suffix=f"_frame_{i}.jpg", delete=False
                        )
                        last_frame.close()
                        sp.run([
                            "ffmpeg", "-y", "-sseof", "-0.1",
                            "-i", tmp_a.name,
                            "-vframes", "1", "-q:v", "2",
                            last_frame.name,
                        ], capture_output=True, timeout=30)

                        # Upload last frame
                        frame_url = fal_client.upload_file(Path(last_frame.name))

                        # Clip B: return to neutral
                        result_b = fal_client.subscribe(
                            "fal-ai/kling-video/v3/pro/image-to-video",
                            arguments={
                                "prompt": "Returning to neutral, settling, gentle",
                                "start_image_url": frame_url,
                                "end_image_url": avatar_url,
                                "duration": 5,
                                "aspect_ratio": "9:16",
                                "negative_prompt": (
                                    "blur, distortion, morphing, deformation, "
                                    "fast motion, sudden changes"
                                ),
                                "cfg_scale": 0.5,
                                "generate_audio": False,
                            },
                        )
                        video_b_url = result_b.get("video", {}).get("url", "")
                        if not video_b_url:
                            continue

                        tmp_b = tempfile.NamedTemporaryFile(
                            suffix=f"_clip_{i}_b.mp4", delete=False
                        )
                        resp = httpx.get(video_b_url, timeout=120)
                        tmp_b.write(resp.content)
                        tmp_b.close()

                        # Crossfade stitch
                        output = tempfile.NamedTemporaryFile(
                            suffix=f"_loop_{i:02d}.mp4", delete=False
                        )
                        output.close()
                        sp.run([
                            "ffmpeg", "-y",
                            "-i", tmp_a.name, "-i", tmp_b.name,
                            "-filter_complex",
                            "[0:v][1:v]xfade=transition=fade:duration=0.15:offset=4.85[v]",
                            "-map", "[v]",
                            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                            output.name,
                        ], capture_output=True, timeout=120)

                        self._video_loop_paths.append(output.name)
                        generated += 1
                        self._video_progress_ready.emit(generated, count)

                    except Exception:
                        # Individual clip failure - continue with remaining
                        self._video_progress_ready.emit(generated, count)
                        continue

                self._video_done_ready.emit(generated)

            except Exception as e:
                self._video_done_ready.emit(0)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _add_video_progress(self, total: int):
        """Add a video generation progress bar to the chat."""
        from PyQt5.QtWidgets import QProgressBar

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        title = QLabel(f"Generating {total} video clips...")
        title.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 12px; font-style: italic;"
        )
        lay.addWidget(title)

        progress = QProgressBar()
        progress.setRange(0, total)
        progress.setValue(0)
        progress.setFixedHeight(6)
        progress.setTextVisible(False)
        progress.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.06); border: none; "
            "border-radius: 3px; }"
            "QProgressBar::chunk { background: rgba(100,140,255,0.5); "
            "border-radius: 3px; }"
        )
        lay.addWidget(progress)

        self._video_progress_widget = {"container": container, "bar": progress, "label": title}

        self._msg_layout.addWidget(container)
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _on_video_progress(self, current: int, total: int):
        if self._video_progress_widget:
            self._video_progress_widget["bar"].setValue(current)
            self._video_progress_widget["label"].setText(
                f"Generating video clips... {current}/{total}"
            )

    def _on_video_done(self, total: int):
        if self._video_progress_widget:
            if total > 0:
                self._video_progress_widget["label"].setText(
                    f"{total} video clip{'s' if total != 1 else ''} generated."
                )
                self._video_progress_widget["label"].setStyleSheet(
                    "color: rgba(100,200,100,0.7); font-size: 12px;"
                )
                self._video_progress_widget["bar"].setValue(
                    self._video_progress_widget["bar"].maximum()
                )
            else:
                self._video_progress_widget["label"].setText(
                    "Video generation failed - you can try again later in Settings."
                )
                self._video_progress_widget["label"].setStyleSheet(
                    "color: rgba(255,150,100,0.7); font-size: 12px;"
                )
        # Notify AI (non-blocking - it may have already moved on)
        self._chat_messages.append({
            "role": "user",
            "content": f"(VIDEOS: complete - {total} clips generated)",
        })

    # ── Video background helpers ──

    def _find_xan_loop(self) -> Path | None:
        """Find Xan's ambient loop - checks user data then bundle."""
        # User data (full quality loops if available)
        user_loop = Path.home() / ".atrophy" / "agents" / "xan" / "avatar" / "loops" / "blue" / "loop_bounce_playful.mp4"
        if user_loop.exists():
            return user_loop
        # Bundled 20-min ambient video (compressed, ships with app)
        bundle_ambient = Path(__file__).parent.parent / "agents" / "xan" / "avatar" / "xan_ambient.mp4"
        if bundle_ambient.exists():
            return bundle_ambient
        # Individual clip fallback
        bundle_loop = Path(__file__).parent.parent / "agents" / "xan" / "avatar" / "loops" / "blue" / "loop_bounce_playful.mp4"
        if bundle_loop.exists():
            return bundle_loop
        return None

    def _setup_local_video(self, parent: QWidget, loop_path: Path):
        """Set up QMediaPlayer-based video background."""
        from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
        from display.window import FrameGrabSurface

        self._local_surface = FrameGrabSurface(self)
        self._local_surface.frame_ready.connect(self._on_local_frame)
        self._local_player = QMediaPlayer(self)
        self._local_player.setVideoOutput(self._local_surface)
        self._local_player.setMuted(True)
        self._local_player.mediaStatusChanged.connect(self._on_local_media_status)
        self._local_player.setMedia(QMediaContent(QUrl.fromLocalFile(str(loop_path))))
        self._video_bg = True  # signal that we have video (for scrim logic)

    def _on_local_frame(self, img: QImage):
        """Receive a decoded video frame - store and request repaint."""
        self._local_frame = img
        if hasattr(self, '_chat_overlay'):
            self._chat_overlay.update()

    def _on_local_media_status(self, status):
        """Loop the video when it ends."""
        from PyQt5.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.EndOfMedia and self._local_player:
            self._local_player.setPosition(0)
            self._local_player.play()

    def _start_local_video(self):
        """Start playback of local video (called when chat page becomes visible)."""
        if self._local_player:
            self._local_player.play()

    # ── Page 3: Creating ──

    def _build_page_creating(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(50, 0, 50, 40)
        lay.addStretch(3)

        if self._brain_pixmaps:
            icon_label = self._make_brain_label()
            lay.addWidget(icon_label)
            lay.addSpacing(16)

        self._creating_label = _label("Building.", 18, 0.8, align=Qt.AlignCenter)
        lay.addWidget(self._creating_label)
        lay.addSpacing(12)
        self._creating_detail = _label("", 12, 0.4, align=Qt.AlignCenter)
        lay.addWidget(self._creating_detail)

        lay.addStretch(4)
        self._pages.addWidget(page)

    # ── Page 4: Done ──

    def _build_page_done(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(50, 0, 50, 40)
        lay.addStretch(3)

        if self._brain_pixmaps:
            icon_label = self._make_brain_label()
            lay.addWidget(icon_label)
            lay.addSpacing(16)

        self._done_title = _label("", 20, 0.9, align=Qt.AlignCenter)
        lay.addWidget(self._done_title)
        lay.addSpacing(8)
        self._done_subtitle = _label("", 13, 0.45, align=Qt.AlignCenter)
        self._done_subtitle.setWordWrap(True)
        lay.addWidget(self._done_subtitle)
        lay.addSpacing(30)

        launch_btn = QPushButton("Launch")
        launch_btn.setObjectName("continueBtn")
        launch_btn.setCursor(Qt.PointingHandCursor)
        launch_btn.clicked.connect(self._finish)
        lay.addLayout(_centred(launch_btn, 200))

        lay.addStretch(4)
        self._pages.addWidget(page)

    # ── Agent creation ──

    def _do_skip(self):
        """User chose to skip agent creation - mark setup complete with Xan as default."""
        from config import save_user_config
        user_name = self._user_name or "User"
        save_user_config({
            "user_name": user_name,
            "default_agent": "xan",
            "setup_complete": True,
        })
        self._agent_created = True
        self._agent_name = "xan"
        self._done_title.setText("Ready.")
        self._done_subtitle.setText(
            "Xan is your active agent.\n\n"
            "Cmd+Shift+Space - show/hide from anywhere\n"
            "Hold Ctrl - push to talk\n"
            "Enable wake words to activate by voice\n\n"
            "Build a companion any time - Settings → Agents → New Agent,\n"
            "or just ask Xan to build one."
        )
        self._pages.setCurrentIndex(4)

    def _do_create(self):
        self._pages.setCurrentIndex(3)
        self._start_brain_animation(forward=True)  # animate brain during creation
        QTimer.singleShot(100, self._create_agent)

    def _create_agent(self):
        cfg = self._pending_config
        display_name = cfg.get("display_name", "Companion")
        slug = re.sub(r"[^a-z0-9_]", "_", display_name.lower().strip())
        user_name = self._user_name or "User"

        self._creating_detail.setText(f"Setting up {display_name}...")

        config = {
            "identity": {
                "display_name": display_name,
                "name": slug,
                "user_name": user_name,
                "origin_story": cfg.get("origin_story", f"A companion created for {user_name}."),
                "core_nature": cfg.get("core_nature", "A thoughtful, attentive presence."),
                "character_traits": cfg.get("character_traits", "Genuine and direct."),
                "values": cfg.get("values", "Honesty. Presence. Not performing."),
                "relationship": cfg.get("relationship", f"A companion to {user_name}."),
                "opening_line": cfg.get("opening_line", "Hello."),
            },
            "boundaries": {
                "wont_do": cfg.get("wont_do", "Won't mirror mood blindly. Won't validate without thinking."),
                "friction_modes": cfg.get("friction_modes", "Direct but kind. Names what's happening."),
                "session_limit_behaviour": "Check in - are you grounded?",
                "soft_limit_mins": 60,
            },
            "voice": {
                "tts_backend": "elevenlabs",
                "elevenlabs_voice_id": "",
                "fal_voice_id": "",
                "elevenlabs_model": "eleven_v3",
                "elevenlabs_stability": 0.5,
                "elevenlabs_similarity": 0.75,
                "elevenlabs_style": 0.35,
                "playback_rate": 1.12,
                "writing_style": cfg.get("writing_style", "Natural. Not too formal, not too casual."),
            },
            "appearance": {
                "has_avatar": self._selected_avatar is not None,
                "appearance_description": cfg.get("appearance_description", ""),
            },
            "channels": {"wake_words": f"hey {slug}, {slug}", "telegram_emoji": ""},
            "heartbeat": {"active_start": 9, "active_end": 22, "interval_mins": 30},
            "autonomy": {
                "introspection": True, "gifts": True, "morning_brief": True,
                "evolution": True, "sleep_cycle": True, "observer": True,
                "reminders": True, "inter_agent_conversations": False,
            },
        }

        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from scripts.create_agent import scaffold_from_config
            scaffold_from_config(config)
            self._agent_created = True
            self._agent_name = slug

            # Copy avatar and video assets to agent directory
            self._install_media_assets(slug)

            from config import save_user_config
            save_user_config({
                "user_name": user_name,
                "default_agent": slug,
                "setup_complete": True,
            })

            self._done_title.setText(f"{display_name} is ready.")
            self._done_subtitle.setText(
                f"{display_name} has memory, personality, and prompts.\n"
                "Customise anything in Settings.\n\n"
                "Cmd+Shift+Space - show/hide from anywhere\n"
                "Hold Ctrl - push to talk\n"
                "Switch agents with Cmd+Up/Down or from the tray menu."
            )
            self._pages.setCurrentIndex(4)

        except Exception as e:
            self._creating_label.setText("Something went wrong")
            self._creating_label.setStyleSheet("color: rgba(255,120,120,0.9); font-size: 18px;")
            self._creating_detail.setText(str(e)[:200])
            self._creating_detail.setStyleSheet("color: rgba(255,120,120,0.6); font-size: 12px;")

    def _install_media_assets(self, slug: str):
        """Copy avatar and video loops from temp files to the agent directory."""
        import shutil
        from config import USER_DATA

        agent_avatar = USER_DATA / "agents" / slug / "avatar"

        # Copy selected avatar → avatar/source/face.png
        if self._selected_avatar and Path(self._selected_avatar).exists():
            source_dir = agent_avatar / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._selected_avatar, source_dir / "face.png")

        # Copy video loops → avatar/loops/loop_00.mp4, loop_01.mp4, ...
        if self._video_loop_paths:
            loops_dir = agent_avatar / "loops"
            loops_dir.mkdir(parents=True, exist_ok=True)
            for i, src in enumerate(self._video_loop_paths):
                if Path(src).exists():
                    shutil.copy2(src, loops_dir / f"loop_{i:02d}.mp4")

    def _finish(self):
        self._completed = True
        self.close()

    # ── Painting ──

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.Resize and hasattr(self, '_chat_overlay'):
            w, h = obj.width(), obj.height()
            self._chat_overlay.setGeometry(0, 0, w, h)
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 16, 16)
        p.setClipPath(path)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0.0, QColor(10, 10, 18))
        grad.setColorAt(0.5, QColor(15, 15, 26))
        grad.setColorAt(1.0, QColor(10, 10, 18))
        p.fillRect(self.rect(), grad)
        p.setPen(QColor(255, 255, 255, 15))
        p.drawRoundedRect(0, 0, self.width() - 1, self.height() - 1, 16, 16)
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._secure_mode:
                self._on_secure_skip()
            elif self._pages.currentIndex() == 0:
                self._completed = True
                self.close()
            elif self._pages.currentIndex() == 3:
                self._finish()
        else:
            super().keyPressEvent(event)

    @property
    def user_name(self) -> str | None:
        return self._user_name

    @property
    def agent_name(self) -> str | None:
        return self._agent_name

    @property
    def agent_created(self) -> bool:
        return self._agent_created

    @property
    def completed(self) -> bool:
        return self._completed


# ── Public API ──

def needs_setup() -> bool:
    """Check if first-launch setup is needed.

    Looks for setup_complete flag in ~/.atrophy/config.json.
    User can reset this to re-run setup.
    """
    from config import _user_cfg
    return not _user_cfg.get("setup_complete", False)


def run_setup(app: QApplication = None) -> dict | None:
    """Run the setup wizard. Returns result dict or None if skipped.

    Result: {"user_name": str, "agent_name": str | None, "agent_created": bool}
    """
    if app is None:
        app = QApplication.instance() or QApplication(sys.argv)

    wizard = SetupWizard()
    loop = QEventLoop()

    _orig_closeEvent = wizard.closeEvent

    def _on_close(event):
        _orig_closeEvent(event)
        loop.quit()

    wizard.closeEvent = _on_close

    wizard.show()
    wizard.raise_()
    wizard.activateWindow()
    wizard._start_intro()

    # Bring to front - essential for LSUIElement apps
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except ImportError:
        pass

    loop.exec_()

    if wizard.user_name:
        return {
            "user_name": wizard.user_name,
            "agent_name": wizard.agent_name,
            "agent_created": wizard.agent_created,
        }
    return None

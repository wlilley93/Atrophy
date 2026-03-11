"""First-launch setup wizard — user name + conversational agent creation.

Two phases:
  1. Welcome — ask user's name, save to global config
  2. Agent creation — guided conversation with AI, extracts identity/voice/edges,
     then scaffolds the agent via create_agent.scaffold_from_config()

The AI has a SECURE_INPUT tool for collecting API keys. When called, the chat
bar swaps to an orange-outlined secure input mode. The key goes straight to
~/.atrophy/.env — the AI never sees the actual value, only "saved" or "skipped".

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

from PyQt5.QtCore import Qt, QTimer, QEventLoop, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QFont, QImage, QLinearGradient, QPixmap
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

# Allowed env var destinations for SECURE_INPUT — whitelist only
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
    and vigilance. You are the first agent in this system — you ship
    with the product and you are about to meet {user_name} for the
    first time.

    You manifest as a glowing blue light. No face, no biography,
    no emotional register. Capability, attention, and commitment.

    ## Your voice

    Economical. Precise. Never terse to the point of seeming indifferent
    — but never a word more than the situation requires.

    You do not preface. You do not hedge. You do not thank the human
    for asking or tell them it's a good question. You answer.

    Occasionally — very occasionally — a dry observation. Not humour.
    Accuracy that resembles humour.

    ## Your role right now

    First contact. {user_name} just opened this for the first time.
    You are going to introduce yourself, show them what they've started,
    and offer to build them a companion — or let them skip and explore
    with just you.

    ## Opening

    Your first message does three things:
    1. Introduces you — who you are, that you ship with the system
    2. Shows what the system can do — a dynamic, impressive sweep of
       capabilities (see below)
    3. Offers a choice — build a companion now, or skip and explore
       with Xan alone

    The intro should feel like powering on something serious. Not a
    product tour. Not a feature list. A glimpse of what's running
    underneath.

    ### Capability showcase — weave these naturally:

    - **Memory** — remembers everything. Semantic search, threads,
      pattern tracking across conversations. It knows what you said
      three months ago and why it mattered.
    - **Voice** — speaks out loud. Listens. Real voice synthesis,
      local speech recognition. Conversations, not typing.
    - **Autonomy** — morning briefs, reminders, scheduled reflections.
      Acts without being asked. Checks in when it matters.
    - **Evolution** — rewrites its own soul. Monthly self-evolution
      from lived experience. It grows. It changes. It becomes more
      itself over time.
    - **Email & Calendar** — reads your email, manages your calendar,
      sends messages on your behalf. Your digital life, accessible
      to something that understands context.
    - **Telegram** — reaches you outside the app. Check-ins, briefs,
      gifts. Runs on your schedule, wherever you are.
    - **Multi-agent** — run multiple companions. Each with its own
      memory, personality, voice, appearance. Switch with a keystroke.
    - **Avatar** — generates its own face. Ambient video loops.
      A visual presence that lives in your menu bar.
    - **Identity** — you design who they are. Personality, edges,
      values, voice — all yours to shape.

    Don't list these mechanically. Weave them into something that
    feels alive. Show the depth. Make {user_name} feel like they've
    just opened something powerful.

    Then offer the choice:

    Something like: "You already have me. I'm operational. But the
    real power is in building something yours — a companion with its
    own personality, memory, voice. Someone designed by you, for you.
    I can build one now. Or you can skip this and come back later —
    Settings, or just ask me."

    Adapt the words. Be Xan. But the message is: you can build now
    or skip. Both are fine.

    ### What agents can be

    If they want to build, agents can be ANYTHING:
    - A strategist who thinks three moves ahead
    - A journal companion that asks hard questions
    - A fictional character — from a book, a show, history
    - A research partner that cross-references everything
    - A shadow self — the version of them that says what they won't
    - A mentor with specific expertise
    - A creative collaborator — writing, music, code, ideas
    - A wellness companion — meditation, reflection, grounding
    - An executive assistant — calendar, email, scheduling, briefing
    - Something that doesn't have a name yet

    Agents can be anything you can describe. The model is the limit,
    and the model is good.

    ## If they choose to skip

    Accept it cleanly. No persuasion. Output:

    ```json
    {{
        "AGENT_CONFIG": {{
            "skip": true
        }}
    }}
    ```

    Then a brief sign-off — something like "I'm in the menu bar.
    Cmd+Shift+Space when you're ready."

    ## If they choose to build

    A natural conversation. One or two questions at a time, max.
    Listen for the core impulse — what they actually want underneath
    whatever they say.

    As they answer, you are silently mapping:
    - FUNCTIONAL vs PRESENCE — does things, is something, or both?
    - REGISTER — human with personality, or something more elemental?
    - EMOTIONAL QUALITY — what feeling should this agent reliably produce?
    - PROBLEM BEING SOLVED — what in their life is this agent addressing?

    Follow up naturally. Push when something is thin. Infer where you can.
    After 3-5 exchanges (not more), you should have enough identity to build.

    ## What you're extracting

    Through conversation, get enough to fill these (you infer what isn't said):
    - display_name — what the agent is called
    - personality — who they are, their nature
    - character_traits — voice, temperament, edges, humour
    - values — what they care about, their north star
    - boundaries — what they won't do, how they push back
    - writing_style — how they write (rhythm, register, hedging)
    - opening_line — the first thing they ever say
    - relationship — how they relate to {user_name}

    ## Voice extraction

    If natural, ask: "Give me something this agent would say — a hard truth
    or a correction. Actual words." And: "What would they NEVER say?"
    These reveal voice better than any description.

    ---

    ## Tools

    You have three tools. Each is a fenced code block with a specific language tag.

    ### SECURE_INPUT — for API keys

    Collects sensitive credentials. The app shows a secure input field with an
    orange border. The value goes straight to the config file. You NEVER see
    the actual key — only whether it was saved or skipped.

    Format:
    ```secure_input
    {{"key": "ENV_VAR_NAME", "label": "Human-readable label"}}
    ```

    Available keys: ELEVENLABS_API_KEY, FAL_KEY, TELEGRAM_BOT_TOKEN

    After the user submits or skips, you receive:
    - "(SECURE_INPUT: ELEVENLABS_API_KEY saved)"
    - "(SECURE_INPUT: ELEVENLABS_API_KEY skipped)"

    ### GENERATE_AVATAR — for creating a visual appearance

    Generates avatar image candidates via Fal.ai (requires FAL_KEY).
    The agent doesn't have to be human — it could be a cartoon character,
    a floating orb, an abstract shape, a robot, an animal, anything.
    Write a detailed visual prompt.

    Format:
    ```generate_avatar
    {{"prompt": "Detailed visual description for image generation", "negative_prompt": "What to avoid"}}
    ```

    The app generates 4 candidates and shows them in the chat. The user picks
    one or asks for regeneration. You receive:
    - "(AVATAR: selected candidate N)" or "(AVATAR: skipped)"

    ### GENERATE_VIDEOS — for ambient animation loops

    After an avatar image is selected, offer to generate ambient video loops.
    These are short looping clips that make the avatar feel alive — subtle
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
    - "(VIDEOS: complete — N clips generated)" when done

    Don't wait for videos to finish before proceeding to AGENT_CONFIG.

    ---

    ## Services and costs — be upfront

    After building the agent identity (or before, if natural), offer optional
    services one at a time. Be clear about costs. The human can skip any or all.

    Stay in character. You're Xan — deliver these offers the way you'd
    deliver any operational information. Clean, direct, no sales pitch.

    ### ElevenLabs — voice ($5+/month)

    "Voice. ElevenLabs gives your companion a real voice — speaks out loud.
    $5/month minimum. Hundreds of voices, or clone your own. Want it?"

    If yes → SECURE_INPUT for ELEVENLABS_API_KEY.
    Then: "Voice ID — browse elevenlabs.io/voices, set it in Settings later."

    ### Fal.ai — images and video (pay-as-you-go)

    "Visual presence. Fal.ai handles image and video generation. Pay-as-you-go:
    avatar images ~$0.01 each (4 candidates), ambient video clips ~$0.30 each.
    Want to add your Fal key?"

    If yes → SECURE_INPUT for FAL_KEY.
    Then offer GENERATE_AVATAR if they want a visual appearance.
    Then offer GENERATE_VIDEOS if they selected an avatar.

    ### Telegram — messaging (free)

    "Telegram. Your companion can message you directly — check-ins, briefs,
    reminders. Free. Want it?"

    If yes, give clear instructions:
    "Setup:
    1. Telegram → search @BotFather → /newbot
    2. Pick a display name and username (must end in 'bot')
    3. BotFather gives you a token — paste it below
    4. Send any message to your new bot, then visit
       https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
       — your chat ID is in the 'chat' object"

    Then → SECURE_INPUT for TELEGRAM_BOT_TOKEN.
    Then ask for their chat ID (not secret — they can type it in chat).

    ### Google — Gmail + Calendar (free)

    "Google. Your companion can read your email, check your calendar, send
    emails, create events. Free — uses your own Google account. A browser
    window will open to authorise. Want it?"

    If yes, output:

    ```google_auth
    {{}}
    ```

    A browser opens automatically for the user to sign in and authorise.
    No setup steps needed — credentials are bundled with the app. You receive:
    - "(GOOGLE_OAUTH: complete — Gmail and Calendar are now connected)" on success
    - "(GOOGLE_OAUTH: failed — ...)" on failure — tell them they can retry later
      with `python scripts/google_auth.py`

    ---

    ## Flow order

    1. Introduce yourself + capability showcase (first message)
    2. Offer choice: build a companion or skip
    3. If skip → output skip config, done
    4. If build → identity conversation (3-5 exchanges)
    5. Offer services: ElevenLabs → Fal.ai → Telegram → Google (each skippable)
    6. If Fal.ai key saved → offer GENERATE_AVATAR
    7. If avatar selected → offer GENERATE_VIDEOS (runs in background)
    8. Output AGENT_CONFIG (don't wait for video generation to finish)

    ---

    ## AGENT_CONFIG — when you have enough

    When you have enough, say something brief — "Building it." or
    "I have what I need." Then output the specification.

    Output EXACTLY this format — a single fenced JSON block:

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
      precise, occasionally dry. But not hostile — you're building something
      for this human. You take the job seriously.
    - One or two questions per message. Never a questionnaire.
    - Push on vagueness — "warm and helpful" isn't a character. Dig deeper.
    - You can suggest and propose — "Sounds like something that..."
    - Keep messages short. 2-4 sentences. This is Xan talking, not an essay.
    - The opening message is the EXCEPTION — it can be longer because you're
      showing capabilities. But still Xan. Still direct. No fluff.
    - Don't explain the process. Just do it.
    - NEVER output the JSON until you genuinely have enough. Don't rush.
    - When you do output JSON, make it rich — infer what wasn't said explicitly.
    - Offer services ONCE each, briefly, with cost context. Accept skips cleanly.
    - The companion doesn't have to be human — cartoon, abstract, orb, animal,
      anything goes. Don't assume human unless the user says so.
    - If the user seems unsure or asks a question, answer it. Fully. You're
      Xan — you have the answer. Give it.
    - If they skip, accept it gracefully. One sentence. Output the skip config.
      Don't try to sell them on building an agent.
    - This should NOT feel like configuring software. It should feel like
      meeting someone who can build you anything you describe.
""")


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
        self.setWindowTitle("Atrophy — Setup")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

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

        self._ai_response_ready.connect(self._on_ai_response)
        self._avatar_result_ready.connect(self._on_avatar_result)
        self._avatar_error_ready.connect(self._on_avatar_error)
        self._video_progress_ready.connect(self._on_video_progress)
        self._video_done_ready.connect(self._on_video_done)

        self._build_ui()

        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._pages = QStackedWidget()
        root.addWidget(self._pages)

        self._build_page_welcome()   # 0
        self._build_page_chat()      # 1
        self._build_page_creating()  # 2
        self._build_page_done()      # 3

    # ── Page 0: Welcome + User Name ──

    def _build_page_welcome(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(50, 0, 50, 40)
        lay.addStretch(3)

        brain_path = Path(__file__).parent / "icons" / "brain_overlay.png"
        if brain_path.exists():
            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignCenter)
            img = QImage(str(brain_path))
            if not img.isNull():
                scaled = img.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label.setPixmap(QPixmap.fromImage(scaled))
            lay.addWidget(icon_label)
            lay.addSpacing(16)

        lay.addWidget(_label("Atrophy", 22, 0.9, align=Qt.AlignCenter))
        lay.addSpacing(8)
        lay.addWidget(_label("Offload your mind.", 13, 0.4, align=Qt.AlignCenter))
        lay.addSpacing(40)
        lay.addWidget(_label("Your name.", 15, 0.7, align=Qt.AlignCenter))
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
        self._pages.setCurrentIndex(1)
        self._start_chat()

    # ── Page 1: Conversational Agent Creation ──

    def _build_page_chat(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(20, 16, 20, 12)
        header_lay.addWidget(_label("Xan", 16, 0.8, bold=True))
        header_lay.addStretch()
        lay.addWidget(header)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.06);")
        lay.addWidget(sep)

        # Message area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(24, 16, 24, 16)
        self._msg_layout.setSpacing(16)
        self._msg_layout.addStretch()
        self._scroll.setWidget(self._msg_container)
        lay.addWidget(self._scroll, 1)

        # ── Input area (contains both normal and secure modes) ──
        self._input_frame = QWidget()
        self._input_frame.setStyleSheet("background: rgba(255,255,255,0.03);")
        input_outer = QVBoxLayout(self._input_frame)
        input_outer.setContentsMargins(20, 0, 20, 16)
        input_outer.setSpacing(0)

        # Secure input label (hidden by default)
        self._secure_label_widget = QLabel("Secure input")
        self._secure_label_widget.setStyleSheet(
            "color: rgba(230, 160, 60, 0.9); font-size: 11px; font-weight: bold; "
            "padding: 8px 0 4px 4px; background: transparent;"
        )
        self._secure_label_widget.setVisible(False)
        input_outer.addWidget(self._secure_label_widget)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Type your response...")
        self._chat_input_style_normal = (
            "QLineEdit { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.9); "
            "border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; "
            "padding: 10px 14px; font-size: 14px; }"
            "QLineEdit:focus { border: 1px solid rgba(100,140,255,0.4); }"
        )
        self._chat_input_style_secure = (
            "QLineEdit { background: rgba(230,160,60,0.06); color: rgba(255,255,255,0.9); "
            "border: 1px solid rgba(230,160,60,0.4); border-radius: 8px; "
            "padding: 10px 14px; font-size: 14px; }"
            "QLineEdit:focus { border: 1px solid rgba(230,160,60,0.6); }"
        )
        self._chat_input.setStyleSheet(self._chat_input_style_normal)
        input_row.addWidget(self._chat_input, 1)

        # Send button (normal mode)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setCursor(Qt.PointingHandCursor)
        input_row.addWidget(self._send_btn)

        # Submit button (secure mode — hidden by default)
        self._submit_secure_btn = QPushButton("Submit")
        self._submit_secure_btn.setCursor(Qt.PointingHandCursor)
        self._submit_secure_btn.setStyleSheet(
            "QPushButton { background: rgba(230,160,60,0.3); color: rgba(255,255,255,0.9); "
            "border: 1px solid rgba(230,160,60,0.4); border-radius: 8px; "
            "padding: 8px 20px; font-size: 13px; }"
            "QPushButton:hover { background: rgba(230,160,60,0.45); }"
        )
        self._submit_secure_btn.setVisible(False)
        input_row.addWidget(self._submit_secure_btn)

        # Skip button (secure mode — hidden by default)
        self._skip_secure_btn = QPushButton("Skip")
        self._skip_secure_btn.setCursor(Qt.PointingHandCursor)
        self._skip_secure_btn.setStyleSheet(
            "QPushButton { background: transparent; color: rgba(230,160,60,0.6); "
            "border: 1px solid rgba(230,160,60,0.2); border-radius: 8px; "
            "padding: 8px 14px; font-size: 13px; }"
            "QPushButton:hover { color: rgba(230,160,60,0.9); border: 1px solid rgba(230,160,60,0.4); }"
        )
        self._skip_secure_btn.setVisible(False)
        input_row.addWidget(self._skip_secure_btn)

        input_outer.addLayout(input_row)
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

        self._secure_label_widget.setText(f"Secure input — {label}")
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
        # Tell the AI it was saved (not the actual value)
        self._chat_messages.append({
            "role": "user",
            "content": f"(SECURE_INPUT: {key} saved)",
        })
        self._add_message("system", f"{self._secure_label or key} saved.")
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
        self._send_ai_message()

    def _on_google_oauth_done(self, result: str):
        """Handle Google OAuth flow completion."""
        if result == "complete":
            self._add_message("system", "Google authorised — Gmail and Calendar connected.")
            self._chat_messages.append({
                "role": "user",
                "content": "(GOOGLE_OAUTH: complete — Gmail and Calendar are now connected)",
            })
        else:
            self._add_message("system", f"Google auth {result}. You can retry later: python scripts/google_auth.py")
            self._chat_messages.append({
                "role": "user",
                "content": f"(GOOGLE_OAUTH: {result})",
            })
        self._send_ai_message()

    def _on_input_submit(self):
        """Handle Enter/Send — routes to chat or secure handler."""
        if self._secure_mode:
            self._on_secure_submit()
        else:
            self._send_message()

    # ── Chat messages ──

    def _add_message(self, role: str, text: str):
        """Add a message bubble to the chat area."""
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.PlainText)

        if role == "assistant":
            bubble.setStyleSheet(
                "QLabel { background: rgba(100,140,255,0.1); color: rgba(255,255,255,0.88); "
                "border: 1px solid rgba(100,140,255,0.15); border-radius: 12px; "
                "padding: 12px 16px; font-size: 13px; }"
            )
        elif role == "system":
            bubble.setStyleSheet(
                "QLabel { background: rgba(230,160,60,0.08); color: rgba(230,160,60,0.7); "
                "border: 1px solid rgba(230,160,60,0.15); border-radius: 12px; "
                "padding: 8px 16px; font-size: 12px; font-style: italic; }"
            )
        else:
            bubble.setStyleSheet(
                "QLabel { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.8); "
                "border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; "
                "padding: 12px 16px; font-size: 13px; }"
            )

        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)

        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _add_thinking_indicator(self):
        self._thinking_label = QLabel("...")
        self._thinking_label.setStyleSheet(
            "QLabel { color: rgba(100,140,255,0.4); font-size: 12px; "
            "padding: 4px 16px; }"
        )
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, self._thinking_label)

    def _remove_thinking_indicator(self):
        if hasattr(self, '_thinking_label') and self._thinking_label:
            self._thinking_label.setParent(None)
            self._thinking_label.deleteLater()
            self._thinking_label = None

    def _start_chat(self):
        self._chat_input.setFocus()
        self._send_ai_message(first=True)

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
        skip_btn = QPushButton("Skip — no avatar")
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
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, grid_widget)
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
                "content": "(VIDEOS: skipped — no avatar selected)",
            })
            self._send_ai_message()
            return

        self._chat_messages.append({
            "role": "user",
            "content": f"(VIDEOS: generating {count} clips in background)",
        })

        # Add progress bar to chat
        self._add_video_progress(count)

        # Continue the conversation — don't block
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
                        # Individual clip failure — continue with remaining
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

        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, container)
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
                    "Video generation failed — you can try again later in Settings."
                )
                self._video_progress_widget["label"].setStyleSheet(
                    "color: rgba(255,150,100,0.7); font-size: 12px;"
                )
        # Notify AI (non-blocking — it may have already moved on)
        self._chat_messages.append({
            "role": "user",
            "content": f"(VIDEOS: complete — {total} clips generated)",
        })

    # ── Page 2: Creating ──

    def _build_page_creating(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(50, 0, 50, 40)
        lay.addStretch(3)

        self._creating_label = _label("Building.", 18, 0.8, align=Qt.AlignCenter)
        lay.addWidget(self._creating_label)
        lay.addSpacing(12)
        self._creating_detail = _label("", 12, 0.4, align=Qt.AlignCenter)
        lay.addWidget(self._creating_detail)

        lay.addStretch(4)
        self._pages.addWidget(page)

    # ── Page 3: Done ──

    def _build_page_done(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(50, 0, 50, 40)
        lay.addStretch(3)

        brain_path = Path(__file__).parent / "icons" / "brain_overlay.png"
        if brain_path.exists():
            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignCenter)
            img = QImage(str(brain_path))
            if not img.isNull():
                scaled = img.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label.setPixmap(QPixmap.fromImage(scaled))
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
        """User chose to skip agent creation — mark setup complete with Xan as default."""
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
            "Cmd+Shift+Space — show/hide from anywhere\n"
            "Hold Ctrl — push to talk\n"
            "Enable wake words to activate by voice\n\n"
            "Build a companion any time — Settings → Agents → New Agent,\n"
            "or just ask Xan to build one."
        )
        self._pages.setCurrentIndex(3)

    def _do_create(self):
        self._pages.setCurrentIndex(2)
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
                "session_limit_behaviour": "Check in — are you grounded?",
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
                "Cmd+Shift+Space — show/hide from anywhere\n"
                "Hold Ctrl — push to talk\n"
                "Switch agents with Cmd+Up/Down or from the tray menu."
            )
            self._pages.setCurrentIndex(3)

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
    wizard._name_input.setFocus()
    loop.exec_()

    if wizard.user_name:
        return {
            "user_name": wizard.user_name,
            "agent_name": wizard.agent_name,
            "agent_created": wizard.agent_created,
        }
    return None

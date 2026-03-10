"""Central configuration. Nothing hardcoded elsewhere."""
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "companion.db"
OPENING_CACHE = PROJECT_ROOT / ".opening_cache.json"
MESSAGE_QUEUE = PROJECT_ROOT / ".message_queue.json"
USER_STATUS_FILE = PROJECT_ROOT / ".user_status.json"
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "companion_system_prompt.md"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"

# Whisper
WHISPER_PATH = PROJECT_ROOT / "vendor" / "whisper.cpp"
WHISPER_BIN = WHISPER_PATH / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = WHISPER_PATH / "models" / "ggml-tiny.en.bin"

# Claude Code CLI
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")  # low, medium, high, max

# MCP Memory Server
MCP_DIR = PROJECT_ROOT / "mcp"
MCP_SERVER_SCRIPT = MCP_DIR / "memory_server.py"

# Voice — TTS
TTS_BACKEND = os.environ.get("TTS_BACKEND", "elevenlabs")  # "elevenlabs", "fal", "macos"
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v3")
ELEVENLABS_STABILITY = float(os.environ.get("ELEVENLABS_STABILITY", "0.5"))
ELEVENLABS_SIMILARITY = float(os.environ.get("ELEVENLABS_SIMILARITY", "0.75"))
ELEVENLABS_STYLE = float(os.environ.get("ELEVENLABS_STYLE", "0.35"))
TTS_PLAYBACK_RATE = float(os.environ.get("TTS_PLAYBACK_RATE", "1.12"))  # afplay -r rate

# Fal TTS fallback (ElevenLabs v3 via Fal, uses FAL_KEY from .env)
FAL_TTS_ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"
FAL_VOICE_ID = os.environ.get("FAL_VOICE_ID", "")

# Voice — Input
PTT_KEY = "ctrl"  # hold to record (pynput Key.ctrl_l)
INPUT_MODE = os.environ.get("INPUT_MODE", "dual")  # "voice", "text", "dual"

# Audio capture
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORD_SEC = 120

# Avatar (preserved for future)
SOURCE_IMAGE = PROJECT_ROOT / "avatar" / "source" / "companion.png"
LIVEPORTRAIT_PATH = Path.home() / "LivePortrait"
AVATAR_RESOLUTION = 512
AVATAR_ENABLED = os.environ.get("AVATAR_ENABLED", "false").lower() == "true"
IDLE_LOOP = PROJECT_ROOT / "avatar" / "ambient_loop.mp4"
IDLE_LOOPS_DIR = PROJECT_ROOT / "avatar" / "loops"
IDLE_THINKING = PROJECT_ROOT / "avatar" / "idle_thinking.mp4"
IDLE_LISTENING = PROJECT_ROOT / "avatar" / "idle_listening.mp4"
IDLE_DRIVER = PROJECT_ROOT / "avatar" / "source" / "idle_driver.wav"

# Obsidian vault (for companion note reading/writing)
OBSIDIAN_VAULT = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    str(Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "The Atrophied Mind"),
))

# Memory
CONTEXT_SUMMARIES = 3
MAX_CONTEXT_TOKENS = 180000

# Session
SESSION_SOFT_LIMIT_MINS = 60

# Display (matches ambient_loop.mp4: 1244x1660)
WINDOW_WIDTH = 622
WINDOW_HEIGHT = 830

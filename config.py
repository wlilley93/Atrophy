"""Central configuration. Agent-aware — loads identity from agents/<name>/."""
import json
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"

# ── Active agent ──
AGENT_NAME = os.environ.get("AGENT", "companion")
AGENT_DIR = PROJECT_ROOT / "agents" / AGENT_NAME

# Load agent manifest
_manifest_path = AGENT_DIR / "agent.json"
if _manifest_path.exists():
    AGENT = json.loads(_manifest_path.read_text())
else:
    AGENT = {"name": AGENT_NAME, "display_name": AGENT_NAME.title(), "user_name": "User"}

# ── Agent identity ──
AGENT_DISPLAY_NAME = AGENT.get("display_name", AGENT_NAME.title())
USER_NAME = AGENT.get("user_name", "User")
OPENING_LINE = AGENT.get("opening_line", "Hello.")
WAKE_WORDS = AGENT.get("wake_words", [f"hey {AGENT_NAME}", AGENT_NAME])

# ── Per-agent paths ──
DB_PATH = AGENT_DIR / "memory.db"
OPENING_CACHE = AGENT_DIR / "state" / ".opening_cache.json"
MESSAGE_QUEUE = AGENT_DIR / "state" / ".message_queue.json"
EMOTIONAL_STATE_FILE = AGENT_DIR / "state" / ".emotional_state.json"
USER_STATUS_FILE = AGENT_DIR / "state" / ".user_status.json"
CANVAS_CONTENT = AGENT_DIR / "state" / ".canvas_content.html"
SYSTEM_PROMPT_PATH = AGENT_DIR / "system_prompt.md"
SOUL_PATH = AGENT_DIR / "soul.md"
HEARTBEAT_PATH = AGENT_DIR / "heartbeat.md"
DREAM_LOG = AGENT_DIR / "state" / ".dream_log.txt"
IDENTITY_QUEUE = AGENT_DIR / "state" / ".identity_review_queue.json"

# ── Per-agent avatar ──
AVATAR_DIR = AGENT_DIR / "avatar"
SOURCE_IMAGE = AVATAR_DIR / "source" / "face.png"
IDLE_LOOP = AVATAR_DIR / "ambient_loop.mp4"
IDLE_LOOPS_DIR = AVATAR_DIR / "loops"
IDLE_THINKING = AVATAR_DIR / "idle_thinking.mp4"
IDLE_LISTENING = AVATAR_DIR / "idle_listening.mp4"
IDLE_DRIVER = AVATAR_DIR / "source" / "idle_driver.wav"
AVATAR_RESOLUTION = 512
AVATAR_ENABLED = os.environ.get("AVATAR_ENABLED", "false").lower() == "true"
LIVEPORTRAIT_PATH = Path.home() / "LivePortrait"

# ── Voice — TTS (per-agent from manifest) ──
_voice = AGENT.get("voice", {})
TTS_BACKEND = _voice.get("tts_backend", os.environ.get("TTS_BACKEND", "elevenlabs"))
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = _voice.get("elevenlabs_voice_id", os.environ.get("ELEVENLABS_VOICE_ID", ""))
ELEVENLABS_MODEL = _voice.get("elevenlabs_model", os.environ.get("ELEVENLABS_MODEL", "eleven_v3"))
ELEVENLABS_STABILITY = _voice.get("elevenlabs_stability", float(os.environ.get("ELEVENLABS_STABILITY", "0.5")))
ELEVENLABS_SIMILARITY = _voice.get("elevenlabs_similarity", float(os.environ.get("ELEVENLABS_SIMILARITY", "0.75")))
ELEVENLABS_STYLE = _voice.get("elevenlabs_style", float(os.environ.get("ELEVENLABS_STYLE", "0.35")))
TTS_PLAYBACK_RATE = _voice.get("playback_rate", float(os.environ.get("TTS_PLAYBACK_RATE", "1.12")))
FAL_TTS_ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"
FAL_VOICE_ID = _voice.get("fal_voice_id", os.environ.get("FAL_VOICE_ID", ""))

# ── Voice — Input ──
PTT_KEY = "ctrl"
INPUT_MODE = os.environ.get("INPUT_MODE", "dual")

# ── Audio capture ──
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORD_SEC = 120

# ── Wake word detection ──
WAKE_WORD_ENABLED = os.environ.get("WAKE_WORD_ENABLED", "false").lower() == "true"
WAKE_CHUNK_SECONDS = 2

# ── Whisper ──
WHISPER_PATH = PROJECT_ROOT / "vendor" / "whisper.cpp"
WHISPER_BIN = WHISPER_PATH / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = WHISPER_PATH / "models" / "ggml-tiny.en.bin"

# ── Claude Code CLI ──
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")
ADAPTIVE_EFFORT = os.environ.get("ADAPTIVE_EFFORT", "true").lower() == "true"

# ── MCP Memory Server ──
MCP_DIR = PROJECT_ROOT / "mcp"
MCP_SERVER_SCRIPT = MCP_DIR / "memory_server.py"

# ── Obsidian vault ──
_obsidian_base = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    str(Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "The Atrophied Mind"),
))
OBSIDIAN_VAULT = _obsidian_base
OBSIDIAN_AGENT_DIR = _obsidian_base / AGENT.get("obsidian_subdir", AGENT_DISPLAY_NAME)
OBSIDIAN_AGENT_NOTES = OBSIDIAN_AGENT_DIR / "agents" / AGENT_NAME

# ── Memory ──
CONTEXT_SUMMARIES = 3
MAX_CONTEXT_TOKENS = 180000

# ── Embeddings & Vector Search ──
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MODELS_DIR = PROJECT_ROOT / ".models"
VECTOR_SEARCH_WEIGHT = 0.7

# ── Session ──
SESSION_SOFT_LIMIT_MINS = 60

# ── Heartbeat (per-agent from manifest) ──
_hb = AGENT.get("heartbeat", {})
HEARTBEAT_ACTIVE_START = _hb.get("active_start", int(os.environ.get("HEARTBEAT_ACTIVE_START", "9")))
HEARTBEAT_ACTIVE_END = _hb.get("active_end", int(os.environ.get("HEARTBEAT_ACTIVE_END", "22")))
HEARTBEAT_INTERVAL_MINS = _hb.get("interval_mins", int(os.environ.get("HEARTBEAT_INTERVAL_MINS", "30")))

# ── Telegram (per-agent from manifest) ──
_tg = AGENT.get("telegram", {})
TELEGRAM_BOT_TOKEN = os.environ.get(
    _tg.get("bot_token_env", "TELEGRAM_BOT_TOKEN"),
    os.environ.get("TELEGRAM_BOT_TOKEN", ""),
)
TELEGRAM_CHAT_ID = os.environ.get(
    _tg.get("chat_id_env", "TELEGRAM_CHAT_ID"),
    os.environ.get("TELEGRAM_CHAT_ID", ""),
)

# ── Canvas ──
CANVAS_TEMPLATES = PROJECT_ROOT / "display" / "templates"

# ── Display (per-agent from manifest) ──
_disp = AGENT.get("display", {})
WINDOW_WIDTH = _disp.get("window_width", 622)
WINDOW_HEIGHT = _disp.get("window_height", 830)

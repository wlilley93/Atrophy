"""Central configuration — three-tier path resolution.

Resolution order (highest wins):
  1. Environment variables
  2. User config     (~/.atrophy/config.json)
  3. Agent manifest  (agents/<name>/data/agent.json — bundled or user-installed)
  4. Hardcoded defaults

Two root paths:
  BUNDLE_ROOT — where the code lives (repo checkout or .app bundle)
  USER_DATA   — ~/.atrophy/ — runtime state, memory DBs, user config

Agent definitions (agent.json, prompts/) are searched in USER_DATA first,
then BUNDLE_ROOT. This lets users install custom agents by dropping a folder
into ~/.atrophy/agents/<name>/.
"""
import json
import os
from pathlib import Path


# ── Root paths ──
BUNDLE_ROOT = Path(os.environ.get("ATROPHY_BUNDLE", str(Path(__file__).parent)))
USER_DATA = Path(os.environ.get("ATROPHY_DATA", str(Path.home() / ".atrophy")))


def ensure_user_data():
    """Create ~/.atrophy/ structure on first run. Safe to call repeatedly."""
    dirs = [
        USER_DATA,
        USER_DATA / "agents",
        USER_DATA / "logs",
        USER_DATA / "models",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Seed config.json if missing
    cfg_path = USER_DATA / "config.json"
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps({}, indent=2) + "\n")
        cfg_path.chmod(0o600)

    # Migrate legacy data from bundle (agents/<name>/data/) to ~/.atrophy/agents/<name>/data/
    _migrate_legacy_data()


def _migrate_legacy_data():
    """One-time migration: copy runtime data from repo to ~/.atrophy/."""
    import shutil
    bundle_agents = BUNDLE_ROOT / "agents"
    if not bundle_agents.is_dir():
        return
    for agent_dir in bundle_agents.iterdir():
        if not agent_dir.is_dir():
            continue
        # Migrate data/ files
        old_data = agent_dir / "data"
        new_data = USER_DATA / "agents" / agent_dir.name / "data"
        if old_data.is_dir():
            new_data.mkdir(parents=True, exist_ok=True)
            for f in old_data.iterdir():
                if f.name == "agent.json":
                    continue  # manifest stays in bundle
                dest = new_data / f.name
                if not dest.exists() and f.is_file():
                    shutil.copy2(f, dest)
        # Migrate entire avatar/ tree (source images, loops, videos) to user data
        old_avatar = agent_dir / "avatar"
        new_avatar = USER_DATA / "agents" / agent_dir.name / "avatar"
        if old_avatar.is_dir():
            for dirpath, dirnames, filenames in os.walk(old_avatar):
                rel = Path(dirpath).relative_to(old_avatar)
                dest_dir = new_avatar / rel
                dest_dir.mkdir(parents=True, exist_ok=True)
                for fname in filenames:
                    src = Path(dirpath) / fname
                    dest = dest_dir / fname
                    if not dest.exists():
                        shutil.copy2(src, dest)


# Run on import — lightweight, idempotent
ensure_user_data()


# ── User config (from ~/.atrophy/config.json) ──
_user_cfg_path = USER_DATA / "config.json"
_user_cfg: dict = {}
if _user_cfg_path.exists():
    try:
        _user_cfg = json.loads(_user_cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        _user_cfg = {}


def _cfg(key: str, default=None):
    """Read from env var first, then config.json, then default."""
    env = os.environ.get(key)
    if env is not None:
        return env
    return _user_cfg.get(key, default)


def save_user_config(updates: dict):
    """Merge updates into ~/.atrophy/config.json and write."""
    global _user_cfg
    _user_cfg.update(updates)
    _user_cfg_path.write_text(json.dumps(_user_cfg, indent=2) + "\n")


# ── Version ──
_version_file = BUNDLE_ROOT / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "0.0.0"

# ── Schema ──
SCHEMA_PATH = BUNDLE_ROOT / "db" / "schema.sql"

# ── Active agent ──
AGENT_NAME = _cfg("AGENT", "companion")


def _find_agent_dir(name: str) -> Path:
    """Find agent definition — user-installed agents take precedence over bundled."""
    user_agent = USER_DATA / "agents" / name
    bundle_agent = BUNDLE_ROOT / "agents" / name
    if (user_agent / "data" / "agent.json").exists():
        return user_agent
    if (bundle_agent / "data" / "agent.json").exists():
        return bundle_agent
    # Fallback: prefer user dir (for new agents being created)
    return user_agent


def _agent_data_dir(name: str) -> Path:
    """Runtime data always lives in USER_DATA, never in the bundle."""
    d = USER_DATA / "agents" / name / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


AGENT_DIR = _find_agent_dir(AGENT_NAME)
DATA_DIR = _agent_data_dir(AGENT_NAME)

# Load agent manifest
_manifest_path = AGENT_DIR / "data" / "agent.json"
if _manifest_path.exists():
    AGENT = json.loads(_manifest_path.read_text())
else:
    AGENT = {"name": AGENT_NAME, "display_name": AGENT_NAME.title(), "user_name": "User"}

# ── Agent identity ──
AGENT_DISPLAY_NAME = AGENT.get("display_name", AGENT_NAME.title())
USER_NAME = _user_cfg.get("user_name") or AGENT.get("user_name", "User")
OPENING_LINE = AGENT.get("opening_line", "Hello.")
WAKE_WORDS = AGENT.get("wake_words", [f"hey {AGENT_NAME}", AGENT_NAME])
TELEGRAM_EMOJI = AGENT.get("telegram_emoji", "")

# ── Per-agent paths ──
# Prompts come from the agent definition (bundle or user-installed)
PROMPTS_DIR = AGENT_DIR / "prompts"
# Runtime state always in USER_DATA
DB_PATH = DATA_DIR / "memory.db"
OPENING_CACHE = DATA_DIR / ".opening_cache.json"
MESSAGE_QUEUE = DATA_DIR / ".message_queue.json"
EMOTIONAL_STATE_FILE = DATA_DIR / ".emotional_state.json"
USER_STATUS_FILE = DATA_DIR / ".user_status.json"
CANVAS_CONTENT = DATA_DIR / ".canvas_content.html"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.md"
SOUL_PATH = PROMPTS_DIR / "soul.md"
HEARTBEAT_PATH = PROMPTS_DIR / "heartbeat.md"
IDENTITY_QUEUE = DATA_DIR / ".identity_review_queue.json"
ARTEFACT_DISPLAY_FILE = DATA_DIR / ".artefact_display.json"
ARTEFACT_INDEX_FILE = DATA_DIR / ".artefact_index.json"

# ── Per-agent avatar ──
# All avatar assets live in user data (~/.atrophy/agents/<name>/avatar/).
# Bundle path is a fallback for first-run before migration completes.
_AVATAR_USER = USER_DATA / "agents" / AGENT_NAME / "avatar"
_AVATAR_BUNDLE = AGENT_DIR / "avatar"
AVATAR_DIR = _AVATAR_USER if _AVATAR_USER.is_dir() else _AVATAR_BUNDLE

def _avatar_path(rel: str) -> Path:
    """Resolve an avatar-relative path, preferring user data over bundle."""
    user = _AVATAR_USER / rel
    if user.exists():
        return user
    return _AVATAR_BUNDLE / rel

SOURCE_IMAGE = _avatar_path("source/face.png")
IDLE_DRIVER = _avatar_path("source/idle_driver.wav")
AVATAR_RESOLUTION = 512
AVATAR_ENABLED = _cfg("AVATAR_ENABLED", "false").lower() == "true"
IDLE_LOOPS_DIR = _AVATAR_USER / "loops"
IDLE_LOOP = _AVATAR_USER / "ambient_loop.mp4"
IDLE_THINKING = _AVATAR_USER / "idle_thinking.mp4"
IDLE_LISTENING = _AVATAR_USER / "idle_listening.mp4"

# ── Per-agent tool disabling ──
DISABLED_TOOLS = AGENT.get("disabled_tools", [])

# ── Voice — TTS (per-agent from manifest) ──
_voice = AGENT.get("voice", {})
TTS_BACKEND = _voice.get("tts_backend", _cfg("TTS_BACKEND", "elevenlabs"))
ELEVENLABS_API_KEY = _cfg("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = _voice.get("elevenlabs_voice_id", _cfg("ELEVENLABS_VOICE_ID", ""))
ELEVENLABS_MODEL = _voice.get("elevenlabs_model", _cfg("ELEVENLABS_MODEL", "eleven_v3"))
ELEVENLABS_STABILITY = _voice.get("elevenlabs_stability", float(_cfg("ELEVENLABS_STABILITY", "0.5")))
ELEVENLABS_SIMILARITY = _voice.get("elevenlabs_similarity", float(_cfg("ELEVENLABS_SIMILARITY", "0.75")))
ELEVENLABS_STYLE = _voice.get("elevenlabs_style", float(_cfg("ELEVENLABS_STYLE", "0.35")))
TTS_PLAYBACK_RATE = _voice.get("playback_rate", float(_cfg("TTS_PLAYBACK_RATE", "1.12")))
FAL_TTS_ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"
FAL_VOICE_ID = _voice.get("fal_voice_id", _cfg("FAL_VOICE_ID", ""))

# ── Voice — Input ──
PTT_KEY = "ctrl"
INPUT_MODE = _cfg("INPUT_MODE", "dual")

# ── Audio capture ──
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORD_SEC = 120

# ── Wake word detection ──
WAKE_WORD_ENABLED = _cfg("WAKE_WORD_ENABLED", "false").lower() == "true"
WAKE_CHUNK_SECONDS = 2

# ── Whisper ──
WHISPER_PATH = BUNDLE_ROOT / "vendor" / "whisper.cpp"
WHISPER_BIN = WHISPER_PATH / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = WHISPER_PATH / "models" / "ggml-tiny.en.bin"

# ── Claude Code CLI ──
CLAUDE_BIN = _cfg("CLAUDE_BIN", "claude")
CLAUDE_EFFORT = _cfg("CLAUDE_EFFORT", "medium")
ADAPTIVE_EFFORT = _cfg("ADAPTIVE_EFFORT", "true").lower() == "true"

# ── MCP Memory Server ──
MCP_DIR = BUNDLE_ROOT / "mcp"
MCP_SERVER_SCRIPT = MCP_DIR / "memory_server.py"

# ── Obsidian vault (optional — graceful when absent) ──
_obsidian_default = str(Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "The Atrophied Mind")
_obsidian_base = Path(_cfg("OBSIDIAN_VAULT", _obsidian_default))
OBSIDIAN_VAULT = _obsidian_base
OBSIDIAN_PROJECT_DIR = _obsidian_base / "Projects" / BUNDLE_ROOT.name
OBSIDIAN_AGENT_DIR = OBSIDIAN_PROJECT_DIR / "Agent Workspace" / AGENT_NAME
OBSIDIAN_AGENT_NOTES = OBSIDIAN_AGENT_DIR

# ── Memory ──
CONTEXT_SUMMARIES = 3
MAX_CONTEXT_TOKENS = 180000

# ── Embeddings & Vector Search ──
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MODELS_DIR = USER_DATA / "models"
VECTOR_SEARCH_WEIGHT = 0.7

# ── Session ──
SESSION_SOFT_LIMIT_MINS = 60

# ── Heartbeat (per-agent from manifest) ──
_hb = AGENT.get("heartbeat", {})
HEARTBEAT_ACTIVE_START = _hb.get("active_start", int(_cfg("HEARTBEAT_ACTIVE_START", "9")))
HEARTBEAT_ACTIVE_END = _hb.get("active_end", int(_cfg("HEARTBEAT_ACTIVE_END", "22")))
HEARTBEAT_INTERVAL_MINS = _hb.get("interval_mins", int(_cfg("HEARTBEAT_INTERVAL_MINS", "30")))

# ── Telegram (per-agent from manifest) ──
_tg = AGENT.get("telegram", {})
TELEGRAM_BOT_TOKEN = os.environ.get(
    _tg.get("bot_token_env", "TELEGRAM_BOT_TOKEN"),
    _cfg("TELEGRAM_BOT_TOKEN", ""),
)
TELEGRAM_CHAT_ID = os.environ.get(
    _tg.get("chat_id_env", "TELEGRAM_CHAT_ID"),
    _cfg("TELEGRAM_CHAT_ID", ""),
)

# ── Notifications ──
NOTIFICATIONS_ENABLED = _cfg("NOTIFICATIONS_ENABLED", "true").lower() == "true"

# ── Canvas ──
CANVAS_TEMPLATES = BUNDLE_ROOT / "display" / "templates"

# ── Display (per-agent from manifest) ──
_disp = AGENT.get("display", {})
WINDOW_WIDTH = _disp.get("window_width", 622)
WINDOW_HEIGHT = _disp.get("window_height", 830)

# ── Backward compat ──
# Some modules use PROJECT_ROOT — alias to BUNDLE_ROOT
PROJECT_ROOT = BUNDLE_ROOT

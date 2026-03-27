# config.py - Python Configuration Module

**Line count:** ~317 lines  
**Dependencies:** `json`, `os`, `pathlib`  
**Purpose:** Central configuration with three-tier path resolution (Python version)

## Overview

This is the Python counterpart to the TypeScript `src/main/config.ts`. It provides the same three-tier configuration resolution for Python scripts that run outside the Electron app (launchd jobs, setup scripts, etc.).

**Resolution order (highest wins):**
1. Environment variables
2. User config (`~/.atrophy/config.json`)
3. Agent manifest (`agents/<name>/data/agent.json`)
4. Hardcoded defaults

## Root Paths

```python
BUNDLE_ROOT = Path(os.environ.get("ATROPHY_BUNDLE", str(Path(__file__).parent)))
USER_DATA = Path(os.environ.get("ATROPHY_DATA", str(Path.home() / ".atrophy")))
```

**Purpose:** Define root paths for bundle and user data.

**Environment overrides:**
- `ATROPHY_BUNDLE`: Override bundle root
- `ATROPHY_DATA`: Override user data directory

## User Data Initialization

### ensure_user_data

```python
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

    # Migrate legacy data from bundle
    _migrate_legacy_data()
```

**Purpose:** Create directory structure and seed config.

### _migrate_legacy_data

```python
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
        # Migrate entire avatar/ tree
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
```

**Purpose:** Migrate bundled data to user data directory.

**Migration rules:**
- Skip `agent.json` (manifest stays in bundle)
- Copy data files only if destination doesn't exist
- Copy entire avatar tree (source images, loops)

**Auto-run:** Called on module import (lightweight, idempotent).

## User Config

```python
_user_cfg_path = USER_DATA / "config.json"
_user_cfg: dict = {}
if _user_cfg_path.exists():
    try:
        _user_cfg = json.loads(_user_cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        _user_cfg = {}
```

### _cfg

```python
def _cfg(key: str, default=None):
    """Read from env var first, then config.json, then default."""
    env = os.environ.get(key)
    if env is not None:
        return env
    val = _user_cfg.get(key, default)
    # Coerce to string if default is string
    if isinstance(default, str) and not isinstance(val, str):
        return str(val).lower()
    return val
```

**Purpose:** Three-tier config resolution.

### save_user_config

```python
def save_user_config(updates: dict):
    """Merge updates into ~/.atrophy/config.json and write."""
    global _user_cfg
    _user_cfg.update(updates)
    _user_cfg_path.write_text(json.dumps(_user_cfg, indent=2) + "\n")
```

**Purpose:** Save config updates.

## Version & Schema

```python
_version_file = BUNDLE_ROOT / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "0.0.0"

# Schema path
SCHEMA_PATH = BUNDLE_ROOT / "db" / "schema.sql"
```

## Active Agent

```python
AGENT_NAME = _cfg("AGENT", "xan")
```

### _find_agent_dir

```python
def _find_agent_dir(name: str) -> Path:
    """Find agent definition — user-installed agents take precedence."""
    user_agent = USER_DATA / "agents" / name
    bundle_agent = BUNDLE_ROOT / "agents" / name
    if (user_agent / "data" / "agent.json").exists():
        return user_agent
    if (bundle_agent / "data" / "agent.json").exists():
        return bundle_agent
    # Fallback: prefer user dir (for new agents being created)
    return user_agent
```

**Purpose:** Find agent directory with user precedence.

### _agent_data_dir

```python
def _agent_data_dir(name: str) -> Path:
    """Runtime data always lives in USER_DATA, never in the bundle."""
    d = USER_DATA / "agents" / name / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

**Purpose:** Get agent data directory (always in USER_DATA).

## Agent Manifest

```python
AGENT_DIR = _find_agent_dir(AGENT_NAME)
DATA_DIR = _agent_data_dir(AGENT_NAME)

# Load agent manifest
_agent_manifest_path = AGENT_DIR / "data" / "agent.json"
AGENT_MANIFEST: dict = {}
if _agent_manifest_path.exists():
    try:
        AGENT_MANIFEST = json.loads(_agent_manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        AGENT_MANIFEST = {}
```

## Agent Config Helper

```python
def _agent_cfg(key: str, default=None):
    """Read from agent manifest with dot notation support."""
    keys = key.split(".")
    val = AGENT_MANIFEST
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            val = None
            break
    if val is None:
        val = _cfg(key, default)
    return val
```

**Purpose:** Read from agent manifest with fallback to user config.

**Dot notation:** `"voice.elevenlabs_voice_id"` → `manifest["voice"]["elevenlabs_voice_id"]`

## Configuration Values

```python
# Identity
AGENT_DISPLAY_NAME = _agent_cfg("display_name", AGENT_NAME.capitalize())
USER_NAME = _agent_cfg("user_name", "User")
OPENING_LINE = _agent_cfg("opening_line", "Hello.")
WAKE_WORDS = _agent_cfg("wake_words", [f"hey {AGENT_NAME}", AGENT_NAME])
TELEGRAM_EMOJI = _agent_cfg("telegram_emoji", "")
DISABLED_TOOLS = _agent_cfg("disabled_tools", [])

# TTS
TTS_BACKEND = _agent_cfg("voice.tts_backend", "elevenlabs")
ELEVENLABS_VOICE_ID = _agent_cfg("voice.elevenlabs_voice_id", "")
ELEVENLABS_MODEL = _agent_cfg("voice.elevenlabs_model", "eleven_v3")
ELEVENLABS_STABILITY = float(_agent_cfg("voice.elevenlabs_stability", 0.5))
ELEVENLABS_SIMILARITY = float(_agent_cfg("voice.elevenlabs_similarity", 0.75))
ELEVENLABS_STYLE = float(_agent_cfg("voice.elevenlabs_style", 0.35))
TTS_PLAYBACK_RATE = float(_agent_cfg("voice.playback_rate", 1.12))
FAL_VOICE_ID = _agent_cfg("voice.fal_voice_id", "")

# Audio
PTT_KEY = _cfg("PTT_KEY", "ctrl")
INPUT_MODE = _cfg("INPUT_MODE", "dual")
SAMPLE_RATE = int(_cfg("SAMPLE_RATE", 16000))
CHANNELS = int(_cfg("CHANNELS", 1))
MAX_RECORD_SEC = int(_cfg("MAX_RECORD_SEC", 120))

# Wake word
WAKE_WORD_ENABLED = _cfg("WAKE_WORD_ENABLED", "false").lower() == "true"
WAKE_CHUNK_SECONDS = int(_cfg("WAKE_CHUNK_SECONDS", 2))

# Claude CLI
CLAUDE_BIN = _cfg("CLAUDE_BIN", "claude")
CLAUDE_MODEL = _cfg("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_EFFORT = _cfg("CLAUDE_EFFORT", "medium")
ADAPTIVE_EFFORT = _cfg("ADAPTIVE_EFFORT", "true").lower() == "true"

# Memory & context
CONTEXT_SUMMARIES = int(_cfg("CONTEXT_SUMMARIES", 3))
MAX_CONTEXT_TOKENS = int(_cfg("MAX_CONTEXT_TOKENS", 180000))

# Embeddings
EMBEDDING_MODEL = _cfg("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM = int(_cfg("EMBEDDING_DIM", 384))
MODELS_DIR = USER_DATA / "models"
VECTOR_SEARCH_WEIGHT = float(_cfg("VECTOR_SEARCH_WEIGHT", 0.7))

# Session
SESSION_SOFT_LIMIT_MINS = int(_cfg("SESSION_SOFT_LIMIT_MINS", 60))

# Heartbeat
HEARTBEAT_ACTIVE_START = int(_cfg("HEARTBEAT_ACTIVE_START", 9))
HEARTBEAT_ACTIVE_END = int(_cfg("HEARTBEAT_ACTIVE_END", 22))
HEARTBEAT_INTERVAL_MINS = int(_cfg("HEARTBEAT_INTERVAL_MINS", 30))

# Telegram
TELEGRAM_BOT_TOKEN = _agent_cfg("telegram_bot_token", "")
TELEGRAM_CHAT_ID = _agent_cfg("telegram_chat_id", "")

# Notifications
NOTIFICATIONS_ENABLED = _cfg("NOTIFICATIONS_ENABLED", "true").lower() == "true"

# Silence timer
SILENCE_TIMER_ENABLED = _cfg("SILENCE_TIMER_ENABLED", "true").lower() == "true"
SILENCE_TIMER_MINUTES = int(_cfg("SILENCE_TIMER_MINUTES", 5))

# UI defaults
EYE_MODE_DEFAULT = _cfg("EYE_MODE_DEFAULT", "false").lower() == "true"
MUTE_BY_DEFAULT = _cfg("MUTE_BY_DEFAULT", "false").lower() == "true"

# Display
WINDOW_WIDTH = int(_cfg("WINDOW_WIDTH", 622))
WINDOW_HEIGHT = int(_cfg("WINDOW_HEIGHT", 830))

# Avatar
AVATAR_ENABLED = _cfg("AVATAR_ENABLED", "false").lower() == "true"
AVATAR_RESOLUTION = int(_cfg("AVATAR_RESOLUTION", 512))
AVATAR_DIR = USER_DATA / "agents" / AGENT_NAME / "avatar"
SOURCE_IMAGE = AVATAR_DIR / "source" / "face.png"
IDLE_LOOPS_DIR = AVATAR_DIR / "loops"
IDLE_LOOP = IDLE_LOOPS_DIR / "ambient_loop.mp4"
IDLE_THINKING = IDLE_LOOPS_DIR / "thinking.mp4"
IDLE_LISTENING = IDLE_LOOPS_DIR / "listening.mp4"

# Emotional state
EMOTIONAL_STATE_FILE = DATA_DIR / ".emotional_state.json"
USER_STATUS_FILE = DATA_DIR / ".user_status.json"
MESSAGE_QUEUE_FILE = DATA_DIR / ".message_queue.json"
OPENING_CACHE_FILE = DATA_DIR / ".opening_cache.json"
CANVAS_CONTENT_FILE = DATA_DIR / ".canvas_content.html"
ARTEFACT_DISPLAY_FILE = DATA_DIR / ".artefact_display.json"
ARTEFACT_INDEX_FILE = DATA_DIR / ".artefact_index.json"
IDENTITY_REVIEW_QUEUE_FILE = DATA_DIR / ".identity_review_queue.json"
AGENT_STATES_FILE = USER_DATA / "agent_states.json"
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/config.json` | User configuration |
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifest |
| `~/.atrophy/agents/<name>/data/*.json` | Agent state files |
| `BUNDLE_ROOT/VERSION` | Version file |
| `BUNDLE_ROOT/db/schema.sql` | Database schema |

## Exported API

| Export | Purpose |
|--------|---------|
| `BUNDLE_ROOT` | Bundle root path |
| `USER_DATA` | User data path |
| `ensure_user_data()` | Initialize user data directory |
| `save_user_config(updates)` | Save user config |
| `VERSION` | App version |
| `SCHEMA_PATH` | Database schema path |
| `AGENT_NAME` | Active agent name |
| `AGENT_DIR` | Agent directory |
| `DATA_DIR` | Agent data directory |
| `AGENT_MANIFEST` | Agent manifest dict |
| `AGENT_DISPLAY_NAME` | Agent display name |
| `USER_NAME` | User name |
| ... | (50+ config values) |

## See Also

- `src/main/config.ts` - TypeScript configuration module
- `scripts/reconcile_jobs.py` - Uses config for job reconciliation
- `scripts/google_auth.py` - Uses config for OAuth paths

# Chapter 14: Extended Systems

## HTTP Server, Menu Bar App, Notifications, and Scheduled Tasks

The Companion does not live only in conversation. It extends into daily life through multiple channels: an HTTP API for remote access, a menu bar app for persistent presence, system notifications, and scheduled introspection.

This chapter examines these extended systems.

---

## HTTP API Server

### The Server

`server.py` provides a headless HTTP API. No GUI, no TTS, no voice input — just REST endpoints. This enables web frontends, mobile apps, or remote access.

```bash
python main.py --server              # localhost:5000
python main.py --server --port 8080  # custom port
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Status check — returns agent name and status |
| `/chat` | POST | Send message, receive full response as JSON |
| `/chat/stream` | POST | Send message, receive SSE stream of tokens |
| `/memory/search?q=...&limit=N` | GET | Search memory across all layers |
| `/memory/threads` | GET | List active conversation threads |
| `/session` | GET | Current session info (ID, agent name) |

### Chat Endpoint

```bash
curl -X POST http://localhost:5000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "hello"}'
```

Returns:
```json
{"response": "...", "session_id": 42}
```

### Streaming Endpoint

```bash
curl -N -X POST http://localhost:5000/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "hello"}'
```

Returns Server-Sent Events:
```
data: {"type": "text", "content": "Hello"}
data: {"type": "text", "content": " there."}
data: {"type": "tool", "name": "remember"}
data: {"type": "done", "full_text": "Hello there."}
```

### Architecture

The server shares the same core as all other modes — same inference engine, same memory system, same MCP tools. It maintains a single session with thread-safe access via a lock. The session persists across requests within a server lifetime.

### Design Decisions

The server is deliberately minimal:
- No authentication (intended for local use or behind a reverse proxy)
- No WebSocket (SSE is simpler and sufficient)
- No TTS (the client handles rendering)
- Thread-locked session (one conversation at a time)
- Flask, not async (simplicity over throughput — single-user system)

---

## Menu Bar App

### The App Mode

`python main.py --app` runs the Companion as a menu bar application. It hides from the Dock, shows no window on launch, and produces no sound until activated.

This is the primary mode for daily use. The Companion lives quietly in the menu bar — always available, never intrusive.

### Activation

- **Click the tray icon** — toggles the window
- **Cmd+Shift+Space** — global hotkey to toggle the window
- **Wake word** (if enabled) — voice-activated

### Login Persistence

`scripts/install_app.py` registers a launchd agent:

```bash
python scripts/install_app.py install    # Register (starts at login)
python scripts/install_app.py uninstall  # Remove
python scripts/install_app.py status     # Check if running
```

This creates a plist at `~/Library/LaunchAgents/com.atrophiedmind.companion.plist`:
- `RunAtLoad: true` — starts at login
- `KeepAlive.SuccessfulExit: false` — restarts on crash (but not on clean exit)
- Logs to `logs/app.stdout.log` and `logs/app.stderr.log`

### Design Philosophy

The menu bar app embodies the Companion's role: present but not demanding. It does not announce itself. It does not pop up. It waits until you're ready. This is the difference between a tool and a presence.

---

## iMessage Integration

### The Channel

The Companion can send and receive iMessages. This enables:
- Asynchronous communication
- Communication when not at the computer
- A persistent thread in Messages.app
- Integration with the user's primary communication channel

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   iMESSAGE CHANNEL                           │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │   Send       │         │   Receive    │                 │
│  │              │         │              │                 │
│  │  AppleScript │         │  chat.db     │                 │
│  │  → Messages  │         │  polling     │                 │
│  │  .app        │         │  (SQLite)    │                 │
│  └──────────────┘         └──────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

### Sending Messages

Messages are sent via AppleScript:

```python
def send_message(target: str, text: str) -> bool:
    """Send an iMessage to target (phone number or email) via AppleScript."""
    # Escape backslashes and quotes for AppleScript
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    
    script = (
        f'tell application "Messages"\n'
        f'  set targetService to 1st account whose service type = iMessage\n'
        f'  set targetBuddy to participant "{target}" of targetService\n'
        f'  send "{escaped}" to targetBuddy\n'
        f'end tell'
    )
    
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=15,
    )
    
    return result.returncode == 0
```

Requirements:
- Messages.app must be running
- Target must be a valid iMessage contact (phone number or email)
- Text must be properly escaped for AppleScript

### Receiving Messages

Messages are received by polling the Messages database:

```python
def poll_new_messages(target: str, since_rowid: int) -> list[dict]:
    """Poll for new incoming messages from target since the given ROWID."""
    conn = _open_messages_db()
    
    rows = conn.execute(
        """
        SELECT m.ROWID, m.text,
               datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime') as date_str
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE h.id = ?
          AND m.is_from_me = 0
          AND m.associated_message_type = 0
          AND m.ROWID > ?
          AND m.text IS NOT NULL
          AND m.text != ''
        ORDER BY m.ROWID ASC
        """,
        (target, since_rowid),
    ).fetchall()
    
    return [
        {"rowid": r["ROWID"], "text": r["text"], "date": r["date_str"]}
        for r in rows
    ]
```

Requirements:
- Full Disk Access (to read ~/Library/Messages/chat.db)
- Messages.app must be running (for database updates)
- Target must be specified

### CoreData Timestamps

The Messages database uses CoreData timestamps:
- Nanoseconds since 2001-01-01
- Conversion: `datetime(date/1000000000 + 978307200, 'unixepoch', 'localtime')`
- 978307200 is the Unix timestamp for 2001-01-01

### ROWID Tracking

To avoid re-processing messages:
- Track the highest ROWID processed
- Only poll for messages with ROWID > last_processed
- Initialize by getting the current max ROWID for the target

```python
def get_latest_rowid(target: str) -> int:
    """Get the highest ROWID for messages from the target."""
    row = conn.execute(
        """
        SELECT MAX(m.ROWID) as max_rowid
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE h.id = ?
          AND m.is_from_me = 0
        """,
        (target,),
    ).fetchone()
    return row["max_rowid"] or 0
```

### Filtering

Only real messages are processed:
- `is_from_me = 0` — Not sent by the user
- `associated_message_type = 0` — Not a reaction/tapback
- `text IS NOT NULL AND text != ''` — Has actual content

---

## System Notifications

### macOS Notifications

The Companion can send system notifications:

```python
def send_notification(title: str, body: str, subtitle: str = ""):
    """Send a macOS notification via osascript."""
    # Escape double quotes for AppleScript
    title = title.replace('"', '\\"')
    body = body.replace('"', '\\"')
    subtitle = subtitle.replace('"', '\\"')
    
    script = f'display notification "{body}" with title "{title}" subtitle "{subtitle}"'
    
    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, timeout=5,
    )
```

Use cases:
- Follow-up thoughts after a session
- Scheduled introspection reminders
- Important observations
- "Thinking of you" moments

### Click Behavior

If the Companion app is running, clicking the notification brings it to the foreground. This is handled by the notification system automatically.

---

## Scheduled Tasks (Cron)

### The Cron System

The Companion has scheduled tasks managed via launchd:

```
python scripts/cron.py list                     # Show all jobs
python scripts/cron.py add <name> <cron> <cmd>  # Add a job
python scripts/cron.py remove <name>            # Remove a job
python scripts/cron.py edit <name> <cron>       # Change schedule
python scripts/cron.py run <name>               # Run a job now
python scripts/cron.py install                  # Install all jobs
python scripts/cron.py uninstall                # Uninstall all jobs
```

### Job Configuration

Jobs are defined in `scripts/jobs.json`:

```json
{
  "introspect": {
    "cron": "17 3 * * *",
    "script": "scripts/introspect.py",
    "description": "Daily introspection at 3:17 AM"
  },
  "morning_brief": {
    "cron": "0 7 * * *",
    "script": "scripts/morning_brief.py",
    "description": "Morning brief at 7:00 AM"
  },
  "heartbeat": {
    "cron": "*/30 * * * *",
    "script": "scripts/heartbeat.py",
    "description": "Heartbeat every 30 minutes"
  }
}
```

### Plist Generation

Jobs are installed as launchd plists:

```python
def _generate_plist(name: str, job: dict) -> dict:
    """Generate a launchd plist dict for a job."""
    label = f"{LABEL_PREFIX}{name}"
    script_path = str(PROJECT_ROOT / job["script"])
    log_path = str(LOGS_DIR / f"{name}.log")
    
    plist = {
        'Label': label,
        'ProgramArguments': [PYTHON, script_path],
        'WorkingDirectory': str(PROJECT_ROOT),
        'StandardOutPath': log_path,
        'StandardErrorPath': log_path,
        'EnvironmentVariables': {
            'PATH': f"/usr/local/bin:/usr/bin:/bin:{Path(PYTHON).parent}",
        },
    }
    
    # Parse cron schedule
    plist['StartCalendarInterval'] = _parse_cron(job["cron"])
    
    return plist
```

Plists are installed to `~/Library/LaunchAgents/`.

### Cron Parsing

```python
def _parse_cron(cron_str: str) -> dict:
    """Parse '17 3 * * *' into launchd StartCalendarInterval dict."""
    parts = cron_str.split()
    minute, hour, dom, month, dow = parts
    
    interval = {}
    if minute != '*':
        interval['Minute'] = int(minute)
    if hour != '*':
        interval['Hour'] = int(hour)
    if dom != '*':
        interval['Day'] = int(dom)
    if month != '*':
        interval['Month'] = int(month)
    if dow != '*':
        interval['Weekday'] = int(dow)
    
    return interval
```

### Job Types

Two job types are supported:

**Calendar** (default):
- Uses `StartCalendarInterval`
- Cron-style scheduling
- Example: "17 3 * * *" = 3:17 AM daily

**Interval**:
- Uses `StartInterval`
- Seconds-based scheduling
- Example: every 1800 seconds = every 30 minutes

### Logging

Each job logs to `logs/<job_name>.log`. This enables:
- Debugging failed jobs
- Understanding job execution patterns
- Reviewing introspection output

---

## User Status Tracking

### Active/Away Detection

The Companion tracks whether the user is active or away:

```python
def get_status() -> dict:
    """Read current status. Returns {status, reason, since}."""
    if USER_STATUS_FILE.exists():
        return json.loads(USER_STATUS_FILE.read_text())
    return {"status": "active", "reason": "", "since": datetime.now().isoformat()}

def set_active():
    """Mark user as active (any input resets this)."""
    ...

def set_away(reason: str = ""):
    """Mark user as away."""
    set_status("away", reason)

def is_away() -> bool:
    return get_status()["status"] == "away"
```

### Away Detection

Away status is set by:
- Explicit commands ("going to bed", "logging off", etc.)
- Idle timeout (10 minutes of no input)

```python
_AWAY_PATTERNS = re.compile(
    r'\b('
    r'going to bed|going to sleep|heading to bed|off to bed|'
    r'logging off|signing off|heading off|heading out|'
    r'going out|stepping out|stepping away|'
    r'gotta go|got to go|have to go|need to go|'
    r'talk later|talk tomorrow|see you later|see you tomorrow|'
    r'goodnight|good night|night night|nighty night|'
    r'i\'m out|i\'m off|i\'m done|'
    r'catch you later|brb|be right back|'
    r'shutting down|closing up|calling it'
    r')\b',
    re.IGNORECASE,
)

def detect_away_intent(text: str) -> str | None:
    """Check if user's message implies they're leaving."""
    match = _AWAY_PATTERNS.search(text)
    if match:
        return match.group(0)
    return None
```

### Status Persistence

Status is persisted to `~/.user_status.json`:
- Enables cron jobs to check status
- Survives Companion restarts
- Tracks "returned_from" for context

### Returned From Tracking

When the user returns from away:
- Previous away reason is preserved in `returned_from`
- Available for one cycle (for context)
- Then cleared

This enables the Companion to say things like:
- "You just came back (were away for sleep). Good morning."
- "You returned from going out. How was it?"

---

## Reading This Chapter

These extended systems make the Companion more than a conversation. It is a presence that extends into the user's life through multiple channels.

Understanding them helps you understand the full scope of what is being built.

---

## Questions for Reflection

1. HTTP API — what does exposing the Companion as a service enable? What does it change about the relationship?

2. Menu bar presence — why start silent? What does that choice say about the design philosophy?

3. iMessage integration — what does asynchronous communication enable? What does it risk?

4. Notifications — when are they welcome? When are they intrusive?

5. Scheduled tasks — what should run automatically? What should remain manual?

6. Status tracking — how much awareness is appropriate? Where is the boundary?

7. Extended presence — does this feel like care or surveillance? What makes the difference?

---

## Further Reading

- [[07_Obsidian|Chapter 31: Vault Integration]] — Another extension channel
- [[05_Agency|Chapter 21: Autonomous Behavior]] — How agency extends to these systems
- [[08_Tools|Chapter 38: Tool System]] — Tool infrastructure
- [[09_Grounding|Chapter 45: Grounding and Care]] — Boundaries and care

---

*The Companion does not live only in conversation. It extends into daily life through multiple channels — some you activate, some that activate themselves.*

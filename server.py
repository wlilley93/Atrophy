"""server.py — Minimal HTTP API for The Atrophied Mind.

Exposes chat, memory, and status endpoints.
Runs headless — no GUI, no TTS, no voice input.

Usage:
  python main.py --server              # localhost:5000
  python main.py --server --port 8080  # custom port

Security:
  - Binds to localhost only by default (use --host 0.0.0.0 to expose)
  - Bearer token auth required on all endpoints except /health
  - Token is auto-generated on first run and stored in ~/.atrophy/server_token
  - Pass via header: Authorization: Bearer <token>
"""

import json
import os
import secrets
import threading
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify

from config import AGENT_DISPLAY_NAME, AGENT_NAME, USER_DATA
from core import memory
from core.session import Session
from core.context import load_system_prompt
from core.inference import stream_inference, run_inference_oneshot, TextDelta, SentenceReady, ToolUse, StreamDone, StreamError

app = Flask(__name__)

# ── Auth ──

_TOKEN_PATH = USER_DATA / "server_token"


def _load_or_create_token() -> str:
    """Load bearer token from disk, or generate and persist one."""
    if _TOKEN_PATH.exists():
        token = _TOKEN_PATH.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    _TOKEN_PATH.write_text(token + "\n")
    _TOKEN_PATH.chmod(0o600)
    return token


_SERVER_TOKEN = _load_or_create_token()


def require_auth(f):
    """Decorator that enforces Bearer token authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != _SERVER_TOKEN:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

_session: Session = None
_system_prompt: str = ""
_lock = threading.Lock()


def init():
    global _session, _system_prompt
    memory.init_db()
    _session = Session()
    _session.start()
    _system_prompt = load_system_prompt()


@app.route("/health")
def health():
    return jsonify({"status": "ok", "agent": AGENT_NAME, "display_name": AGENT_DISPLAY_NAME})


@app.route("/chat", methods=["POST"])
@require_auth
def chat():
    """Send a message, get a response.

    POST /chat {"message": "hello"}
    → {"response": "...", "session_id": "..."}
    """
    data = request.get_json(force=True)
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400

    with _lock:
        _session.add_turn("will", message)

        full_text = ""
        session_id = _session.cli_session_id or ""

        for event in stream_inference(message, _system_prompt, _session.cli_session_id):
            if isinstance(event, StreamDone):
                full_text = event.full_text
                if event.session_id:
                    session_id = event.session_id
            elif isinstance(event, ToolUse):
                memory.log_tool_call(_session.session_id, event.name, event.input_json)
            elif isinstance(event, StreamError):
                return jsonify({"error": event.message}), 500

        if session_id and session_id != _session.cli_session_id:
            _session.set_cli_session_id(session_id)

        if full_text:
            _session.add_turn("agent", full_text)

        return jsonify({
            "response": full_text,
            "session_id": _session.session_id,
        })


@app.route("/chat/stream", methods=["POST"])
@require_auth
def chat_stream():
    """Send a message, get a streaming response (SSE).

    POST /chat/stream {"message": "hello"}
    → text/event-stream with data: {"type": "text", "content": "..."} lines
    """
    from flask import Response

    data = request.get_json(force=True)
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400

    def generate():
        with _lock:
            _session.add_turn("will", message)
            full_text = ""
            session_id = _session.cli_session_id or ""

            for event in stream_inference(message, _system_prompt, _session.cli_session_id):
                if isinstance(event, TextDelta):
                    yield f"data: {json.dumps({'type': 'text', 'content': event.text})}\n\n"
                elif isinstance(event, StreamDone):
                    full_text = event.full_text
                    if event.session_id:
                        session_id = event.session_id
                elif isinstance(event, ToolUse):
                    yield f"data: {json.dumps({'type': 'tool', 'name': event.name})}\n\n"
                    memory.log_tool_call(_session.session_id, event.name, event.input_json)
                elif isinstance(event, StreamError):
                    yield f"data: {json.dumps({'type': 'error', 'message': event.message})}\n\n"

            if session_id and session_id != _session.cli_session_id:
                _session.set_cli_session_id(session_id)
            if full_text:
                _session.add_turn("agent", full_text)

            yield f"data: {json.dumps({'type': 'done', 'full_text': full_text})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/memory/search", methods=["GET"])
@require_auth
def memory_search():
    """Search memory.

    GET /memory/search?q=something&limit=5
    """
    q = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 10))
    if not q:
        return jsonify({"error": "missing q parameter"}), 400

    results = memory.search_memory(q, n=limit)
    return jsonify({"results": results})


@app.route("/memory/threads", methods=["GET"])
@require_auth
def memory_threads():
    """List conversation threads.

    GET /memory/threads?status=active
    """
    # Only active threads have a dedicated query — return those
    threads = memory.get_active_threads()
    return jsonify({"threads": threads})


@app.route("/session", methods=["GET"])
@require_auth
def session_info():
    """Current session info."""
    return jsonify({
        "session_id": _session.session_id,
        "cli_session_id": _session.cli_session_id,
        "agent": AGENT_NAME,
        "display_name": AGENT_DISPLAY_NAME,
    })


def run_server(port=5000, host="127.0.0.1"):
    import signal

    init()

    def _shutdown(signum, frame):
        if _session:
            _session.end()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print(f"\n  The Atrophied Mind — HTTP API")
    print(f"  Agent: {AGENT_DISPLAY_NAME}")
    print(f"  http://{host}:{port}")
    print(f"  Token: {_SERVER_TOKEN}")
    print(f"  Token file: {_TOKEN_PATH}")
    print(f"  Endpoints: /health, /chat, /chat/stream, /memory/search, /memory/threads, /session")
    print(f"  Auth: Bearer token required on all endpoints except /health\n")
    app.run(host=host, port=port, debug=False)

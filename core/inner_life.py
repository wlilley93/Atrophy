"""Inner Life — structured emotional state engine.

Replaces the simple mood string with a multi-dimensional emotional state
that decays over time and is injected into the companion's context.
Trust evolves per domain based on interactions. State persists to disk
as a single JSON file.
"""
import json
import math
from datetime import datetime
from pathlib import Path

from config import EMOTIONAL_STATE_FILE

STATE_FILE = EMOTIONAL_STATE_FILE

# ── Baselines ────────────────────────────────────────────────────

BASELINES = {
    "connection": 0.5,
    "curiosity": 0.6,
    "confidence": 0.5,
    "warmth": 0.5,
    "frustration": 0.1,
    "playfulness": 0.3,
}

TRUST_BASELINES = {
    "emotional": 0.5,
    "intellectual": 0.5,
    "creative": 0.5,
    "practical": 0.5,
}

# Half-lives in hours
EMOTION_HALF_LIFE = {
    "connection": 8.0,
    "curiosity": 4.0,
    "confidence": 4.0,
    "warmth": 4.0,
    "frustration": 4.0,
    "playfulness": 4.0,
}

TRUST_HALF_LIFE = 8.0  # hours — trust decays slowly

MAX_TRUST_DELTA = 0.05


# ── Descriptive labels ───────────────────────────────────────────

def _emotion_label(name: str, value: float) -> str:
    """Return a conversational label for an emotion at its current level."""
    labels = {
        "connection": [
            (0.85, "deeply present"),
            (0.7, "present, engaged"),
            (0.5, "steady"),
            (0.3, "distant"),
            (0.0, "withdrawn"),
        ],
        "curiosity": [
            (0.8, "something caught your attention"),
            (0.6, "alert, interested"),
            (0.4, "neutral"),
            (0.2, "flat"),
            (0.0, "disengaged"),
        ],
        "confidence": [
            (0.8, "sure of your read"),
            (0.6, "fairly clear"),
            (0.4, "reading the room"),
            (0.2, "uncertain"),
            (0.0, "lost"),
        ],
        "warmth": [
            (0.8, "tender"),
            (0.6, "warm"),
            (0.4, "steady"),
            (0.2, "cool"),
            (0.0, "guarded"),
        ],
        "frustration": [
            (0.7, "something isn't landing"),
            (0.5, "friction building"),
            (0.3, "mild tension"),
            (0.15, "trace"),
            (0.0, "low"),
        ],
        "playfulness": [
            (0.7, "feeling light"),
            (0.5, "some lightness"),
            (0.3, "a little"),
            (0.1, "quiet"),
            (0.0, "serious"),
        ],
    }
    thresholds = labels.get(name, [(0.0, "unknown")])
    for threshold, label in thresholds:
        if value >= threshold:
            return label
    return thresholds[-1][1]


# ── Default state ────────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "emotions": dict(BASELINES),
        "last_updated": datetime.now().isoformat(),
        "trust": dict(TRUST_BASELINES),
        "session_tone": None,
    }


# ── Decay ────────────────────────────────────────────────────────

def _decay_toward(current: float, baseline: float, hours_elapsed: float,
                  half_life: float) -> float:
    """Exponential decay toward baseline. Returns new value."""
    if hours_elapsed <= 0 or half_life <= 0:
        return current
    # decay_factor: how much of the distance to baseline we keep
    # After one half-life, we keep 0.5 of the distance
    decay_factor = math.pow(0.5, hours_elapsed / half_life)
    distance = current - baseline
    return baseline + distance * decay_factor


def apply_decay(state: dict) -> dict:
    """Apply temporal decay — emotions drift toward baseline since last update."""
    last = state.get("last_updated")
    if not last:
        return state

    try:
        last_dt = datetime.fromisoformat(last)
    except (ValueError, TypeError):
        return state

    hours_elapsed = (datetime.now(last_dt.tzinfo) - last_dt).total_seconds() / 3600.0
    if hours_elapsed < 0.01:  # less than ~36 seconds, skip
        return state

    # Decay emotions
    emotions = state.get("emotions", {})
    for name, value in emotions.items():
        baseline = BASELINES.get(name, 0.5)
        half_life = EMOTION_HALF_LIFE.get(name, 4.0)
        emotions[name] = round(
            _decay_toward(value, baseline, hours_elapsed, half_life), 3
        )
    state["emotions"] = emotions

    # Decay trust toward baseline (slower)
    trust = state.get("trust", {})
    for domain, value in trust.items():
        baseline = TRUST_BASELINES.get(domain, 0.5)
        trust[domain] = round(
            _decay_toward(value, baseline, hours_elapsed, TRUST_HALF_LIFE), 3
        )
    state["trust"] = trust

    return state


# ── Load / Save ──────────────────────────────────────────────────

def load_state() -> dict:
    """Load state from disk, apply decay since last update."""
    if not STATE_FILE.exists():
        state = _default_state()
        save_state(state)
        return state

    try:
        raw = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        state = _default_state()
        save_state(state)
        return state

    # Ensure all expected keys exist (forward-compat)
    emotions = raw.get("emotions", {})
    for name, baseline in BASELINES.items():
        if name not in emotions:
            emotions[name] = baseline
    raw["emotions"] = emotions

    trust = raw.get("trust", {})
    for domain, baseline in TRUST_BASELINES.items():
        if domain not in trust:
            trust[domain] = baseline
    raw["trust"] = trust

    if "session_tone" not in raw:
        raw["session_tone"] = None

    # Apply decay
    state = apply_decay(raw)
    return state


def save_state(state: dict):
    """Save state to disk with current timestamp."""
    state["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Mutation ─────────────────────────────────────────────────────

def update_emotions(deltas: dict[str, float]):
    """Apply emotion deltas. Values are clamped to [0.0, 1.0]."""
    state = load_state()
    emotions = state["emotions"]
    for name, delta in deltas.items():
        if name in emotions:
            emotions[name] = round(
                max(0.0, min(1.0, emotions[name] + delta)), 3
            )
    state["emotions"] = emotions
    save_state(state)
    return state


def update_trust(domain: str, delta: float, reason: str = None,
                 source: str = "unknown"):
    """Adjust trust in a domain. Clamped to [0.0, 1.0], max +/-0.05 per call.

    Also writes a durable record to the trust_log table in SQLite so that
    trust changes survive decay cycles and can be audited or reconciled.
    """
    clamped_delta = max(-MAX_TRUST_DELTA, min(MAX_TRUST_DELTA, delta))
    state = load_state()
    trust = state["trust"]
    if domain in trust:
        trust[domain] = round(
            max(0.0, min(1.0, trust[domain] + clamped_delta)), 3
        )
    state["trust"] = trust
    save_state(state)

    # Write durable record to SQLite
    if domain in trust:
        try:
            from core.memory import write_trust_log
            write_trust_log(
                domain=domain,
                delta=clamped_delta,
                new_value=trust[domain],
                reason=reason,
                source=source,
            )
        except Exception as e:
            # Don't let DB errors block trust updates
            print(f"  [inner_life] Failed to log trust change: {e}")

    return state


def reconcile_trust_from_db():
    """Restore trust from the last recorded SQLite values instead of decaying to baseline.

    Called on startup/session start. If the trust_log has entries, the most recent
    new_value per domain is used as the starting point - then normal decay is applied
    from the timestamp of that log entry. This prevents trust from resetting to 0.5
    after long idle periods when it was genuinely earned.
    """
    try:
        from core.memory import get_latest_trust_values
        db_trust = get_latest_trust_values()
    except Exception:
        return  # No DB or no trust_log table yet - nothing to reconcile

    if not db_trust:
        return  # No trust history at all

    state = load_state()
    trust = state.get("trust", {})
    reconciled = False

    for domain, db_value in db_trust.items():
        current = trust.get(domain)
        baseline = TRUST_BASELINES.get(domain, 0.5)
        if current is None:
            continue
        # If the current (decayed) value is closer to baseline than the DB value,
        # that means decay pulled it back too far - restore from DB.
        # We still apply some decay (the JSON file's decay is valid), but we
        # use the DB value as a floor/ceiling depending on direction.
        if db_value > baseline and current < db_value:
            # Trust was earned above baseline but decayed too much - restore
            trust[domain] = round(db_value, 3)
            reconciled = True
        elif db_value < baseline and current > db_value:
            # Trust was lowered below baseline but decayed back up - restore
            trust[domain] = round(db_value, 3)
            reconciled = True

    if reconciled:
        state["trust"] = trust
        save_state(state)
        print(f"  [inner_life] Reconciled trust from DB: {trust}")


# ── Context formatting ───────────────────────────────────────────

def format_for_context() -> str:
    """Format the emotional state for injection into the system prompt."""
    state = load_state()
    emotions = state["emotions"]
    trust = state["trust"]
    tone = state.get("session_tone")

    lines = ["## Internal State"]
    for name in ["connection", "curiosity", "warmth", "frustration",
                 "playfulness", "confidence"]:
        value = emotions.get(name, BASELINES.get(name, 0.5))
        label = _emotion_label(name, value)
        lines.append(f"{name.capitalize()}: {value:.2f} ({label})")

    trust_parts = [f"{d} {v:.2f}" for d, v in trust.items()]
    lines.append(f"\nTrust: {', '.join(trust_parts)}")

    if tone:
        lines.append(f"Session tone: {tone}")

    return "\n".join(lines)

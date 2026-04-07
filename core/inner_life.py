"""Inner Life v2 - structured emotional state engine.

Multi-dimensional emotional state with decay, trust, needs, personality,
and relationship tracking. State persists to disk as a single JSON file.

v2: expanded to 6 categories (emotions, trust, needs, personality,
relationship, drives). Matches the TypeScript inner-life-types.ts.
"""
import json
import math
from datetime import datetime
from pathlib import Path

from config import EMOTIONAL_STATE_FILE, AGENT_DIR

STATE_FILE = EMOTIONAL_STATE_FILE

# ── Emotion baselines and half-lives ─────────────────────────────

BASELINES = {
    "connection": 0.5,
    "curiosity": 0.6,
    "confidence": 0.5,
    "warmth": 0.5,
    "frustration": 0.1,
    "playfulness": 0.3,
    "amusement": 0.2,
    "anticipation": 0.4,
    "satisfaction": 0.4,
    "restlessness": 0.2,
    "tenderness": 0.3,
    "melancholy": 0.1,
    "focus": 0.5,
    "defiance": 0.1,
}

# Aggressive half-lives (matching TypeScript v2)
EMOTION_HALF_LIFE = {
    "connection": 2.0,
    "curiosity": 1.0,
    "confidence": 2.0,
    "warmth": 1.5,
    "frustration": 1.0,
    "playfulness": 0.5,
    "amusement": 0.5,
    "anticipation": 1.5,
    "satisfaction": 3.0,
    "restlessness": 1.0,
    "tenderness": 3.0,
    "melancholy": 4.0,
    "focus": 1.0,
    "defiance": 1.0,
}

# ── Trust baselines and half-lives ───────────────────────────────

TRUST_BASELINES = {
    "emotional": 0.5,
    "intellectual": 0.5,
    "creative": 0.5,
    "practical": 0.5,
    "operational": 0.5,
    "personal": 0.5,
}

TRUST_HALF_LIVES = {
    "emotional": 12.0,
    "intellectual": 12.0,
    "creative": 12.0,
    "practical": 12.0,
    "operational": 24.0,
    "personal": 24.0,
}

MAX_TRUST_DELTA = 0.05

# ── Needs defaults and decay ────────────────────────────────────

NEED_DEFAULTS = {
    "stimulation": 5.0,
    "expression": 5.0,
    "purpose": 5.0,
    "autonomy": 5.0,
    "recognition": 5.0,
    "novelty": 5.0,
    "social": 5.0,
    "rest": 5.0,
}

NEED_DECAY_HOURS = {
    "stimulation": 6.0,
    "expression": 8.0,
    "purpose": 12.0,
    "autonomy": 8.0,
    "recognition": 12.0,
    "novelty": 4.0,
    "social": 6.0,
    "rest": 24.0,
}

# ── Personality defaults ────────────────────────────────────────

PERSONALITY_DEFAULTS = {
    "assertiveness": 0.6,
    "initiative": 0.6,
    "warmth_default": 0.6,
    "humor_style": 0.5,
    "depth_preference": 0.7,
    "directness": 0.65,
    "patience": 0.6,
    "risk_tolerance": 0.5,
}

# ── Relationship defaults and half-lives ────────────────────────

RELATIONSHIP_DEFAULTS = {
    "familiarity": 0.3,
    "rapport": 0.3,
    "reliability": 0.5,
    "boundaries": 0.5,
    "challenge_comfort": 0.3,
    "vulnerability": 0.2,
}

RELATIONSHIP_HALF_LIVES = {
    "familiarity": 168.0,    # 1 week
    "rapport": 72.0,         # 3 days
    "reliability": 168.0,    # 1 week
    "boundaries": 336.0,     # 2 weeks
    "challenge_comfort": 120.0,  # 5 days
    "vulnerability": 120.0,  # 5 days
}


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
            (0.6, "curious"),
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
            (0.4, "neutral"),
            (0.2, "cool"),
            (0.0, "guarded"),
        ],
        "frustration": [
            (0.7, "sharp, frustrated"),
            (0.5, "irritated"),
            (0.3, "mildly annoyed"),
            (0.15, "a twinge"),
            (0.0, "calm"),
        ],
        "playfulness": [
            (0.7, "feeling light"),
            (0.5, "playful"),
            (0.3, "a little"),
            (0.1, "flat"),
            (0.0, "serious"),
        ],
        # v2 emotions
        "amusement": [
            (0.7, "delighted"),
            (0.5, "amused"),
            (0.3, "a hint of humor"),
            (0.1, "dry"),
            (0.0, "unamused"),
        ],
        "anticipation": [
            (0.7, "eager"),
            (0.5, "anticipating"),
            (0.3, "mildly expectant"),
            (0.1, "indifferent"),
            (0.0, "uninterested"),
        ],
        "satisfaction": [
            (0.7, "deeply satisfied"),
            (0.5, "content"),
            (0.3, "somewhat fulfilled"),
            (0.1, "wanting"),
            (0.0, "unsatisfied"),
        ],
        "restlessness": [
            (0.7, "restless, itching to move"),
            (0.5, "antsy"),
            (0.3, "a little fidgety"),
            (0.1, "mostly settled"),
            (0.0, "still"),
        ],
        "tenderness": [
            (0.7, "deeply tender"),
            (0.5, "gentle"),
            (0.3, "softening"),
            (0.1, "neutral"),
            (0.0, "detached"),
        ],
        "melancholy": [
            (0.7, "heavy, melancholic"),
            (0.5, "wistful"),
            (0.3, "a tinge of sadness"),
            (0.1, "faint"),
            (0.0, "clear"),
        ],
        "focus": [
            (0.8, "locked in"),
            (0.6, "focused"),
            (0.4, "attentive"),
            (0.2, "drifting"),
            (0.0, "scattered"),
        ],
        "defiance": [
            (0.7, "defiant"),
            (0.5, "resistant"),
            (0.3, "pushing back a little"),
            (0.1, "mild friction"),
            (0.0, "compliant"),
        ],
    }
    thresholds = labels.get(name, [(0.0, "unknown")])
    for threshold, label in thresholds:
        if value >= threshold:
            return label
    return thresholds[-1][1]


# ── Default state ────────────────────────────────────────────────

def _default_state() -> dict:
    """Return a fresh v2 state with all 6 categories at defaults."""
    return {
        "version": 2,
        "emotions": dict(BASELINES),
        "trust": dict(TRUST_BASELINES),
        "needs": dict(NEED_DEFAULTS),
        "personality": dict(PERSONALITY_DEFAULTS),
        "relationship": dict(RELATIONSHIP_DEFAULTS),
        "session_tone": None,
        "last_updated": datetime.now().isoformat(),
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
    """Apply temporal decay - all categories drift since last update."""
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

    # Decay emotions toward baselines
    emotions = state.get("emotions", {})
    for name, value in emotions.items():
        baseline = BASELINES.get(name, 0.5)
        half_life = EMOTION_HALF_LIFE.get(name, 1.0)
        emotions[name] = round(
            _decay_toward(value, baseline, hours_elapsed, half_life), 3
        )
    state["emotions"] = emotions

    # Decay trust toward baselines (per-domain half-lives)
    trust = state.get("trust", {})
    for domain, value in trust.items():
        baseline = TRUST_BASELINES.get(domain, 0.5)
        half_life = TRUST_HALF_LIVES.get(domain, 12.0)
        trust[domain] = round(
            _decay_toward(value, baseline, hours_elapsed, half_life), 3
        )
    state["trust"] = trust

    # Decay needs toward 0 (depletion model)
    needs = state.get("needs", {})
    for name, value in needs.items():
        half_life = NEED_DECAY_HOURS.get(name, 8.0)
        decay_factor = math.pow(0.5, hours_elapsed / half_life)
        needs[name] = round(value * decay_factor, 3)
    state["needs"] = needs

    # Personality does NOT decay (only changed by evolve.py)

    # Decay relationship toward defaults
    relationship = state.get("relationship", {})
    for dim, value in relationship.items():
        baseline = RELATIONSHIP_DEFAULTS.get(dim, 0.3)
        half_life = RELATIONSHIP_HALF_LIVES.get(dim, 120.0)
        relationship[dim] = round(
            _decay_toward(value, baseline, hours_elapsed, half_life), 3
        )
    state["relationship"] = relationship

    return state


# ── Load / Save ──────────────────────────────────────────────────

def _load_personality_from_manifest() -> dict:
    """Read personality overrides from agent.json if available."""
    try:
        manifest_path = AGENT_DIR / "data" / "agent.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if isinstance(manifest.get("personality"), dict):
                merged = dict(PERSONALITY_DEFAULTS)
                merged.update(manifest["personality"])
                return merged
    except Exception:
        pass
    return dict(PERSONALITY_DEFAULTS)


def load_state() -> dict:
    """Load state from disk, apply decay since last update.

    v1 files (no "version" key) get merged with v2 defaults so new
    categories get default values while existing emotion/trust values
    are preserved.
    """
    if not STATE_FILE.exists():
        state = _default_state()
        # Seed personality from agent manifest
        state["personality"] = _load_personality_from_manifest()
        save_state(state)
        return state

    try:
        raw = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        state = _default_state()
        state["personality"] = _load_personality_from_manifest()
        save_state(state)
        return state

    # Merge emotions - fill in any missing dimensions
    emotions = raw.get("emotions", {})
    for name, baseline in BASELINES.items():
        if name not in emotions:
            emotions[name] = baseline
    raw["emotions"] = emotions

    # Merge trust - fill in new domains
    trust = raw.get("trust", {})
    for domain, baseline in TRUST_BASELINES.items():
        if domain not in trust:
            trust[domain] = baseline
    raw["trust"] = trust

    # Merge needs - new in v2
    needs = raw.get("needs", {})
    for name, default in NEED_DEFAULTS.items():
        if name not in needs:
            needs[name] = default
    raw["needs"] = needs

    # Personality - seed from manifest if state has no personality or all defaults
    personality = raw.get("personality", {})
    if not personality:
        personality = _load_personality_from_manifest()
    else:
        # Fill in any missing traits
        for trait, default in PERSONALITY_DEFAULTS.items():
            if trait not in personality:
                personality[trait] = default
    raw["personality"] = personality

    # Merge relationship - new in v2
    relationship = raw.get("relationship", {})
    for dim, default in RELATIONSHIP_DEFAULTS.items():
        if dim not in relationship:
            relationship[dim] = default
    raw["relationship"] = relationship

    if "session_tone" not in raw:
        raw["session_tone"] = None

    raw["version"] = 2

    # Apply decay
    state = apply_decay(raw)
    return state


def save_state(state: dict):
    """Save state to disk with current timestamp."""
    state["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Mutation ─────────────────────────────────────────────────────

def update_emotions(deltas: dict[str, float], reason: str = None,
                    source: str = "unknown"):
    """Apply emotion deltas. Values are clamped to [0.0, 1.0]."""
    state = load_state()
    emotions = state["emotions"]
    changed = {}
    for name, delta in deltas.items():
        if name in emotions:
            new_val = round(max(0.0, min(1.0, emotions[name] + delta)), 3)
            if new_val != emotions[name]:
                changed[name] = (delta, new_val)
            emotions[name] = new_val
    state["emotions"] = emotions
    save_state(state)
    if changed:
        try:
            from core.memory import write_state_log
            for name, (delta, new_val) in changed.items():
                write_state_log('emotion', name, delta, new_val, reason, source)
        except Exception as e:
            print(f"  [inner_life] Failed to log emotion change: {e}")
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

    # Write durable record to SQLite (both tables - trust_log for reconciliation,
    # state_log for unified cross-category audit trail)
    if domain in trust:
        try:
            from core.memory import write_trust_log, write_state_log
            write_trust_log(
                domain=domain,
                delta=clamped_delta,
                new_value=trust[domain],
                reason=reason,
                source=source,
            )
            write_state_log('trust', domain, clamped_delta, trust[domain],
                            reason, source)
        except Exception as e:
            # Don't let DB errors block trust updates
            print(f"  [inner_life] Failed to log trust change: {e}")

    return state


def update_needs(deltas: dict[str, float], reason: str = None,
                 source: str = "unknown"):
    """Apply need deltas. Values are clamped to [0, 10]."""
    state = load_state()
    needs = state.get("needs", {})
    changed = {}
    for name, delta in deltas.items():
        if name in needs:
            new_val = round(max(0.0, min(10.0, needs[name] + delta)), 3)
            if new_val != needs[name]:
                changed[name] = (delta, new_val)
            needs[name] = new_val
    state["needs"] = needs
    save_state(state)
    if changed:
        try:
            from core.memory import write_state_log
            for name, (delta, new_val) in changed.items():
                write_state_log('need', name, delta, new_val, reason, source)
        except Exception as e:
            print(f"  [inner_life] Failed to log need change: {e}")
    return state


def update_relationship(deltas: dict[str, float], reason: str = None,
                        source: str = "unknown"):
    """Apply relationship deltas. Values are clamped to [0.0, 1.0]."""
    state = load_state()
    relationship = state.get("relationship", {})
    changed = {}
    for dim, delta in deltas.items():
        if dim in relationship:
            new_val = round(max(0.0, min(1.0, relationship[dim] + delta)), 3)
            if new_val != relationship[dim]:
                changed[dim] = (delta, new_val)
            relationship[dim] = new_val
    state["relationship"] = relationship
    save_state(state)
    if changed:
        try:
            from core.memory import write_state_log
            for dim, (delta, new_val) in changed.items():
                write_state_log('relationship', dim, delta, new_val, reason, source)
        except Exception as e:
            print(f"  [inner_life] Failed to log relationship change: {e}")
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
        if db_value > baseline and current < db_value:
            trust[domain] = round(db_value, 3)
            reconciled = True
        elif db_value < baseline and current > db_value:
            trust[domain] = round(db_value, 3)
            reconciled = True

    if reconciled:
        state["trust"] = trust
        save_state(state)
        print(f"  [inner_life] Reconciled trust from DB: {trust}")


# ── Context formatting ───────────────────────────────────────────

def format_for_context() -> str:
    """Format the emotional state for injection into the system prompt.

    Includes all 6 v2 categories. Keeps the verbose format for Python
    (the compressed format is TypeScript-only for now).
    """
    state = load_state()
    emotions = state["emotions"]
    trust = state["trust"]
    tone = state.get("session_tone")

    lines = ["## Internal State"]

    # Emotions - original 6 then v2 additions
    emotion_order = [
        "connection", "curiosity", "warmth", "frustration",
        "playfulness", "confidence",
        "amusement", "anticipation", "satisfaction", "restlessness",
        "tenderness", "melancholy", "focus", "defiance",
    ]
    for name in emotion_order:
        value = emotions.get(name, BASELINES.get(name, 0.5))
        label = _emotion_label(name, value)
        lines.append(f"{name.capitalize()}: {value:.2f} ({label})")

    # Trust
    trust_parts = [f"{d} {v:.2f}" for d, v in trust.items()]
    lines.append(f"\nTrust: {', '.join(trust_parts)}")

    # Needs
    needs = state.get("needs", {})
    if needs:
        need_parts = [f"{n} {v:.1f}" for n, v in needs.items()]
        lines.append(f"Needs: {', '.join(need_parts)}")

    # Relationship
    relationship = state.get("relationship", {})
    if relationship:
        rel_parts = [f"{r} {v:.2f}" for r, v in relationship.items()]
        lines.append(f"Relationship: {', '.join(rel_parts)}")

    if tone:
        lines.append(f"Session tone: {tone}")

    return "\n".join(lines)

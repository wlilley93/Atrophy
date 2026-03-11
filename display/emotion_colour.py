"""Emotion → Colour + Clip mapping for Xan's orb avatar.

Maps response text to a specific video clip and colour. The display system
plays the clip once as a reaction, then reverts to the default ambient loop.

Default ambient: loops/blue/loop_bounce_playful.mp4 (gentle mid-air bob)
Reaction clips:  loops/{colour}/loop_{clip}.mp4 (played once, then revert)

Clip files live at:
    ~/.atrophy/agents/{agent}/avatar/loops/{colour}/loop_{clip}.mp4
"""
from pathlib import Path


# ── Emotion definitions ──
# Each emotion maps to a colour and a specific clip.

EMOTIONS = {
    "thinking": {
        "colour": "dark_blue",
        "clip": "idle_hover",
        "keywords": [],  # triggered programmatically, not by text
    },
    "alert": {
        "colour": "red",
        "clip": "pulse_intense",
        "keywords": [
            "warning", "danger", "urgent", "critical", "alert", "immediately",
            "stop", "protect", "threat", "security", "compromised", "breach",
            "emergency", "do not", "must not", "cannot allow",
        ],
    },
    "frustrated": {
        "colour": "red",
        "clip": "itch",
        "keywords": [
            "error", "failed", "broken", "crash", "bug", "wrong", "problem",
            "issue", "unfortunately", "unable", "can't", "won't work",
            "frustrat", "damn", "annoying",
        ],
    },
    "positive": {
        "colour": "green",
        "clip": "drift_close",
        "keywords": [
            "done", "complete", "success", "great", "excellent", "good",
            "ready", "confirmed", "yes", "perfect", "resolved", "fixed",
            "healthy", "growing", "progress", "well done", "nice",
            "happy", "glad", "proud", "love",
        ],
    },
    "cautious": {
        "colour": "orange",
        "clip": "drift_lateral",
        "keywords": [
            "note", "caution", "cost", "price", "pay", "spend", "budget",
            "careful", "watch out", "heads up", "fyi", "worth noting",
            "trade-off", "consider", "maybe", "possibly", "suggest",
            "however", "but", "although", "risk",
        ],
    },
    "reflective": {
        "colour": "purple",
        "clip": "crystal_shimmer",
        "keywords": [
            "interesting", "philosophical", "wonder", "meaning", "think about",
            "reflects", "deeper", "perspective", "soul", "evolve", "growth",
            "remember when", "looking back", "pattern", "insight", "curious",
            "fascinating", "profound", "existential", "beautiful", "strange",
        ],
    },
}

# Default state
DEFAULT_COLOUR = "blue"
DEFAULT_CLIP = "bounce_playful"
REVERT_TIMEOUT_S = 12  # seconds before reverting to default after a reaction


def classify_emotion(text: str) -> str | None:
    """Classify response text into an emotion name.

    Returns the emotion key (e.g. 'alert', 'positive', 'reflective')
    or None if no strong signal (stay on default).
    """
    if not text:
        return None

    lower = text.lower()
    scores = {}

    for emotion, spec in EMOTIONS.items():
        if not spec["keywords"]:
            continue
        score = 0
        for kw in spec["keywords"]:
            count = lower.count(kw)
            if count > 0:
                score += count * (1 + len(kw) / 10)
        if score > 0:
            scores[emotion] = score

    if not scores:
        return None

    best = max(scores, key=scores.get)
    if scores[best] < 2.0:
        return None

    return best


def get_clip_path(colour: str, clip: str, agent_name: str = "xan") -> Path | None:
    """Get path to a specific clip in a specific colour."""
    base = Path.home() / ".atrophy" / "agents" / agent_name / "avatar" / "loops"
    path = base / colour / f"loop_{clip}.mp4"
    if path.exists():
        return path
    return None


def get_default_loop(agent_name: str = "xan") -> Path | None:
    """Get the default ambient loop (gentle bounce, blue)."""
    return get_clip_path(DEFAULT_COLOUR, DEFAULT_CLIP, agent_name)


def get_reaction(emotion: str) -> tuple[str, str] | None:
    """Get (colour, clip) for an emotion. Returns None if unknown."""
    spec = EMOTIONS.get(emotion)
    if not spec:
        return None
    return (spec["colour"], spec["clip"])

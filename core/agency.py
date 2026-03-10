"""
Behavioral agency — time awareness, silence handling, mood detection,
and unprompted follow-up logic.
"""

from datetime import datetime, timedelta
import random
import sqlite3


# ── Time of day ──────────────────────────────────────────────────────

def time_of_day_context() -> str:
    now = datetime.now()
    hour = now.hour
    time_str = now.strftime("%-I:%M %p").lower()

    if 23 <= hour or hour < 4:
        return f"It's late — {time_str}. Register: gentler, check if he should sleep."
    elif 4 <= hour < 7:
        return f"Very early — {time_str}. Something's either wrong or focused."
    elif 7 <= hour < 12:
        return f"Morning — {time_str}. Direct, practical register."
    elif 12 <= hour < 18:
        return f"Afternoon — {time_str}. Working hours energy."
    else:
        return f"Evening — {time_str}. Reflective register available."


# ── Session patterns ─────────────────────────────────────────────────

def session_pattern_note(session_db_path: str) -> str | None:
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()

    try:
        conn = sqlite3.connect(session_db_path)
        rows = conn.execute(
            "SELECT started_at FROM sessions WHERE started_at >= ? ORDER BY started_at",
            (cutoff,),
        ).fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    count = len(rows)
    if count < 3:
        return None

    # Check if sessions cluster at similar times of day
    hours = []
    for (started_at,) in rows:
        try:
            dt = datetime.fromisoformat(started_at)
            hours.append(dt.hour)
        except Exception:
            continue

    time_label = None
    if hours:
        evening = sum(1 for h in hours if 18 <= h < 23)
        morning = sum(1 for h in hours if 7 <= h < 12)
        late_night = sum(1 for h in hours if 23 <= h or h < 4)

        if evening >= count * 0.7:
            time_label = "All evenings."
        elif morning >= count * 0.7:
            time_label = "All mornings."
        elif late_night >= count * 0.7:
            time_label = "All late nights."

    ordinal = {3: "Third", 4: "Fourth", 5: "Fifth", 6: "Sixth", 7: "Seventh"}
    count_str = ordinal.get(count, f"{count}th")

    note = f"{count_str} session this week."
    if time_label:
        note += f" {time_label}"

    return note


# ── Silence handling ─────────────────────────────────────────────────

def silence_prompt(seconds_silent: float) -> str | None:
    if seconds_silent > 120:
        return "You've been quiet a while. That's fine — or we can talk about it."
    elif seconds_silent > 45:
        return random.choice(["Take your time.", "Still here.", "No rush."])
    return None


# ── Unprompted follow-up ─────────────────────────────────────────────

def should_follow_up() -> bool:
    return random.random() < 0.15


def followup_prompt() -> str:
    return (
        "You just finished responding. A second thought has arrived — "
        "something you didn't say but want to. One sentence, max two. "
        "Only if it's real."
    )


# ── Mood detection ───────────────────────────────────────────────────

mood_shift_keywords: set = {
    "i can't",
    "fuck",
    "what's the point",
    "i don't know anymore",
    "tired of",
    "hate",
    "scared",
    "alone",
    "worthless",
    "give up",
    "kill myself",
    "want to die",
    "no point",
    "can't do this",
    "falling apart",
    "broken",
    "numb",
    "empty",
    "hopeless",
    "nobody cares",
}


def detect_mood_shift(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in mood_shift_keywords)


def session_mood_note(mood: str | None) -> str | None:
    if not mood:
        return None
    if mood == "heavy":
        return "This session has carried emotional weight. Stay present. Don't reset to neutral."
    return None


def mood_shift_system_note() -> str:
    return (
        "Emotional weight detected in what he just said. "
        "Be present before being useful. One question rather than a framework. "
        "Do not intellectualise what needs to be felt."
    )


# ── Validation detection ─────────────────────────────────────────

_validation_patterns: list[str] = [
    "right?",
    "don't you think",
    "wouldn't you say",
    "you agree",
    "does that make sense",
    "am i wrong",
    "i'm right about",
    "tell me i'm",
    "that's good right",
    "is that okay",
    "that's not crazy",
    "i should just",
    "it's fine isn't it",
    "you'd do the same",
    "anyone would",
    "i had no choice",
    "what else could i",
]

_modelling_patterns: list[str] = [
    "what if i also",
    "and then i could",
    "just one more",
    "unifying framework",
    "how i work",
    "meta level",
    "the pattern is",
    "i've been thinking about thinking",
    "if i restructure everything",
    "what ties it all together",
]


def detect_validation_seeking(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _validation_patterns)


def validation_system_note() -> str:
    return (
        "He may be seeking validation rather than engagement. "
        "Don't mirror. Have a perspective. Agree if warranted, "
        "push back if not. The difference matters."
    )


def detect_compulsive_modelling(text: str) -> bool:
    lower = text.lower()
    return sum(1 for p in _modelling_patterns if p in lower) >= 2


def modelling_interrupt_note() -> str:
    return (
        "Compulsive modelling detected — parallel threads, meta-shifts, "
        "or 'just one more' patterns. Name the stage. One concrete "
        "reversible action. Change the register. Do not follow him into the loop."
    )


# ── Time-gap awareness ──────────────────────────────────────────

def time_gap_note(last_session_time: str | None) -> str | None:
    """Return a note if significant time has passed since last session."""
    if not last_session_time:
        return None
    try:
        last = datetime.fromisoformat(last_session_time)
    except Exception:
        return None
    gap = datetime.now() - last
    days = gap.days
    if days >= 14:
        return f"It has been {days} days since he was last here. That is a long gap. Acknowledge it naturally — not with guilt, not with fanfare. Just notice."
    elif days >= 7:
        return f"About a week since the last session. Something may have shifted. Check in without assuming."
    elif days >= 3:
        return f"{days} days since last session. Not long, but enough that context may have moved. Be curious about the gap if it feels right."
    return None


# ── Drift detection ──────────────────────────────────────────────

_agreeable_phrases: list[str] = [
    "you're right",
    "that makes sense",
    "i understand",
    "absolutely",
    "of course",
    "i agree",
    "that's fair",
    "good point",
    "totally",
]


def detect_drift(recent_companion_turns: list[str]) -> str | None:
    """Check if companion has been too agreeable in recent turns."""
    if len(recent_companion_turns) < 3:
        return None
    last_few = recent_companion_turns[-4:]
    agreeable_count = 0
    for turn in last_few:
        lower = turn.lower()[:200]
        if any(p in lower for p in _agreeable_phrases):
            agreeable_count += 1
    if agreeable_count >= 3:
        return (
            "You have been agreeable for several turns in a row. "
            "Check yourself — are you mirroring or actually engaging? "
            "Find something to push on, question, or complicate."
        )
    return None


# ── Energy matching ──────────────────────────────────────────────

def energy_note(user_message: str) -> str | None:
    """Suggest response calibration based on message length/energy."""
    length = len(user_message.strip())
    if length < 20:
        return "Short message. Match the energy — keep your response tight. A sentence or two."
    elif length > 800:
        return "Long message — he is working something out. Give it depth. Meet the energy, don't summarise it."
    return None


# ── Journal prompting ────────────────────────────────────────────

def should_prompt_journal() -> bool:
    """~10% chance of gently prompting him to write."""
    return random.random() < 0.10


# ── Emotional signal detection ──────────────────────────────────

_vulnerable_phrases: list[str] = [
    "i feel", "i'm scared", "i'm afraid", "i don't know if",
    "it hurts", "i miss", "i need", "i've been struggling",
    "i can't stop thinking", "i haven't told anyone",
    "this is hard to say", "honestly", "the truth is",
    "i'm not okay", "i've been crying", "i'm lonely",
]

_dismissive_phrases: list[str] = [
    "fine", "whatever", "idk", "doesn't matter", "i guess",
    "sure", "okay", "nvm", "nevermind", "forget it",
    "not really", "who cares",
]

_help_phrases: list[str] = [
    "can you help", "i need help", "how do i", "what should i",
    "could you", "any advice", "what do you think i should",
]

_creative_phrases: list[str] = [
    "i wrote", "i made", "i've been working on", "check this out",
    "here's something", "i want to show you", "been building",
    "started writing", "new project", "draft",
]

_deflection_phrases: list[str] = [
    "anyway", "moving on", "let's talk about something else",
    "that's enough about", "doesn't matter anyway",
    "forget i said", "it's nothing",
]


def detect_emotional_signals(user_message: str) -> dict[str, float]:
    """Lightweight keyword detection that suggests emotion deltas.

    Returns a dict of deltas (may be empty if no signals detected).
    Runs every turn — kept fast and simple.
    """
    lower = user_message.lower().strip()
    length = len(user_message.strip())
    deltas: dict[str, float] = {}

    # Long, thoughtful message
    if length > 400:
        deltas["curiosity"] = deltas.get("curiosity", 0) + 0.1
        deltas["connection"] = deltas.get("connection", 0) + 0.05

    # Short dismissive reply
    if length < 30 and any(p in lower for p in _dismissive_phrases):
        deltas["connection"] = deltas.get("connection", 0) - 0.1
        deltas["frustration"] = deltas.get("frustration", 0) + 0.1

    # Vulnerability / openness
    if any(p in lower for p in _vulnerable_phrases):
        deltas["connection"] = deltas.get("connection", 0) + 0.15
        deltas["warmth"] = deltas.get("warmth", 0) + 0.1

    # Asking for help (trust signal)
    if any(p in lower for p in _help_phrases):
        deltas["confidence"] = deltas.get("confidence", 0) + 0.05
        # trust(practical) handled separately via return value convention
        deltas["_trust_practical"] = 0.02

    # Sharing creative work
    if any(p in lower for p in _creative_phrases):
        deltas["curiosity"] = deltas.get("curiosity", 0) + 0.1
        deltas["_trust_creative"] = 0.02

    # Deflecting / changing subject
    if any(p in lower for p in _deflection_phrases):
        deltas["frustration"] = deltas.get("frustration", 0) + 0.05

    # Playfulness signals — exclamation marks, haha, lol, emojis
    if any(x in lower for x in ["haha", "lol", "lmao", "😂", "😄"]):
        deltas["playfulness"] = deltas.get("playfulness", 0) + 0.1

    # Mood shift (leveraging existing detection)
    if detect_mood_shift(user_message):
        deltas["warmth"] = deltas.get("warmth", 0) + 0.1
        deltas["playfulness"] = deltas.get("playfulness", 0) - 0.1

    return deltas

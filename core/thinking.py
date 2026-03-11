"""Adaptive thinking - classify message complexity to set inference effort.

Simple heuristic classifier. No ML, no API calls. Runs in <1ms.
"""
import re


# ── HIGH effort signals ──────────────────────────────────────────

_PHILOSOPHICAL_KEYWORDS = [
    "meaning", "purpose", "why do i", "what does it mean",
    "identity", "existence", "consciousness", "feel like",
    "struggling with", "what matters", "who am i",
    "what's the point", "nature of", "free will",
]

_VULNERABILITY_MARKERS = [
    "i'm scared", "i don't know who", "i've been thinking",
    "can't stop", "hurts", "afraid", "ashamed", "lost",
    "i'm not okay", "i don't know anymore", "falling apart",
    "i need to tell you", "haven't told anyone",
    "the truth is", "i've been crying",
]

_META_CONVERSATION = [
    "what do you think about us", "are you real",
    "do you actually", "what are you", "are we",
    "do you feel", "do you remember",
]

_COMPLEX_REASONING = [
    "because", "therefore", "on the other hand", "but what if",
    "the problem is", "i realize", "i've realized",
    "which means", "the thing is", "what i'm trying to say",
    "it's complicated", "i keep coming back to",
]

# ── LOW effort signals ───────────────────────────────────────────

_GREETINGS = {
    "hey", "hi", "hello", "morning", "yo", "sup", "heya",
    "good morning", "good evening", "good night", "gn",
    "evening", "night", "hiya",
}

_ACKNOWLEDGMENTS = {
    "ok", "okay", "sure", "got it", "thanks", "thank you",
    "cool", "nice", "lol", "lmao", "haha", "yep", "yea",
    "yeah", "yes", "no", "nah", "nope", "k", "kk", "bet",
    "word", "true", "fair", "right", "ah", "oh", "hmm",
    "mm", "mhm", "alright",
}

_SIMPLE_QUESTION_PREFIXES = [
    "what time", "how's the weather", "what should i eat",
    "play music", "set a timer", "remind me", "turn on",
    "turn off", "what's the date", "what day is it",
]

# ── Patterns ─────────────────────────────────────────────────────

_QUESTION_RE = re.compile(r'\?')


def _count_questions(text: str) -> int:
    return len(_QUESTION_RE.findall(text))


def _has_any(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def _context_is_deep(recent_context: list[str] | None) -> bool:
    """Check if recent companion turns suggest sustained depth."""
    if not recent_context:
        return False
    # If the last 2+ turns averaged over 300 chars, we're in deep water
    long_turns = sum(1 for t in recent_context[-3:] if len(t) > 300)
    return long_turns >= 2


# ── Main classifier ──────────────────────────────────────────────

def classify_effort(user_message: str, recent_context: list[str] = None) -> str:
    """Classify message complexity and return an effort level.

    Returns: "low", "medium", or "high"

    Fast heuristic only - no inference, no model calls.
    Defaults to "medium" when unsure.
    """
    text = user_message.strip()
    lower = text.lower()
    length = len(text)

    # ── Check LOW signals first (short-circuit for fast responses) ──

    # Very short messages
    if length < 30:
        # Check if it's a greeting
        words = set(lower.rstrip("!.,?").split())
        if words & _GREETINGS:
            return "low"
        # Check if it's a simple acknowledgment
        stripped = lower.rstrip("!.,?").strip()
        if stripped in _ACKNOWLEDGMENTS:
            return "low"

    # Simple commands / questions
    if length < 60 and _has_any(lower, _SIMPLE_QUESTION_PREFIXES):
        return "low"

    # ── Check HIGH signals ──

    high_score = 0

    # Long message
    if length > 300:
        high_score += 2

    # Multiple questions
    if _count_questions(text) > 2:
        high_score += 2

    # Philosophical / abstract
    if _has_any(lower, _PHILOSOPHICAL_KEYWORDS):
        high_score += 2

    # Emotional vulnerability
    if _has_any(lower, _VULNERABILITY_MARKERS):
        high_score += 3

    # Meta-conversation about the relationship
    if _has_any(lower, _META_CONVERSATION):
        high_score += 2

    # Complex reasoning
    reasoning_hits = sum(1 for p in _COMPLEX_REASONING if p in lower)
    if reasoning_hits >= 2:
        high_score += 2
    elif reasoning_hits == 1:
        high_score += 1

    # Context momentum - if recent conversation was deep, maintain it
    if _context_is_deep(recent_context):
        high_score += 1

    # Threshold: need clear signals for high
    if high_score >= 3:
        return "high"

    # ── Default to MEDIUM ──
    return "medium"

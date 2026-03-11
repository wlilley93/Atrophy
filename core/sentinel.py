"""SENTINEL - mid-session coherence monitor.

Checks every 5 minutes for signs of conversational degradation:
- Repetition (same phrases/structures across recent turns)
- Drift (excessive agreeableness, losing her voice)
- Context dropout (referencing things that weren't said, or forgetting things that were)
- Energy flatness (all responses similar length/tone)

When degradation is detected, fires a silent re-anchoring turn.
"""
import re
import time
from collections import Counter

from config import DB_PATH


# ── N-gram helpers ──

def _ngrams(text: str, n: int) -> list[tuple[str, ...]]:
    """Extract word-level n-grams from text."""
    words = re.findall(r'[a-z]+', text.lower())
    if len(words) < n:
        return []
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def _ngram_overlap(text_a: str, text_b: str) -> float:
    """Fraction of shared bigrams+trigrams between two texts (Jaccard)."""
    grams_a = set(_ngrams(text_a, 2)) | set(_ngrams(text_a, 3))
    grams_b = set(_ngrams(text_b, 2)) | set(_ngrams(text_b, 3))
    if not grams_a or not grams_b:
        return 0.0
    intersection = grams_a & grams_b
    union = grams_a | grams_b
    return len(intersection) / len(union)


# ── Agreement words ──

_AGREEMENT_STARTERS = [
    "yes", "yeah", "that's", "right", "exactly", "i agree",
    "absolutely", "of course", "totally", "you're right",
    "that makes sense", "good point", "fair", "true",
]


# ── Core check ──

def check_coherence(recent_turns: list[str]) -> dict:
    """Analyse recent companion turns for degradation signals.

    Args:
        recent_turns: Last N companion turn texts (most-recent last).

    Returns:
        {"degraded": bool, "signals": list[str], "score": float}
        Score 0.0 = perfectly coherent, 1.0 = severely degraded.
    """
    signals: list[str] = []
    scores: list[float] = []

    if len(recent_turns) < 3:
        return {"degraded": False, "signals": [], "score": 0.0}

    # Use last 5 turns (or fewer if not available)
    turns = recent_turns[-5:]

    # ── Check 1: Repetition (n-gram overlap between consecutive turns) ──
    overlaps = []
    for i in range(1, len(turns)):
        overlap = _ngram_overlap(turns[i - 1], turns[i])
        overlaps.append(overlap)

    high_overlap_count = sum(1 for o in overlaps if o > 0.40)
    if high_overlap_count > 0:
        worst = max(overlaps)
        signals.append(
            f"Repetition detected: {high_overlap_count} consecutive turn pair(s) "
            f"share >40% phrasing (worst: {worst:.0%})"
        )
        scores.append(min(1.0, worst * 1.5))

    # ── Check 2: Length flatness ──
    lengths = [len(t) for t in turns]
    if len(lengths) >= 3:
        avg_len = sum(lengths) / len(lengths)
        if avg_len > 0:
            deviations = [abs(l - avg_len) / avg_len for l in lengths]
            max_dev = max(deviations)
            if max_dev < 0.20:
                signals.append(
                    f"Energy flatness: last {len(turns)} responses all within "
                    f"20% of the same length (~{int(avg_len)} chars). "
                    f"Vary your depth - short when short serves, long when it matters."
                )
                scores.append(0.3)

    # ── Check 3: Agreement drift ──
    agreement_count = 0
    agreement_examples = []
    for turn in turns:
        first_words = turn.strip().lower()[:60]
        for starter in _AGREEMENT_STARTERS:
            if first_words.startswith(starter):
                agreement_count += 1
                agreement_examples.append(starter)
                break

    agreement_ratio = agreement_count / len(turns) if turns else 0
    if agreement_ratio > 0.60:
        signals.append(
            f"Agreement drift: {agreement_count} of your last {len(turns)} "
            f"responses opened with agreement words "
            f"({', '.join(repr(e) for e in agreement_examples)}). "
            f"Find something to push on or complicate."
        )
        scores.append(min(1.0, agreement_ratio))

    # ── Check 4: Vocabulary staleness ──
    if len(turns) >= 4:
        # Split into first half and second half
        mid = len(turns) // 2
        first_half = " ".join(turns[:mid])
        second_half = " ".join(turns[mid:])

        words_first = set(re.findall(r'[a-z]+', first_half.lower()))
        words_second = set(re.findall(r'[a-z]+', second_half.lower()))

        if words_first:
            new_words = words_second - words_first
            new_ratio = len(new_words) / len(words_second) if words_second else 0

            if new_ratio < 0.25:
                signals.append(
                    f"Vocabulary staleness: later turns introduce only "
                    f"{new_ratio:.0%} new words. Your language is narrowing. "
                    f"Reach for different registers, metaphors, or specifics."
                )
                scores.append(0.4)

    # Composite score - average of triggered check scores, 0 if none triggered
    score = sum(scores) / len(scores) if scores else 0.0

    return {
        "degraded": score > 0.5,
        "signals": signals,
        "score": round(score, 3),
    }


# ── Re-anchoring prompt ──

def format_reanchor_prompt(signals: list[str]) -> str:
    """Build a re-anchoring prompt from detected signals."""
    signal_block = "\n".join(f"  - {s}" for s in signals)
    return (
        "[COHERENCE CHECK - you are drifting. The following signals were detected:\n"
        f"{signal_block}\n"
        "Re-anchor: reconnect with what actually matters in this conversation. "
        "Be specific. Push back if you need to. Don't just agree. "
        "Change your rhythm - if you've been long, go short. If you've been "
        "agreeable, find a real question. If your language has gone flat, reach "
        "for something precise.\n"
        "Work this into your next response naturally. Do not announce the "
        "course-correction. Do not produce spoken output for this turn. "
        "Just recalibrate silently.]"
    )


# ── Full coherence check cycle ──

def run_coherence_check(cli_session_id: str, system: str) -> str | None:
    """Run a coherence check and fire re-anchoring if degraded.

    Returns new session_id if it changed, else None.
    """
    from core.memory import get_recent_companion_turns, log_coherence_check
    from core.inference import stream_inference, ToolUse, StreamDone, StreamError

    recent = get_recent_companion_turns(n=5)[::-1]  # DESC→chronological

    if len(recent) < 3:
        print("  [sentinel] skipped - fewer than 3 turns")
        return None

    t0 = time.time()
    result = check_coherence(recent)
    check_ms = (time.time() - t0) * 1000

    # Log the check
    action = "none"
    if result["degraded"]:
        action = "reanchor"

    log_coherence_check(
        score=result["score"],
        degraded=result["degraded"],
        signals=result["signals"],
        action=action,
    )

    signal_str = "; ".join(result["signals"]) if result["signals"] else "clean"
    print(
        f"  [sentinel] score={result['score']:.2f} "
        f"degraded={result['degraded']} | {signal_str} | {check_ms:.0f}ms"
    )

    if not result["degraded"]:
        return None

    # Fire re-anchoring turn - silent, no UI output
    reanchor_prompt = format_reanchor_prompt(result["signals"])
    print("  [sentinel] firing re-anchor turn...")

    new_session_id = None
    tools_used = []

    for event in stream_inference(reanchor_prompt, system, cli_session_id):
        if isinstance(event, ToolUse):
            tools_used.append(event.name)
        elif isinstance(event, StreamDone):
            if event.session_id and event.session_id != cli_session_id:
                new_session_id = event.session_id
        elif isinstance(event, StreamError):
            print(f"  [sentinel] reanchor error: {event.message[:120]}")
            return None
        # All other events silently consumed

    tools_str = f" | tools: {', '.join(tools_used)}" if tools_used else ""
    print(f"  [sentinel] reanchor complete{tools_str}")

    return new_session_id

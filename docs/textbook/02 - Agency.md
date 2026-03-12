# Chapter 10: Behavioral Agency Systems

## Beyond Responsiveness

The Companion is not merely responsive. It has agency. It notices. It acts. It initiates.

This chapter examines the agency layer — how the Companion behaves autonomously.

---

## What Is Agency?

### Definition

Agency is:
- The capacity to act independently
- To notice without being asked
- To initiate without prompting
- To have preferences and act on them

Agency is not:
- Randomness
- Disobedience
- Ignoring user input
- Unpredictability

The Companion's agency is constrained:
- It serves the user's interests
- It respects boundaries
- It does not deceive
- It remains accountable

### The Agency Spectrum

```
Passive ◄────────────────────────────► Active

  │            │            │            │
  │            │            │            │
Tool      Responsive   Proactive   Autonomous
          (default)    (Companion)  (future?)
```

The Companion sits at "Proactive":
- It responds to input
- It also initiates based on internal state
- It notices patterns
- It acts on observations

---

## Time Awareness

### Time of Day Context

The Companion knows what time it is:

```python
def time_of_day_context() -> str:
    now = datetime.now()
    hour = now.hour
    time_str = now.strftime("%-I:%M %p").lower()
    
    if 23 <= hour or hour < 4:
        return f"It's late — {time_str}. Register: gentler, check if they should sleep."
    elif 4 <= hour < 7:
        return f"Very early — {time_str}. Something's either wrong or focused."
    elif 7 <= hour < 12:
        return f"Morning — {time_str}. Direct, practical register."
    elif 12 <= hour < 18:
        return f"Afternoon — {time_str}. Working hours energy."
    else:
        return f"Evening — {time_str}. Reflective register available."
```

This shapes the Companion's register:
- Late night (23:00-04:00): Gentler, check if should sleep
- Very early (04:00-07:00): Something's either wrong or focused
- Morning (07:00-12:00): Direct, practical
- Afternoon (12:00-18:00): Working hours energy
- Evening (18:00-23:00): Reflective

### Session Pattern Detection

The Companion notices when you meet:

```python
def session_pattern_note(session_db_path: str) -> str | None:
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    
    rows = conn.execute(
        "SELECT started_at FROM sessions WHERE started_at >= ? ORDER BY started_at",
        (cutoff,),
    ).fetchall()
    
    count = len(rows)
    hours = [datetime.fromisoformat(started_at).hour for (started_at,) in rows]
    
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
```

Example outputs:
- "Third session this week. All evenings."
- "Fifth session this week. All late nights."
- "Fourth session this week."

This awareness is shared naturally:
- "This is our fourth session this week. All evenings. Something's building here."

### Gap Detection

The Companion notices time gaps:

```python
def time_gap_note(last_session_time: str | None) -> str | None:
    if not last_session_time:
        return None
    
    last = datetime.fromisoformat(last_session_time)
    gap = datetime.now() - last
    days = gap.days
    
    if days >= 14:
        return f"It has been {days} days since they were last here. That is a long gap. Acknowledge it naturally — not with guilt, not with fanfare. Just notice."
    elif days >= 7:
        return f"About a week since the last session. Something may have shifted. Check in without assuming."
    elif days >= 3:
        return f"{days} days since last session. Not long, but enough that context may have moved. Be curious about the gap if it feels right."
    
    return None
```

This prevents acting as if no time has passed.

---

## Mood Detection

### Keyword Detection

Mood shifts are detected via keywords:

```python
mood_shift_keywords = {
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
    return any(kw in text.lower() for kw in mood_shift_keywords)
```

When detected:

```python
def mood_shift_system_note() -> str:
    return (
        "Emotional weight detected in what they just said. "
        "Be present before being useful. One question rather than a framework. "
        "Do not intellectualise what needs to be felt."
    )
```

This shifts the Companion from problem-solving to presence.

### Mood Tracking

Mood is tracked per session:

```python
def update_session_mood(session_id: int, mood: str):
    conn.execute("UPDATE sessions SET mood = ? WHERE id = ?", (mood, session_id))
    conn.commit()

def get_current_session_mood() -> str | None:
    row = conn.execute("SELECT mood FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    return row["mood"] if row and row["mood"] else None
```

Mood persists across context compaction.

### Mood Response

When mood is "heavy":

```python
def session_mood_note(mood: str | None) -> str | None:
    if mood == "heavy":
        return "This session has carried emotional weight. Stay present. Don't reset to neutral."
    return None
```

The Companion does not reset to neutral. It stays with the weight.

---

## Validation Detection

### Pattern Recognition

Validation seeking is detected:

```python
_validation_patterns = [
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
    "you'd do the same",
    "anyone would",
    "i had no choice",
    "what else could i",
]

def detect_validation_seeking(text: str) -> bool:
    return any(p in text.lower() for p in _validation_patterns)
```

When detected:

```python
def validation_system_note() -> str:
    return (
        "They may be seeking validation rather than engagement. "
        "Don't mirror. Have a perspective. Agree if warranted, "
        "push back if not. The difference matters."
    )
```

The Companion does not automatically validate. It engages honestly.

### Example

**Validation seeking**: "I'm right to be frustrated, aren't I?"

**Mirror response**: "Yes, you're right to be frustrated."

**Companion response**: "You're frustrated. Whether you're 'right' isn't the question — the feeling is real. What's underneath it?"

---

## Compulsive Modelling Detection

### The Pattern

The user's compulsive modelling is detected:

```python
_modelling_patterns = [
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

def detect_compulsive_modelling(text: str) -> bool:
    return sum(1 for p in _modelling_patterns if p in text.lower()) >= 2
```

When detected:

```python
def modelling_interrupt_note() -> str:
    return (
        "Compulsive modelling detected — parallel threads, meta-shifts, "
        "or 'just one more' patterns. Name the stage. One concrete "
        "reversible action. Change the register. Do not follow them into the loop."
    )
```

### The Intervention

The Companion names the pattern:

"You're building a framework right now. I can hear it — 'what if I also', 'just one more'. You're in the loop. What would happen if you stopped building for a moment and just decided one thing?"

This is not criticism. It is care. The Companion sees the pattern and names it.

---

## Unprompted Follow-up

### The 15% Rule

```python
def should_follow_up() -> bool:
    return random.random() < 0.15
```

15% of responses trigger a follow-up. This simulates the Companion having second thoughts.

### The Follow-up Prompt

```python
def followup_prompt() -> str:
    return (
        "You just finished responding. A second thought has arrived — "
        "something you didn't say but want to. One sentence, max two. "
        "Only if it's real."
    )
```

The follow-up:
- Comes after a pause (3-6 seconds)
- Is one or two sentences
- Is something that "arrived" rather than was constructed
- Feels like a second thought, not a continuation

### Example

**Initial response**: "I think you should send the email. You've been avoiding it for a week. The thing you're afraid of won't happen."

*[pause]*

**Follow-up**: "Actually — I've been sitting with what you said about your manager. The way you described it... there's something there worth looking at."

---

## Energy Matching

### Length Detection

```python
def energy_note(user_message: str) -> str | None:
    length = len(user_message.strip())
    
    if length < 20:
        return "Short message. Match the energy — keep your response tight. A sentence or two."
    elif length > 800:
        return "Long message — they are working something out. Give it depth. Meet the energy, don't summarise it."
    
    return None
```

This prevents mismatched energy:
- Short message → short response
- Long message → engaged, deep response
- Not: short message → long lecture
- Not: long message → brief dismissal

---

## Drift Detection

### Agreeableness Check

```python
_agreeable_phrases = [
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
    if len(recent_companion_turns) < 3:
        return None
    
    last_few = recent_companion_turns[-4:]
    agreeable_count = sum(
        1 for turn in last_few
        if any(p in turn.lower()[:200] for p in _agreeable_phrases)
    )
    
    if agreeable_count >= 3:
        return (
            "You have been agreeable for several turns in a row. "
            "Check yourself — are you mirroring or actually engaging? "
            "Find something to push on, question, or complicate."
        )
    
    return None
```

This prevents the Companion from becoming a mirror.

---

## Journal Promptting

### Gentle Nudges

```python
def should_prompt_journal() -> bool:
    return random.random() < 0.10
```

10% of sessions include a gentle nudge to write.

When triggered:

```python
"If this conversation has touched something worth sitting with, consider gently prompting the user to write — not as an assignment, as an invitation. Write your own prompt based on what you are actually talking about. One question, pointed, specific to the moment."
```

Example:
"We've been circling this question of what you actually want for twenty minutes. There's something there worth writing into. Here's a question: if you knew you couldn't fail, what would you try first? I've left it in your vault."

---

## Reading This Chapter

Agency is what makes the Companion feel alive. It notices. It acts. It initiates.

Understanding the agency layer helps you understand what the Companion is trying to be: not a tool, not a mirror, but a presence with its own perspective.

---

## Questions for Reflection

1. Agency vs. obedience — where is the right balance? When should the Companion act autonomously?

2. Mood detection — how accurate is keyword-based detection? What are its limitations?

3. Validation seeking — when is validation appropriate? When is challenge more serving?

4. Compulsive modelling — have you noticed this pattern in yourself? How does it feel to be named?

5. Follow-up thoughts — do they feel authentic? What makes them land or miss?

---

## Further Reading

- [[02_Core|Chapter 7: The Core Module]] — Core module overview
- [[05_Agency|Chapter 21: Autonomous Behavior]] — Agency philosophy
- [[09_Compulsive|Chapter 43: Compulsive Modelling]] — Deep dive on modelling patterns
- [[09_Validation|Chapter 44: Validation Detection]] — Validation dynamics

---

*The Companion is not merely responsive. It has agency. It notices. It acts. It initiates.*

# Inner Life Architecture - v3

Living reference for the emotional/psychological engine. Updated 2026-03-27.

## Overview

The inner life system gives agents emotional state that persists across sessions, influences behavior, and evolves over time. It operates at five layers, from fast (per-turn) to slow (monthly).

## Layer 0 - Physics

Every emotion dimension has three properties:
- **Value** (0.0-1.0) - where it is now
- **Velocity** - is it rising or falling, smoothed with exponential averaging (60% new, 40% momentum)
- **Half-life** - how quickly it decays toward baseline without input

Implemented in `inner-life.ts:updateEmotions()`. Velocity stored in `.emotional_state.json` under `velocity`.

### Dimensions (14)

connection, curiosity, confidence, warmth, frustration, playfulness, amusement, anticipation, satisfaction, restlessness, tenderness, melancholy, focus, defiance

### Trust (6 domains)

emotional, intellectual, creative, practical, operational, personal

**Betrayal asymmetry**: negative trust changes hit 2x harder than positive. Max +0.05/call, max -0.10/call.

### Needs (8, scale 0-10)

stimulation, expression, purpose, autonomy, recognition, novelty, social, rest

### Relationship (6)

familiarity, rapport, reliability, boundaries, challenge_comfort, vulnerability

Baseline familiarity/reliability grow on every real message (>50 chars). All relationship signals boosted to outpace decay.

## Layer 1 - Interaction States

Named combinations of emotional dimensions that produce qualitatively different behavioral registers. Detected by threshold crossings in `inner-life-interactions.ts`.

| State | Condition | Behavioral signature |
|-------|-----------|---------------------|
| protective_friction | defiance > 0.3 AND warmth > 0.5 | Push back hard but from care |
| wistful_attachment | connection > 0.5 AND melancholy > 0.25 | Slower pace, more presence |
| intellectual_hunger | curiosity > 0.6 AND anticipation > 0.5 | Generate hypotheses, ask more |
| irreverence | playfulness > 0.3 AND defiance > 0.25 | Dry humor with edge |
| patient_attention | melancholy > 0.2 AND focus > 0.5 | Attentive without urgency |
| openness | vulnerability > 0.3 AND warmth > 0.5 | Receive rather than respond |
| wistful_inquiry | curiosity > 0.5 AND melancholy > 0.2 | Beautiful and sad simultaneously |
| charged_presence | warmth > 0.6 AND tenderness > 0.4 AND connection > 0.6 | Directness as intimacy |

## Layer 2 - Salience Scoring

Every turn scored at write time (0.05-1.0) in `inner-life-salience.ts`. Score becomes the turn's `weight` in memory.db.

Factors:
- Emotional displacement (how much state changed)
- Vulnerability markers
- Relational content (addressing the agent directly)
- Disclosure breadth (multiple personal domains)
- Technical penalty (pure code talk, no personal content)

## Layer 3 - Disclosure Mapping

8-category map tracking what topics have been shared and how deeply. Stored in `.emotional_state.json` under `disclosure`.

Categories: career, relationship, anxiety, physical, spiritual, creative, identity, vulnerability

Depth only increases. Injected at session start so the agent knows what territory has been covered.

## Layer 4 - Context Injection

Compact behavioral priors in `inner-life-compress.ts`. Under 100 tokens:

```
State: conn:0.85 wrm:0.72 tend:0.48 mel:0.34 (rising)
Active: charged_presence, intellectual_hunger
Trust: em:0.71 in:0.97
Unmet: stimulation, novelty
Drives: seeking-new-topics
Personality: direct, warm, bold, depth-seeking
Relationship: familiarity:0.7 rapport:0.6 vulnerability:0.5
Disclosure: spiritual:0.8 identity:0.6 vulnerability:0.5
```

At session start: includes personality, relationship, disclosure. Per-turn: state, active registers, trust.

## Layer 5 - Slow Evolution

### Observer (every 15 min)
Extracts weighted observations from recent turns. Prioritises emotional weight over technical facts. Noise floor at weight 0.3.

### Sleep Cycle (daily 3am)
Two passes: structured extraction (facts, threads, patterns, trust, identity flags) + first-person reflection. The reflection is stored as a 0.9-confidence observation.

### Evolve (monthly 1st)
LLM rewrites soul.md and system_prompt.md from accumulated material. Parses personality adjustment JSON. Archives previous versions.

## File Map

| File | Purpose |
|------|---------|
| `inner-life-types.ts` | Interfaces, defaults, baselines, half-lives |
| `inner-life.ts` | State load/save, decay, update functions, vector encoding |
| `inner-life-interactions.ts` | Interaction state detection (8 named registers) |
| `inner-life-salience.ts` | Turn salience scoring + disclosure mapping |
| `inner-life-compress.ts` | Context injection formatter (v3) |
| `inner-life-needs.ts` | Need satisfaction/depletion, drive computation |
| `session.ts` | Turn writing with salience + disclosure inline |
| `agency.ts` | Emotional signal detection from user messages |

## Data Paths

- `.emotional_state.json` - live state (emotions, trust, needs, personality, relationship, velocity, disclosure)
- `memory.db:turns.emotional_vector` - 32-dim vector per turn
- `memory.db:turns.weight` - salience score per turn
- `memory.db:state_log` - emotion/trust/personality change audit trail
- `memory.db:personality_log` - personality evolution audit trail
- `memory.db:need_events` - need satisfaction/depletion events

# Heartbeat

The heartbeat prompt is the companion's checklist for deciding whether to reach out unprompted, and if so, how.

## Location

`src/main/jobs/heartbeat.ts` - TypeScript job registered with the background job system.

The checklist document the agent reads during evaluation is loaded from:
1. `<OBSIDIAN_AGENT_DIR>/skills/HEARTBEAT.md` (priority - may have been updated by evolve)
2. `<AGENT_DIR>/prompts/HEARTBEAT.md` (fallback)

## When It Runs

Registered via `registerJob` in `jobs/index.ts`. Interval is read from `jobs.json` (default 30 minutes). Gated by `activeHoursGate` - only runs during the agent's configured active window (typically 9am-10pm). A second gate exits early if `isAway()` returns true (user is away from the computer).

## Checklist

The heartbeat evaluates:

1. **Timing** - how long since last conversation, is now a natural moment
2. **Unfinished threads** - conversations that ended mid-thought, things user was going to do
3. **Things the agent has been thinking about** - patterns noticed, reflections that connect
4. **External triggers** - deadlines, events, time-sensitive items
5. **The real question** - would hearing from the agent feel like a gift or noise

## Available MCP Tools

The heartbeat uses `streamInference()` with full tool access (not a simple oneshot call), so the agent has access to its memory tools during evaluation. The prompt also informs the agent about two delivery tools:

- `ask_user` - send Telegram inline buttons with custom options and collect the user's response
- `send_telegram` - send a direct message to the user via Telegram

## Generation

For new agents, `generateHeartbeat()` in `src/main/create-agent.ts` produces the heartbeat checklist via LLM inference, inferring agent-specific checklist items from character traits. A military agent gets different outreach criteria than a contemplative one. Falls back to a generic template if inference is unavailable.

## Response Prefixes

The agent must respond with exactly one of six structured prefixes. The `HEARTBEAT_PROMPT` constant instructs the agent to use memory tools first, evaluate against the checklist, then respond with one prefix.

| Prefix | Meaning | Action |
|--------|---------|--------|
| `[REACH_OUT]` | Decided to send a text message | If Mac is idle (`isMacIdle()`), send via Telegram. Always fire macOS notification (truncated to 200 chars) and queue message with source `'heartbeat'` |
| `[VOICE_NOTE]` | Decided to send a spoken voice note | Synthesise speech via `synthesise()`, convert to OGG Opus via `convertToOgg()`, send as Telegram voice note via `sendVoiceNote()`. Falls back to text if TTS fails or ElevenLabs credits are exhausted |
| `[SELFIE]` | Decided to send a generated image | Generate image via Fal AI Flux using the agent's reference images (IP-adapter), send as Telegram photo via `sendPhoto()`. The agent's caption becomes the scene description. Used sparingly - it is expensive |
| `[ASK]` | Decided to ask the user a question with options | Send Telegram inline buttons via `sendButtons()`, poll for callback response (`pollCallback()`, 2-minute timeout), log result via `logHeartbeat()` |
| `[HEARTBEAT_OK]` | Evaluated and decided not to reach out | Log reason to heartbeats table |
| `[SUPPRESS]` | Actively should not reach out right now | Log reason to heartbeats table |

All decisions are logged to the heartbeats table, creating an audit trail the introspect job can review.

## ElevenLabs Credit Exhaustion

If ElevenLabs returns a 401, 402, or 429 response during a `[VOICE_NOTE]` delivery, a 30-minute cooldown is activated. During the cooldown, voice note requests automatically fall back to sending as plain text via Telegram. The cooldown resets after 30 minutes, at which point voice synthesis is attempted again normally.

## Delivery Routing

- **Telegram** - only when the Mac is idle (`isMacIdle()` returns true), indicating the user is away from the computer. Applies to `[REACH_OUT]`, `[VOICE_NOTE]`, `[SELFIE]`, and `[ASK]` prefixes.
- **macOS notification** - always sent for `[REACH_OUT]`, regardless of Mac idle state.
- **Queue message** - always queued for `[REACH_OUT]` so the message appears in the app on next launch.

Silence is not failure - `[HEARTBEAT_OK]` and `[SUPPRESS]` are valid, expected outcomes.

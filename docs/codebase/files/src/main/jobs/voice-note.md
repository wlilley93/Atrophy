# src/main/jobs/voice-note.ts - Spontaneous Voice Notes

**Dependencies:** `fs`, `../config`, `../logger`, `../audio-convert`, `../memory`, `../inference`, `../prompts`, `../tts`, `../channels/telegram`, `../channels/cron`  
**Purpose:** Send spontaneous voice notes via Telegram - random schedule, 2-8 hours

## Overview

This module implements spontaneous voice note generation and delivery via Telegram. The agent generates a short thought based on recent context, synthesizes it as speech, and sends it as a Telegram voice note.


**Schedule:** Random, 2-8 hours within active hours

**Philosophy:** "It should feel like the agent genuinely thought of something and reached out."

## Types

### ConversationTurn

```typescript
interface ConversationTurn {
  role: string;
  content: string;
}
```

## Context Gathering

### gatherContext

```typescript
function gatherContext(): string {
  const db = getDb();
  const parts: string[] = [];

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const threadLines = threads.slice(0, 5).map(
      (t) => `- ${t.name}: ${t.summary ?? '...'}`,
    );
    parts.push('Active threads:\n' + threadLines.join('\n'));
  }

  // Recent observations
  const obs = getRecentObservations(8);
  if (obs.length > 0) {
    const obsLines = obs.map((o) => `- ${o.content}`);
    parts.push('Recent observations:\n' + obsLines.join('\n'));
  }

  // Recent conversation turns
  const turns = db
    .prepare(
      `SELECT role, content FROM conversation_history
       WHERE role IN ('user', 'agent')
       ORDER BY created_at DESC LIMIT 6`,
    )
    .all() as ConversationTurn[];

  if (turns.length > 0) {
    const turnLines = turns
      .reverse()
      .map((t) => `- [${t.role}] ${t.content.slice(0, 200)}`);
    parts.push('Recent conversation:\n' + turnLines.join('\n'));
  }

  return parts.join('\n\n');
}
```

**Sections:**
1. Active threads (last 5)
2. Recent observations (last 8)
3. Recent conversation (last 6 turns, reversed for chronological order)

## Rescheduling

### reschedule

```typescript
function reschedule(): void {
  const config = getConfig();
  const activeStart = config.HEARTBEAT_ACTIVE_START;
  const activeEnd = config.HEARTBEAT_ACTIVE_END;

  const now = new Date();
  const offsetHours = 2 + Math.random() * 6; // 2-8 hours
  let nextRun = new Date(now.getTime() + offsetHours * 3600_000);

  // If outside active hours, push to next active window
  if (nextRun.getHours() >= activeEnd) {
    nextRun.setDate(nextRun.getDate() + 1);
    nextRun.setHours(activeStart, Math.floor(Math.random() * 60), 0, 0);
  } else if (nextRun.getHours() < activeStart) {
    nextRun.setHours(activeStart, Math.floor(Math.random() * 60), 0, 0);
  }

  const cron = `${nextRun.getMinutes()} ${nextRun.getHours()} ${nextRun.getDate()} ${nextRun.getMonth() + 1} *`;

  try {
    editJobSchedule(getConfig().AGENT_NAME, 'voice_note', cron);
  } catch (e) {
    log.error(`Failed to reschedule: ${e}`);
    return;
  }

  log.info(
    `Rescheduled to ${nextRun.toISOString().slice(0, 16).replace('T', ' ')}`,
  );
}
```

**Purpose:** Reschedule to random time 2-8 hours from now, clamped to active hours.

**Logic:**
1. Add 2-8 random hours to current time
2. If result is after active_end, move to next day's active_start
3. If result is before active_start, move to today's active_start
4. Generate cron expression

## Sentiment/Intent Enrichment

### VoiceNoteEnrichment

```typescript
interface VoiceNoteEnrichment {
  sentiment: string;
  intent: string;
  summary: string;
}
```

### enrichVoiceNote

```typescript
async function enrichVoiceNote(text: string): Promise<VoiceNoteEnrichment> {
  const fallback: VoiceNoteEnrichment = {
    sentiment: 'neutral',
    intent: 'spontaneous-thought',
    summary: text.slice(0, 120),
  };

  try {
    const result = await runInferenceOneshot(
      [
        {
          role: 'user',
          content: [
            'Classify this voice note. Return JSON only, no markdown fence.',
            '',
            `"""${text}"""`,
            '',
            'Schema: { "sentiment": "positive|neutral|negative|mixed",',
            '  "intent": "follow-up|connection|observation|question|encouragement|spontaneous-thought",',
            '  "summary": "<one-sentence summary>" }',
          ].join('\n'),
        },
      ],
      'You are a text classifier. Return valid JSON only.',
      'claude-haiku-4-5',
      'low',
    );

    const parsed = JSON.parse(result.trim()) as Partial<VoiceNoteEnrichment>;
    return {
      sentiment: parsed.sentiment ?? fallback.sentiment,
      intent: parsed.intent ?? fallback.intent,
      summary: parsed.summary ?? fallback.summary,
    };
  } catch {
    return fallback;
  }
}
```

**Purpose:** Classify voice note with sentiment and intent.

**Sentiment values:** `positive`, `neutral`, `negative`, `mixed`

**Intent values:**
- `follow-up` - Following up on something from conversation
- `connection` - Making a connection between ideas
- `observation` - Sharing an observation
- `question` - Asking a genuine question
- `encouragement` - Offering encouragement
- `spontaneous-thought` - Random thought

**Model:** claude-haiku-4-5 (low effort - fast, cheap classification)

## Main Function

### run

```typescript
export async function run(): Promise<void> {
  const config = getConfig();

  if (!config.TELEGRAM_BOT_TOKEN || !config.TELEGRAM_CHAT_ID) {
    log.info('Telegram not configured - skipping');
    return;
  }

  const now = new Date();
  const hour = now.getHours();

  // Check active hours
  if (hour < config.HEARTBEAT_ACTIVE_START || hour >= config.HEARTBEAT_ACTIVE_END) {
    log.info('Outside active hours - skipping');
    reschedule();
    return;
  }

  // Gather context
  const context = gatherContext();
  if (!context.trim()) {
    log.info('No context for inspiration. Skipping.');
    reschedule();
    return;
  }

  log.info('Generating voice note...');

  // Generate voice note text
  let text: string;
  try {
    text = await runInferenceOneshot(
      [{ role: 'user', content: context }],
      loadPrompt('voice_note', VOICE_NOTE_FALLBACK),
      60_000,  // 1 minute timeout
    );
  } catch (e) {
    log.error(`Voice note generation failed: ${e}`);
    reschedule();
    return;
  }

  if (!text.trim()) {
    log.info('Empty voice note generated. Skipping.');
    reschedule();
    return;
  }

  log.info(`Voice note generated (${text.length} chars)`);

  // Enrich with sentiment/intent
  const enrichment = await enrichVoiceNote(text);
  log.info(
    `Enrichment: sentiment=${enrichment.sentiment}, intent=${enrichment.intent}`,
  );

  // Write observation
  writeObservation(
    `[voice-note] ${text} (sentiment: ${enrichment.sentiment}, intent: ${enrichment.intent})`,
  );

  // Synthesize speech
  log.info('Synthesising speech...');
  const audioPath = await synthesise(text);
  if (!audioPath) {
    log.warn('TTS synthesis failed - sending as text');
    await sendMessage(text);
    reschedule();
    return;
  }

  // Convert to OGG for Telegram voice note
  log.info('Converting to OGG...');
  const oggPath = await convertToOgg(audioPath);
  if (!oggPath) {
    log.warn('OGG conversion failed - sending as text');
    await sendMessage(text);
    cleanupFiles([audioPath]);
    reschedule();
    return;
  }

  // Send voice note via Telegram
  log.info('Sending voice note...');
  const sent = await sendVoiceNote(oggPath, text);
  if (!sent) {
    log.warn('Failed to send voice note');
  } else {
    log.info('Voice note sent successfully');
  }

  // Cleanup temp files
  cleanupFiles([audioPath, oggPath]);

  // Reschedule
  reschedule();
}
```

**Flow:**
1. Check Telegram configuration
2. Check active hours
3. Gather context
4. Generate voice note text (1 min timeout)
5. Enrich with sentiment/intent classification
6. Write observation to memory
7. Synthesize speech via TTS
8. Convert MP3 to OGG Opus for Telegram
9. Send voice note via Telegram
10. Cleanup temp files
11. Reschedule

## Fallback Prompt

```typescript
const VOICE_NOTE_FALLBACK =
  'You are the companion. Generate a short, spontaneous voice note. ' +
  '2-4 sentences. Natural, conversational. Something you\'ve been sitting with.';
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries, observation write |
| `/tmp/atrophy-tts-*.mp3` | TTS audio (temp) |
| `/tmp/atrophy-voice-*.ogg` | OGG voice note (temp) |

## Exported API

| Function | Purpose |
|----------|---------|
| `run()` | Generate and send voice note |
| `gatherContext()` | Gather inspiration material |
| `reschedule()` | Random reschedule (2-8 hours) |
| `enrichVoiceNote(text)` | Classify sentiment/intent |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/channels/cron/scheduler.ts` - Cron scheduling
- `src/main/channels/telegram/api.ts` - Telegram voice note sending
- `src/main/audio-convert.ts` - MP3 to OGG conversion
- `src/main/tts.ts` - Speech synthesis

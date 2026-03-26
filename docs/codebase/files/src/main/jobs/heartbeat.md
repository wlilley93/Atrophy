# src/main/jobs/heartbeat.ts - Heartbeat Background Job

**Line count:** ~627 lines  
**Dependencies:** `fs`, `os`, `path`, `events`, `../config`, `../memory`, `../inference`, `../context`, `../status`, `../notify`, `../queue`, `../channels/telegram`, `./index`, `../logger`, `../tts`, `../audio-convert`, `./generate-avatar`  
**Purpose:** Periodic check-in evaluation - decides whether to reach out to user unprompted

## Overview

This module implements the heartbeat background job that runs every 30 minutes during active hours. It gathers context about active threads, time since last interaction, and recent session activity, then asks the agent to evaluate whether to reach out unprompted using the HEARTBEAT.md checklist.

**Invocation:** launchd every 30 minutes, or manually via `cron:runNow` IPC

## Heartbeat Prompt

```typescript
const HEARTBEAT_PROMPT =
  '[HEARTBEAT CHECK - internal evaluation, not a conversation]\n\n' +
  'You are deciding whether to reach out to the user unprompted. ' +
  'You have access to your full conversation history and memory tools.\n\n' +
  'First, review your state - use recall, daily_digest, or your memory tools ' +
  'if you need to refresh context. You may also update your HEARTBEAT.md ' +
  'checklist via write_note if your monitoring criteria should evolve.\n\n' +
  '## Available tools during this evaluation\n\n' +
  '- **ask_user** (via the interact tool): Send a question to the user via ' +
  'Telegram with Yes/No/custom buttons. Use for confirmations or choices.\n' +
  '- **send_telegram**: Send a text message direct to the user via Telegram.\n\n' +
  'Then evaluate using the checklist below. Respond with exactly ONE prefix:\n\n' +
  '[REACH_OUT] followed by the message you\'d send.\n\n' +
  '[VOICE_NOTE] followed by the message, spoken naturally as if recording ' +
  'a voice memo. Use this when the thought is personal, warm, or would ' +
  'land better as a voice than text. 2-4 sentences.\n\n' +
  '[SELFIE] followed by a short, playful caption. A photo will be generated ' +
  'and sent. Use SPARINGLY - once every few days at most.\n\n' +
  '[ASK] followed by a question and pipe-separated options. Example:\n' +
  '[ASK] Want me to check in about the project later? | Yes | No | Tomorrow\n\n' +
  '[HEARTBEAT_OK] followed by a brief reason why now isn\'t the right time.\n\n' +
  '[NOTE] followed by a thought you want to leave quietly in Obsidian.\n\n' +
  '[SUPPRESS] followed by a brief reason if you actively shouldn\'t reach out.\n\n' +
  'Keep it short. 1-3 sentences for the message, one line for OK/SUPPRESS.';
```

**Response prefixes:**
- `[REACH_OUT]` - Send text message
- `[VOICE_NOTE]` - Send voice note (falls back to text if unavailable)
- `[SELFIE]` - Generate and send avatar photo
- `[ASK]` - Send interactive button question
- `[HEARTBEAT_OK]` - Don't reach out (good reason)
- `[NOTE]` - Write quiet note to Obsidian
- `[SUPPRESS]` - Actively shouldn't reach out

## Checklist Loader

```typescript
function loadChecklist(): string {
  const config = getConfig();
  const heartbeatPath = path.join(config.OBSIDIAN_AGENT_DIR, 'skills', 'HEARTBEAT.md');
  try {
    if (fs.existsSync(heartbeatPath)) {
      return fs.readFileSync(heartbeatPath, 'utf-8');
    }
  } catch { /* missing file */ }

  // Fallback: check agent prompts dir
  const fallbackPaths = [
    path.join(config.AGENT_DIR, 'prompts', 'HEARTBEAT.md'),
    path.join(BUNDLE_ROOT, 'agents', config.AGENT_NAME, 'prompts', 'heartbeat.md'),
  ];
  for (const fallbackPath of fallbackPaths) {
    try {
      if (fs.existsSync(fallbackPath)) {
        return fs.readFileSync(fallbackPath, 'utf-8');
      }
    } catch { /* missing file */ }
  }

  return '';
}
```

**Search order:**
1. Obsidian skills dir (`~/.atrophy/agents/<name>/skills/HEARTBEAT.md`)
2. Agent prompts dir (`<agent_dir>/prompts/HEARTBEAT.md`)
3. Bundle prompts dir (`<bundle>/agents/<name>/prompts/heartbeat.md`)

## Context Gathering

```typescript
function gatherContext(): string {
  const parts: string[] = [];

  // Time since last interaction
  const lastTime = getLastInteractionTime();
  if (lastTime) {
    parts.push(`## Last interaction\n${lastTime}`);
  }

  // Recent turn count
  const db = getDb();
  const row = db.prepare(
    'SELECT COUNT(*) as cnt FROM turns t ' +
    'JOIN sessions s ON t.session_id = s.id ' +
    'WHERE s.id = (SELECT MAX(id) FROM sessions)'
  ).get() as { cnt: number };
  parts.push(`## Recent session turn count\n${row.cnt} turns`);

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    parts.push('## Active threads\n' + threads.map(t => `- ${t.name}: ${t.summary}`).join('\n'));
  }

  // Recent summaries
  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    parts.push('## Recent session summaries\n' + 
      summaries.map(s => `- ${s.created_at}: ${s.content}`).join('\n'));
  }

  // Recent observations
  const observations = getRecentObservations(5);
  if (observations.length > 0) {
    parts.push('## Recent observations\n' +
      observations.map(o => `- ${o.content}`).join('\n'));
  }

  // Load checklist
  const checklist = loadChecklist();
  if (checklist) {
    parts.push('## Your monitoring checklist\n' + checklist);
  }

  return parts.join('\n\n');
}
```

## Job Registration

```typescript
registerJob({
  name: 'heartbeat',
  description: 'Periodic check-in evaluation',
  gates: [
    activeHoursGate,  // Only run during active hours
    () => {
      // Skip if user is away
      if (isAway()) {
        return 'User is away';
      }
      return null;
    },
    () => {
      // Skip if Mac has been idle for >1 hour
      if (isMacIdle(60 * 60)) {
        return 'Mac idle for >1 hour';
      }
      return null;
    },
  ],
  run: async () => {
    const config = getConfig();
    
    // Gather context
    const context = gatherContext();
    
    // Run inference
    const systemPrompt = loadSystemPrompt();
    const emitter = streamInference(
      `${HEARTBEAT_PROMPT}\n\n${context}`,
      systemPrompt,
      null,  // No CLI session - fresh evaluation
    );
    
    let fullText = '';
    let toolCalls: ToolUseEvent[] = [];
    
    await new Promise<void>((resolve) => {
      emitter.on('event', (evt: InferenceEvent) => {
        switch (evt.type) {
          case 'ToolUse':
            toolCalls.push(evt);
            break;
          case 'StreamDone':
            fullText = evt.fullText;
            resolve();
            break;
          case 'StreamError':
            resolve();
            break;
        }
      });
    });
    
    // Parse response prefix
    const prefixMatch = fullText.match(/^\[(\w+)\]/);
    const prefix = prefixMatch ? prefixMatch[1] : null;
    const message = fullText.replace(/^\[\w+\]\s*/, '').trim();
    
    // Handle response
    let outcome = '';
    switch (prefix) {
      case 'REACH_OUT':
        // Send notification
        sendNotification('Heartbeat', message);
        // Queue message for next app launch
        await queueMessage(message, 'heartbeat');
        outcome = `Sent notification: "${message}"`;
        break;
        
      case 'VOICE_NOTE':
        // Synthesize voice
        const audioPath = await synthesise(message);
        if (audioPath) {
          // Convert to OGG for Telegram
          const oggPath = await convertToOgg(audioPath);
          // Send via Telegram
          await sendVoiceNote(oggPath, message);
          cleanupFiles([audioPath, oggPath]);
          outcome = `Sent voice note: "${message}"`;
        } else {
          // Fallback to text
          await sendTelegram(message);
          outcome = `Sent text (voice unavailable): "${message}"`;
        }
        break;
        
      case 'SELFIE':
        // Generate avatar photo
        const manifest = loadAgentManifest(config.AGENT_NAME);
        const refImages = getReferenceImages(config.AGENT_NAME);
        const falKey = getFalKey();
        
        if (refImages.length > 0 && falKey) {
          const uploaded = await uploadToFal(refImages[0], falKey);
          const generated = await falGenerate(uploaded, message, falKey);
          const downloaded = await downloadImage(generated);
          await sendPhoto(downloaded, message);
          outcome = `Sent selfie: "${message}"`;
        } else {
          outcome = 'Selfie unavailable (no reference images or FAL key)';
        }
        break;
        
      case 'ASK':
        // Parse question and options
        const askMatch = message.match(/^(.+?)\s*\|\s*(.+)/);
        if (askMatch) {
          const question = askMatch[1].trim();
          const options = askMatch[2].split('|').map(s => s.trim());
          await sendButtons(question, options);
          outcome = `Sent question: "${question}"`;
        }
        break;
        
      case 'NOTE':
        // Write to Obsidian
        const notePath = path.join(AGENT_NOTES, 'notes', `heartbeat-${Date.now()}.md`);
        fs.writeFileSync(notePath, `# Heartbeat Note\n\n${message}\n`);
        outcome = `Wrote note to Obsidian`;
        break;
        
      case 'HEARTBEAT_OK':
        outcome = `Skipped: ${message}`;
        break;
        
      case 'SUPPRESS':
        outcome = `Suppressed: ${message}`;
        break;
        
      default:
        outcome = `Unknown response format: ${fullText.slice(0, 100)}`;
    }
    
    // Log heartbeat
    logHeartbeat(prefix || 'UNKNOWN', outcome, message);
    
    return outcome;
  },
});
```

## Gate Checks

The job has three gates that must all pass for execution:

| Gate | Condition | Skip reason |
|------|-----------|-------------|
| `activeHoursGate` | Within configured active hours | "Outside active hours" |
| User away check | `!isAway()` | "User is away" |
| Mac idle check | `!isMacIdle(60 * 60)` | "Mac idle for >1 hour" |

## Response Handling

### REACH_OUT

```typescript
case 'REACH_OUT':
  sendNotification('Heartbeat', message);
  await queueMessage(message, 'heartbeat');
  outcome = `Sent notification: "${message}"`;
  break;
```

**Actions:**
1. Send macOS notification
2. Queue message for next app launch

### VOICE_NOTE

```typescript
case 'VOICE_NOTE':
  const audioPath = await synthesise(message);
  if (audioPath) {
    const oggPath = await convertToOgg(audioPath);
    await sendVoiceNote(oggPath, message);
    cleanupFiles([audioPath, oggPath]);
    outcome = `Sent voice note: "${message}"`;
  } else {
    await sendTelegram(message);
    outcome = `Sent text (voice unavailable): "${message}"`;
  }
  break;
```

**Flow:**
1. Synthesize speech via ElevenLabs
2. Convert MP3 to OGG Opus for Telegram
3. Send via Telegram
4. Clean up temp files
5. Fallback to text if synthesis fails

### SELFIE

```typescript
case 'SELFIE':
  const refImages = getReferenceImages(config.AGENT_NAME);
  const falKey = getFalKey();
  
  if (refImages.length > 0 && falKey) {
    const uploaded = await uploadToFal(refImages[0], falKey);
    const generated = await falGenerate(uploaded, message, falKey);
    const downloaded = await downloadImage(generated);
    await sendPhoto(downloaded, message);
    outcome = `Sent selfie: "${message}"`;
  } else {
    outcome = 'Selfie unavailable (no reference images or FAL key)';
  }
  break;
```

**Flow:**
1. Get reference image
2. Upload to Fal.ai
3. Generate avatar with caption
4. Download generated image
5. Send via Telegram

### ASK

```typescript
case 'ASK':
  const askMatch = message.match(/^(.+?)\s*\|\s*(.+)/);
  if (askMatch) {
    const question = askMatch[1].trim();
    const options = askMatch[2].split('|').map(s => s.trim());
    await sendButtons(question, options);
    outcome = `Sent question: "${question}"`;
  }
  break;
```

**Format:** `[ASK] Question | Option1 | Option2 | Option3`

### NOTE

```typescript
case 'NOTE':
  const notePath = path.join(AGENT_NOTES, 'notes', `heartbeat-${Date.now()}.md`);
  fs.writeFileSync(notePath, `# Heartbeat Note\n\n${message}\n`);
  outcome = `Wrote note to Obsidian`;
  break;
```

**Purpose:** Quiet note in Obsidian - no notification, no chat bubble.

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/skills/HEARTBEAT.md` | Monitoring checklist |
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries |
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued messages |
| `~/.atrophy/agents/<name>/avatar/source/` | Reference images for selfies |
| `/tmp/atrophy-tts-*.mp3` | TTS temp files |
| `/tmp/atrophy-voice-*.ogg` | Converted OGG files |
| `<Obsidian vault>/notes/heartbeat-*.md` | Heartbeat notes |

## Exported API

None - job is registered with `registerJob()` in module init.

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/channels/cron.ts` - Cron scheduler
- `src/main/channels/telegram/api.ts` - Telegram sending functions
- `src/main/jobs/generate-avatar.ts` - Avatar generation for selfies

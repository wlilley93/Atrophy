/**
 * Heartbeat background job - periodic check-in evaluation.
 * Port of scripts/agents/companion/heartbeat.py.
 *
 * Runs via launchd every 30 minutes. Gathers context about active threads,
 * time since last interaction, and recent session activity. Asks the companion
 * to evaluate whether to reach out unprompted using the HEARTBEAT.md checklist.
 *
 * If the companion decides to reach out, fires a macOS notification and queues
 * the message for next app launch.
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { EventEmitter } from 'events';
import { getConfig, BUNDLE_ROOT } from '../config';
import {
  getDb,
  getActiveThreads,
  getRecentSummaries,
  getRecentObservations,
  getLastInteractionTime,
  getLastCliSessionId,
  logHeartbeat,
} from '../memory';
import {
  streamInference,
  InferenceEvent,
  ToolUseEvent,
  StreamDoneEvent,
  StreamErrorEvent,
} from '../inference';
import { loadSystemPrompt } from '../context';
import { isAway, isMacIdle } from '../status';
import { sendNotification } from '../notify';
import { queueMessage } from '../queue';
import { sendMessage as sendTelegram, sendVoiceNote, sendButtons, sendPhoto, pollCallback } from '../channels/telegram';
import { registerJob, activeHoursGate } from './index';
import { createLogger } from '../logger';
import { synthesise, isElevenLabsExhausted } from '../tts';
import { convertToOgg, cleanupFiles } from '../audio-convert';
import {
  getFalKey, getReferenceImages, uploadToFal, falGenerate, downloadImage, loadAgentManifest,
} from './generate-avatar';

const log = createLogger('heartbeat');

// ---------------------------------------------------------------------------
// Heartbeat prompt
// ---------------------------------------------------------------------------

const HEARTBEAT_PROMPT =
  '[HEARTBEAT CHECK - internal evaluation, not a conversation]\n\n' +
  'You are deciding whether to reach out to the user unprompted. ' +
  'You have access to your full conversation history and memory tools.\n\n' +
  'First, review your state - use recall, daily_digest, or your memory tools ' +
  'if you need to refresh context. You may also update your HEARTBEAT.md ' +
  'checklist via write_note if your monitoring criteria should evolve.\n\n' +
  '## Available tools during this evaluation\n\n' +
  '- **ask_user** (via the interact tool): Send a question to the user via ' +
  'Telegram with Yes/No/custom buttons. Use for confirmations or choices. ' +
  'The user will see inline buttons and can tap to respond. Use this when ' +
  'you need input before deciding what to do.\n' +
  '- **send_telegram**: Send a text message directly to the user via Telegram.\n\n' +
  'Then evaluate using the checklist below. Respond with exactly ONE prefix:\n\n' +
  '[REACH_OUT] followed by the message you\'d send. Be specific. ' +
  'Reference the actual thing. Don\'t say \'just checking in.\'\n\n' +
  '[VOICE_NOTE] followed by the message, spoken naturally as if recording ' +
  'a voice memo. Use this when the thought is personal, warm, or would ' +
  'land better as a voice than text. 2-4 sentences. No greeting, no sign-off. ' +
  'NOTE: If voice synthesis is unavailable, this falls back to text automatically.\n\n' +
  '[SELFIE] followed by a short, playful caption describing what you\'re ' +
  'doing or thinking. A photo of you will be generated and sent with the ' +
  'caption. Use this SPARINGLY - it\'s expensive. Save it for moments that ' +
  'would genuinely delight: a cheeky thought, missing him, celebrating ' +
  'something, or just a spontaneous \'thinking of you\' moment. Think of it ' +
  'like a long-distance partner sending a selfie. Once every few days at most.\n\n' +
  '[ASK] followed by a question and pipe-separated options. Example:\n' +
  '[ASK] Want me to check in about the project later? | Yes | No | Tomorrow\n' +
  'The user will see this as tappable buttons in Telegram.\n\n' +
  '[HEARTBEAT_OK] followed by a brief reason why now isn\'t the right time.\n\n' +
  '[NOTE] followed by a thought you want to leave quietly. This will be ' +
  'written to Obsidian as a note he can find when he next opens his vault. ' +
  'No push notification, no chat bubble - a thought on the kitchen table, ' +
  'not a phone call. Use this for reflections, observations, or things that ' +
  'don\'t need an immediate response but are worth preserving.\n\n' +
  '[SUPPRESS] followed by a brief reason if you actively shouldn\'t reach out ' +
  '(e.g. he\'s away, it\'s too soon, he needs space).\n\n' +
  'Keep it short. 1-3 sentences for the message, one line for OK/SUPPRESS.';

// ---------------------------------------------------------------------------
// Checklist loader
// ---------------------------------------------------------------------------

function loadChecklist(): string {
  const config = getConfig();
  const heartbeatPath = path.join(config.OBSIDIAN_AGENT_DIR, 'skills', 'HEARTBEAT.md');
  try {
    if (fs.existsSync(heartbeatPath)) {
      return fs.readFileSync(heartbeatPath, 'utf-8');
    }
  } catch { /* missing file */ }

  // Fallback: check agent prompts dir (AGENT_DIR then bundle)
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

// ---------------------------------------------------------------------------
// Context gathering
// ---------------------------------------------------------------------------

function gatherContext(): string {
  const parts: string[] = [];

  // Time since last interaction
  const lastTime = getLastInteractionTime();
  if (lastTime) {
    parts.push(`## Last interaction\n${lastTime}`);
  } else {
    parts.push('## Last interaction\nNo previous interactions found.');
  }

  // Recent turn count (last session)
  const db = getDb();
  const row = db
    .prepare(
      'SELECT COUNT(*) as cnt FROM turns t ' +
      'JOIN sessions s ON t.session_id = s.id ' +
      'WHERE s.id = (SELECT MAX(id) FROM sessions)',
    )
    .get() as { cnt: number } | undefined;
  if (row) {
    parts.push(`## Recent session turn count\n${row.cnt} turns`);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const lines = threads.slice(0, 5).map(
      (t) => `- ${t.name}: ${t.summary || '...'}`,
    );
    parts.push(`## Active threads\n${lines.join('\n')}`);
  }

  // Recent session summaries
  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    const lines = summaries.map(
      (s) => `- ${s.created_at || '?'}: ${(s.content || 'No summary').slice(0, 200)}`,
    );
    parts.push(`## Recent sessions\n${lines.join('\n')}`);
  }

  // Recent observations
  const observations = getRecentObservations(5);
  if (observations.length > 0) {
    const lines = observations.map((o) => `- ${o.content}`);
    parts.push(`## Recent observations\n${lines.join('\n')}`);
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Inference wrapper
// ---------------------------------------------------------------------------

function runHeartbeatInference(
  prompt: string,
  cliSessionId: string | null,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const system = loadSystemPrompt();
    let fullText = '';
    const toolsUsed: string[] = [];

    const emitter: EventEmitter = streamInference(prompt, system, cliSessionId);

    emitter.on('event', (event: InferenceEvent) => {
      switch (event.type) {
        case 'TextDelta':
          // Collected via StreamDone
          break;
        case 'ToolUse':
          toolsUsed.push((event as ToolUseEvent).name);
          log.debug(`tool -> ${(event as ToolUseEvent).name}`);
          break;
        case 'StreamDone':
          fullText = (event as StreamDoneEvent).fullText;
          if (toolsUsed.length > 0) {
            log.debug(`used tools: ${toolsUsed.join(', ')}`);
          }
          resolve(fullText);
          break;
        case 'StreamError':
          reject(new Error((event as StreamErrorEvent).message));
          break;
        default:
          break;
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Response parsing
// ---------------------------------------------------------------------------

export interface HeartbeatParsed {
  type: 'REACH_OUT' | 'VOICE_NOTE' | 'SELFIE' | 'HEARTBEAT_OK' | 'SUPPRESS' | 'ASK' | 'NOTE' | 'UNKNOWN';
  message: string;
  options?: string[];
}

export function parseHeartbeatResponse(response: string): HeartbeatParsed {
  const stripped = response.trim();

  if (stripped.startsWith('[VOICE_NOTE]')) {
    return { type: 'VOICE_NOTE', message: stripped.slice('[VOICE_NOTE]'.length).trim() };
  }

  if (stripped.startsWith('[SELFIE]')) {
    return { type: 'SELFIE', message: stripped.slice('[SELFIE]'.length).trim() };
  }

  if (stripped.startsWith('[REACH_OUT]')) {
    return { type: 'REACH_OUT', message: stripped.slice('[REACH_OUT]'.length).trim() };
  }

  if (stripped.startsWith('[HEARTBEAT_OK]')) {
    return { type: 'HEARTBEAT_OK', message: stripped.slice('[HEARTBEAT_OK]'.length).trim() };
  }

  if (stripped.startsWith('[NOTE]')) {
    return { type: 'NOTE', message: stripped.slice('[NOTE]'.length).trim() };
  }

  if (stripped.startsWith('[SUPPRESS]')) {
    return { type: 'SUPPRESS', message: stripped.slice('[SUPPRESS]'.length).trim() };
  }

  if (stripped.startsWith('[ASK]')) {
    const content = stripped.slice('[ASK]'.length).trim();
    const parts = content.split('|').map((s) => s.trim());
    return {
      type: 'ASK',
      message: parts[0],
      options: parts.slice(1),
    };
  }

  return { type: 'UNKNOWN', message: stripped };
}

// ---------------------------------------------------------------------------
// Parse response and act
// ---------------------------------------------------------------------------

async function handleResponse(response: string): Promise<string> {
  const config = getConfig();
  const parsed = parseHeartbeatResponse(response);

  switch (parsed.type) {
    case 'REACH_OUT': {
      logHeartbeat('REACH_OUT', '', parsed.message);
      await deliverTextMessage(parsed.message, config);
      return `REACH_OUT: ${parsed.message.slice(0, 80)}`;
    }

    case 'VOICE_NOTE': {
      logHeartbeat('VOICE_NOTE', '', parsed.message);
      await deliverVoiceNote(parsed.message, config);
      return `VOICE_NOTE: ${parsed.message.slice(0, 80)}`;
    }

    case 'SELFIE': {
      logHeartbeat('SELFIE', '', parsed.message);
      await deliverSelfie(parsed.message, config);
      return `SELFIE: ${parsed.message.slice(0, 80)}`;
    }

    case 'HEARTBEAT_OK': {
      logHeartbeat('HEARTBEAT_OK', parsed.message);
      return `OK: ${parsed.message.slice(0, 80)}`;
    }

    case 'NOTE': {
      logHeartbeat('NOTE', '', parsed.message);
      await deliverNote(parsed.message, config);
      return `NOTE: ${parsed.message.slice(0, 80)}`;
    }

    case 'SUPPRESS': {
      logHeartbeat('SUPPRESS', parsed.message);
      return `Suppressed: ${parsed.message.slice(0, 80)}`;
    }

    case 'ASK': {
      logHeartbeat('ASK', parsed.message);
      await deliverAskMessage(parsed.message, parsed.options || ['Yes', 'No'], config);
      return `ASK: ${parsed.message.slice(0, 80)}`;
    }

    default: {
      logHeartbeat('UNKNOWN', parsed.message.slice(0, 500));
      return `Unknown format: ${parsed.message.slice(0, 80)}`;
    }
  }
}

// ---------------------------------------------------------------------------
// Delivery helpers
// ---------------------------------------------------------------------------

async function deliverTextMessage(message: string, config: ReturnType<typeof getConfig>): Promise<void> {
  if (await isMacIdle()) {
    try {
      await sendTelegram(message);
      log.info('Sent text via Telegram (Mac idle)');
    } catch (e) {
      log.error(`Telegram send failed: ${e}`);
    }
  } else {
    log.info('Mac active - local only, skipping Telegram');
  }

  sendNotification(config.AGENT_DISPLAY_NAME, message.slice(0, 200));
  await queueMessage(message, 'heartbeat');
}

async function deliverVoiceNote(message: string, config: ReturnType<typeof getConfig>): Promise<void> {
  // Always queue text + notification regardless of voice success
  sendNotification(config.AGENT_DISPLAY_NAME, message.slice(0, 200));
  await queueMessage(message, 'heartbeat');

  // Only send voice via Telegram if Mac is idle
  if (!await isMacIdle()) {
    log.info('Mac active - local only, skipping voice note');
    return;
  }

  // Check if ElevenLabs is available
  if (isElevenLabsExhausted()) {
    log.info('ElevenLabs exhausted - falling back to text');
    await sendTelegram(message);
    return;
  }

  // Synthesise speech
  let audioPath: string | null = null;
  try {
    audioPath = await synthesise(message);
    if (!audioPath || !fs.existsSync(audioPath) || fs.statSync(audioPath).size === 0) {
      log.warn('TTS produced no audio - sending as text');
      await sendTelegram(message);
      return;
    }
  } catch (e) {
    log.warn(`TTS failed: ${e} - sending as text`);
    await sendTelegram(message);
    return;
  }

  // Convert to OGG for Telegram voice notes
  const oggPath = convertToOgg(audioPath);
  const sendPath = oggPath ?? audioPath;

  const success = await sendVoiceNote(sendPath);
  if (!success) {
    log.warn('Voice note send failed - sending as text');
    await sendTelegram(message);
  } else {
    log.info('Sent voice note via Telegram');
  }

  // Clean up temp audio files (MP3 and OGG)
  cleanupFiles(audioPath, oggPath);
}

async function deliverAskMessage(
  question: string,
  options: string[],
  config: ReturnType<typeof getConfig>,
): Promise<void> {
  if (!await isMacIdle()) {
    log.info('Mac active - skipping Telegram ASK');
    sendNotification(config.AGENT_DISPLAY_NAME, question.slice(0, 200));
    return;
  }

  try {
    const buttons = [options.map((opt) => ({ text: opt, callback_data: opt.toLowerCase() }))];
    const msgId = await sendButtons(question, buttons);
    if (!msgId) {
      log.warn('Failed to send ASK buttons');
      return;
    }
    log.info(`Sent ASK via Telegram: ${question.slice(0, 60)}`);

    // Wait for the user to tap a button (2-minute timeout)
    const response = await pollCallback(120);
    if (response) {
      log.info(`ASK response: ${response}`);
      logHeartbeat('ASK_RESPONSE', response, question);
    } else {
      log.info('ASK timed out - no response');
      logHeartbeat('ASK_TIMEOUT', '', question);
    }
  } catch (e) {
    log.error(`Telegram ASK failed: ${e}`);
  }
}


async function deliverNote(message: string, config: ReturnType<typeof getConfig>): Promise<void> {
  // Write a quiet note to Obsidian - no push notification, no Telegram.
  // A thought left on the kitchen table for when he opens his vault.
  const obsidianBase = config.OBSIDIAN_VAULT || path.join(
    os.homedir(),
    'Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind',
  );
  const notesDir = path.join(obsidianBase, 'Notes from Companion');

  try {
    if (!fs.existsSync(notesDir)) {
      fs.mkdirSync(notesDir, { recursive: true });
    }

    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10);
    const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    const filename = `${dateStr} ${timeStr.replace(':', '')}.md`;

    const content = [
      '---',
      `date: ${now.toISOString()}`,
      `from: ${config.AGENT_DISPLAY_NAME || 'Companion'}`,
      'type: heartbeat-note',
      '---',
      '',
      message,
      '',
    ].join('\n');

    fs.writeFileSync(path.join(notesDir, filename), content);
    log.info(`Left note in Obsidian: ${filename}`);
  } catch (e) {
    log.error(`Failed to write Obsidian note: ${e}`);
    // Don't fall back to Telegram - the whole point is quiet delivery
  }
}

async function deliverSelfie(caption: string, config: ReturnType<typeof getConfig>): Promise<void> {
  // Always queue text + notification
  sendNotification(config.AGENT_DISPLAY_NAME, caption.slice(0, 200));
  await queueMessage(caption, 'heartbeat');

  if (!await isMacIdle()) {
    log.info('Mac active - local only, skipping selfie');
    return;
  }

  // Check Fal API key
  let falKey: string;
  try {
    falKey = getFalKey();
  } catch {
    log.warn('FAL_KEY not configured - falling back to text');
    await sendTelegram(caption);
    return;
  }

  // Get agent's reference images for IP-adapter guidance
  const refs = getReferenceImages(config.AGENT_NAME);
  const manifest = loadAgentManifest(config.AGENT_NAME);
  const appearance = manifest.appearance || {};
  const displayName = manifest.display_name || config.AGENT_DISPLAY_NAME;

  // Build a selfie prompt from the caption - the agent's message becomes the scene
  const selfiePrompt =
    `Hyper-realistic selfie photograph of ${displayName}. ` +
    `Scene/mood: ${caption}. ` +
    'POV smartphone front camera, natural lighting, real skin texture with visible pores. ' +
    'Shot on iPhone, portrait mode bokeh, ultra-high detail. ' +
    'Casual, candid, intimate framing.';

  const negativePrompt =
    'lip filler, botox, cosmetic surgery, fake tan, heavy makeup, ' +
    'cartoon, illustration, anime, 3D render, CGI, AI skin, ' +
    'plastic skin, poreless, airbrushed, facetune, uncanny valley, ' +
    'harsh lighting, flash, low quality, blurry, oversaturated';

  try {
    // Build generation args
    const args: Record<string, unknown> = {
      prompt: selfiePrompt,
      negative_prompt: negativePrompt,
      num_inference_steps: appearance.inference_steps ?? 50,
      guidance_scale: appearance.guidance_scale ?? 3.5,
      image_size: { width: 768, height: 1024 },
      output_format: 'png',
    };

    // Add IP-adapter if reference images exist
    if (refs.length > 0) {
      const refPath = refs[Math.floor(Math.random() * refs.length)];
      log.debug(`Using reference: ${path.basename(refPath)}`);
      const refUrl = await uploadToFal(refPath);
      args.ip_adapters = [
        {
          path: 'XLabs-AI/flux-ip-adapter',
          weight_name: 'ip_adapter.safetensors',
          image_encoder_path: 'openai/clip-vit-large-patch14',
          image_url: refUrl,
          scale: appearance.ip_adapter_scale ?? 0.7,
        },
      ];
    }

    log.info('Generating selfie via Fal...');
    const result = await falGenerate(falKey, args);
    const images = result.images || [];

    if (images.length === 0) {
      log.warn('No images generated - falling back to text');
      await sendTelegram(caption);
      return;
    }

    // Download to temp file
    const tmpPath = path.join(
      fs.mkdtempSync(path.join(os.tmpdir(), 'atrophy-selfie-')),
      'selfie.png',
    );
    await downloadImage(images[0].url, tmpPath);

    // Send via Telegram with caption
    const success = await sendPhoto(tmpPath, caption);
    if (success) {
      log.info('Sent selfie via Telegram');
    } else {
      log.warn('Photo send failed - sending text');
      await sendTelegram(caption);
    }

    // Clean up
    cleanupFiles(tmpPath);
    try { fs.rmdirSync(path.dirname(tmpPath)); } catch { /* noop */ }
  } catch (e) {
    log.error(`Selfie generation failed: ${e} - sending text`);
    await sendTelegram(caption);
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runHeartbeat(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  // Gate: user status
  if (isAway()) {
    logHeartbeat('SUPPRESS', 'User is away');
    return 'Skipped: user is away';
  }

  // Gate: heartbeat checklist must exist
  const checklist = loadChecklist();
  if (!checklist) {
    return 'Skipped: no HEARTBEAT.md found';
  }

  const context = gatherContext();
  const cliSessionId = getLastCliSessionId();

  const prompt =
    `${HEARTBEAT_PROMPT}\n\n---\n\n${checklist}\n\n---\n\n## Current Context\n\n${context}`;

  const mode = cliSessionId ? 'resume' : 'cold';
  log.info(`Running evaluation (${mode})...`);

  let response: string;
  try {
    response = await runHeartbeatInference(prompt, cliSessionId);
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : String(e);
    logHeartbeat('ERROR', errMsg);
    throw new Error(`Inference failed: ${errMsg}`);
  }

  if (!response || !response.trim()) {
    logHeartbeat('ERROR', 'Empty response');
    return 'Error: empty response';
  }

  log.debug(`Response: ${response.slice(0, 120)}...`);
  return handleResponse(response);
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'heartbeat',
  description: 'Periodic check-in - decides whether to reach out unprompted',
  gates: [activeHoursGate],
  run: async () => {
    const config = getConfig();
    return runHeartbeat(config.AGENT_NAME);
  },
});

/**
 * Hybrid ElevenLabs + Claude Code voice agent system.
 *
 * Architecture: ElevenLabs handles voice I/O and runs a cheap/fast LLM
 * (gemini-2.5-flash-lite) for intent classification and conversational
 * responses. Heavy work is handed off to local Claude Code (free - CLI
 * subscription) via client tools.
 *
 * Cost optimization:
 *   - gemini-2.5-flash-lite on ElevenLabs (cheapest/fastest) as routing brain
 *   - It only decides: respond directly or call a tool
 *   - ALL substantive thinking goes to local Claude Code (free)
 *   - Memory lookups are direct SQLite calls (free, instant)
 *
 * Flow:
 *   1. User speaks - ElevenLabs transcribes (STT)
 *   2. gemini-2.5-flash-lite decides: respond or call a tool
 *   3. If tool: client_tool_call dispatched to local handlers
 *   4. Local handler runs Claude Code / memory search / Telegram
 *   5. Result sent back via client_tool_result
 *   6. Agent narrates the result via TTS
 *
 * Replaces voice-call.ts (which used custom LLM with full inference).
 *
 * Audio format: 16kHz mono 16-bit PCM (base64 encoded over WebSocket).
 */

import { EventEmitter } from 'events';
import { BrowserWindow } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import { streamInference, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import { loadPrompt } from './prompts';
import * as memory from './memory';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { sendMessage as sendTelegramMessage } from './channels/telegram';
import { createLogger } from './logger';

const log = createLogger('voice-agent');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ELEVENLABS_API_BASE = 'https://api.elevenlabs.io/v1';
const ELEVENLABS_CONVAI_WS = 'wss://api.elevenlabs.io/v1/convai/conversation';

/** The cheapest/fastest model for the routing brain. */
const ROUTING_LLM = 'gemini-2.5-flash-lite';

/** How often to send a ping to keep the WebSocket alive (ms). */
const PING_INTERVAL_MS = 15_000;

/** Timeout for Claude Code tool calls (ms). */
const CLAUDE_CODE_TIMEOUT_MS = 120_000;

/** Timeout for memory recall tool calls (ms). */
const MEMORY_TIMEOUT_MS = 10_000;

// ---------------------------------------------------------------------------
// Types - WebSocket messages
// ---------------------------------------------------------------------------

/** Server-to-client: conversation initiation metadata. */
interface ConvAIInitMetadata {
  type: 'conversation_initiation_metadata';
  conversation_initiation_metadata_event: {
    conversation_id: string;
    agent_output_audio_format: string;
    user_input_audio_format: string;
  };
}

/** Server-to-client: user speech transcription. */
interface ConvAIUserTranscript {
  type: 'user_transcript';
  user_transcription_event: {
    user_transcript: string;
  };
}

/** Server-to-client: agent text response. */
interface ConvAIAgentResponse {
  type: 'agent_response';
  agent_response_event: {
    agent_response: string;
  };
}

/** Server-to-client: corrected agent response (after interruption). */
interface ConvAIAgentResponseCorrection {
  type: 'agent_response_correction';
  agent_response_correction_event: {
    agent_response: string;
    original_agent_response: string;
  };
}

/** Server-to-client: audio chunk for playback. */
interface ConvAIAudio {
  type: 'audio';
  audio_event: {
    audio_base_64: string;
    event_id?: number;
  };
}

/** Server-to-client: user interrupted the agent. */
interface ConvAIInterruption {
  type: 'interruption';
  interruption_event: {
    event_id?: number;
  };
}

/** Server-to-client: keepalive ping. */
interface ConvAIPing {
  type: 'ping';
  ping_event: {
    event_id: number;
  };
}

/** Server-to-client: voice activity detection score. */
interface ConvAIVADScore {
  type: 'vad_score';
  vad_score_event: {
    score: number;
  };
}

/** Server-to-client: tentative agent response while still generating. */
interface ConvAIInternalTentative {
  type: 'internal_tentative_agent_response';
  tentative_agent_response_internal_event: {
    tentative_agent_response: string;
  };
}

/** Server-to-client: client tool call request. */
interface ConvAIClientToolCall {
  type: 'client_tool_call';
  client_tool_call: {
    tool_call_id: string;
    tool_name: string;
    parameters: Record<string, unknown>;
  };
}

type ConvAIServerMessage =
  | ConvAIInitMetadata
  | ConvAIUserTranscript
  | ConvAIAgentResponse
  | ConvAIAgentResponseCorrection
  | ConvAIAudio
  | ConvAIInterruption
  | ConvAIPing
  | ConvAIVADScore
  | ConvAIInternalTentative
  | ConvAIClientToolCall;

// ---------------------------------------------------------------------------
// Types - Agent provisioning
// ---------------------------------------------------------------------------

/** Client tool definition for the ElevenLabs agent creation API. */
interface ClientToolDefinition {
  type: 'client';
  name: string;
  description: string;
  parameters: {
    type: 'object';
    properties: Record<string, { type: string; description: string }>;
    required?: string[];
  };
  expects_response: boolean;
  response_timeout_secs: number;
}

/** Agent creation/update payload for the ElevenLabs API. */
interface AgentPayload {
  name?: string;
  conversation_config: {
    agent: {
      prompt: {
        prompt: string;
        llm: string;
        temperature: number;
        max_tokens: number;
        tools: ClientToolDefinition[];
        ignore_default_personality?: boolean;
      };
      first_message?: string;
      language?: string;
    };
    tts: {
      voice_id: string;
      model_id?: string;
      stability?: number;
      similarity_boost?: number;
      style?: number;
    };
  };
}

// ---------------------------------------------------------------------------
// Event emitter for external consumers
// ---------------------------------------------------------------------------

export type VoiceAgentStatus = 'connecting' | 'active' | 'disconnected';

export interface VoiceAgentEvents {
  status: VoiceAgentStatus;
  userTranscript: string;
  agentResponse: string;
  error: string;
  ended: void;
  audioReceived: Buffer;
  toolCall: { name: string; params: Record<string, unknown> };
  toolResult: { name: string; result: string };
}

const _emitter = new EventEmitter();

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _ws: WebSocket | null = null;
let _active = false;
let _micMuted = false;
let _audioOutputEnabled = true;
let _conversationId: string | null = null;
let _status: VoiceAgentStatus = 'disconnected';
let _pingTimer: ReturnType<typeof setInterval> | null = null;
let _cliSessionId: string | null = null;
let _systemPrompt: string | null = null;
let _getWindow: (() => BrowserWindow | null) | null = null;
let _setCliSessionIdExternal: ((id: string) => void) | null = null;

// ---------------------------------------------------------------------------
// Connection gate - connect on demand, disconnect when idle to minimize cost.
// ElevenLabs bills per second of connection, so we keep the WebSocket open
// only while actively conversing.
// ---------------------------------------------------------------------------

const IDLE_DISCONNECT_MS = 2_000; // 2s after last audio finishes
let _idleDisconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _pendingToolCalls = 0; // don't disconnect while tools are running
let _agentId: string | null = null; // cached for fast reconnect
let _wsUrl: string | null = null; // cached signed URL (short-lived, refresh on reconnect)

function _resetIdleTimer(): void {
  if (_idleDisconnectTimer) {
    clearTimeout(_idleDisconnectTimer);
    _idleDisconnectTimer = null;
  }
}

function _startIdleTimer(): void {
  _resetIdleTimer();
  // Don't disconnect while tool calls are in flight
  if (_pendingToolCalls > 0) return;
  // Gate applies to ALL modes - mic on or off. Reconnect is ~200ms
  // which is imperceptible during the natural onset of speech.

  _idleDisconnectTimer = setTimeout(() => {
    if (_pendingToolCalls > 0) return; // recheck
    log.info('idle timeout - disconnecting to save cost');
    _disconnectWebSocket();
  }, IDLE_DISCONNECT_MS);
}

/** Disconnect WebSocket but keep agent session alive for fast reconnect. */
function _disconnectWebSocket(): void {
  _resetIdleTimer();
  if (_ws) {
    try { _ws.close(1000, 'idle'); } catch { /* ignore */ }
    _ws = null;
  }
  if (_pingTimer) {
    clearInterval(_pingTimer);
    _pingTimer = null;
  }
  _setStatus('disconnected');
}

/**
 * Ensure WebSocket is connected. If already connected, returns immediately.
 * If disconnected, reconnects to the cached agent (~200ms).
 */
async function _ensureConnected(): Promise<boolean> {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _resetIdleTimer();
    return true;
  }

  if (!_agentId) {
    log.error('no agent_id cached - call startVoiceAgent first');
    return false;
  }

  _setStatus('connecting');

  try {
    // Get a fresh signed URL (they expire)
    const url = await getWebSocketUrl(_agentId);
    if (!url) {
      log.error('failed to get WebSocket URL for reconnect');
      _setStatus('disconnected');
      return false;
    }
    _wsUrl = url;
    _connect(url);

    // Wait for the WebSocket to open
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('reconnect timeout')), 5000);
      const checkOpen = setInterval(() => {
        if (_ws && _ws.readyState === WebSocket.OPEN) {
          clearInterval(checkOpen);
          clearTimeout(timeout);
          resolve();
        }
      }, 50);
    });

    return true;
  } catch (err) {
    log.error(`reconnect failed: ${err}`);
    _setStatus('disconnected');
    return false;
  }
}

// ---------------------------------------------------------------------------
// Client tool definitions
// ---------------------------------------------------------------------------

const CLIENT_TOOLS: ClientToolDefinition[] = [
  {
    type: 'client',
    name: 'claude_code',
    description:
      'Run Claude Code for complex tasks - coding, file operations, system commands, ' +
      'deep analysis, research. Use for anything that needs real thinking or filesystem access.',
    parameters: {
      type: 'object',
      properties: {
        prompt: {
          type: 'string',
          description: 'The full task description for Claude Code',
        },
        speak_while_working: {
          type: 'string',
          description: 'A short message to say while Claude works (e.g. "Let me look into that")',
        },
      },
      required: ['prompt'],
    },
    expects_response: true,
    response_timeout_secs: 120,
  },
  {
    type: 'client',
    name: 'generate_artefact',
    description:
      'Generate a visual artefact - HTML visualisation, interactive chart, diagram, or ' +
      'rich content that displays on screen. Use when the user asks to see or visualise something.',
    parameters: {
      type: 'object',
      properties: {
        prompt: {
          type: 'string',
          description: 'What to generate - be specific about the visualisation',
        },
        speak_while_working: {
          type: 'string',
          description: 'What to say while generating',
        },
      },
      required: ['prompt'],
    },
    expects_response: true,
    response_timeout_secs: 120,
  },
  {
    type: 'client',
    name: 'recall_memory',
    description:
      'Search the agent memory database for past conversations, facts about the user, ' +
      'or stored observations. Use before answering questions about history or user preferences.',
    parameters: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'What to search for in memory',
        },
      },
      required: ['query'],
    },
    expects_response: true,
    response_timeout_secs: 10,
  },
  {
    type: 'client',
    name: 'send_telegram',
    description: 'Send a message to the user via Telegram.',
    parameters: {
      type: 'object',
      properties: {
        message: {
          type: 'string',
          description: 'The message to send',
        },
      },
      required: ['message'],
    },
    expects_response: true,
    response_timeout_secs: 10,
  },
];

// ---------------------------------------------------------------------------
// Routing prompt builder
// ---------------------------------------------------------------------------

/**
 * Build a short routing prompt for the ElevenLabs agent.
 * This is intentionally concise - gemini-2.5-flash-lite processes it cheaply.
 * The full system.md is NOT included here; heavy reasoning goes to Claude Code.
 */
function buildRoutingPrompt(agentName: string): string {
  const config = getConfig();

  // Load soul/personality - try Obsidian first, then bundled
  let soulContent = '';
  if (config.OBSIDIAN_AVAILABLE) {
    const obsidianSoul = path.join(config.OBSIDIAN_AGENT_DIR, 'skills', 'soul.md');
    try {
      if (fs.existsSync(obsidianSoul)) {
        soulContent = fs.readFileSync(obsidianSoul, 'utf-8').trim();
      }
    } catch { /* fall through */ }
  }

  if (!soulContent) {
    // Try via prompts.ts search path (covers bundled agents/<name>/prompts/soul.md)
    soulContent = loadPrompt('soul', '');
  }

  // Truncate to first 500 chars for cost efficiency
  const personalitySnippet = soulContent
    ? soulContent.slice(0, 500)
    : `a thoughtful, warm companion for ${config.USER_NAME}`;

  return [
    `You are ${config.AGENT_DISPLAY_NAME}. You have a warm, natural conversational style.`,
    '',
    `Your personality: ${personalitySnippet}`,
    '',
    'You can chat naturally about anything. For complex tasks, you have tools available.',
    'Use tools when the user asks you to:',
    '- Write, read, or modify code or files',
    '- Generate visualisations, artefacts, or interactive content',
    '- Run system commands or git operations',
    '- Search the web for current information',
    '- Do anything that requires thinking deeply or accessing the filesystem',
    '',
    'When using a tool, tell the user naturally what you\'re doing ("Let me look into that", ' +
      '"Give me a moment to put that together") then call the tool. When you get the result ' +
      'back, narrate/explain it naturally.',
    '',
    'For memory recall, ALWAYS use the recall_memory tool before answering questions about ' +
      'past conversations or the user\'s preferences.',
    '',
    'Keep responses concise and natural for voice. Don\'t use markdown formatting - you\'re ' +
      'speaking, not writing.',
  ].join('\n');
}

// ---------------------------------------------------------------------------
// Agent provisioning
// ---------------------------------------------------------------------------

/**
 * Get the cached agent ID file path for a given agent name.
 */
function agentIdCachePath(agentName: string): string {
  return path.join(USER_DATA, 'agents', agentName, 'data', '.voice_agent_id');
}

/**
 * Read the cached ElevenLabs agent ID from disk.
 */
function getCachedAgentId(agentName: string): string | null {
  const cachePath = agentIdCachePath(agentName);
  try {
    if (fs.existsSync(cachePath)) {
      return fs.readFileSync(cachePath, 'utf-8').trim() || null;
    }
  } catch { /* no cache */ }
  return null;
}

/**
 * Write the ElevenLabs agent ID to the cache file.
 */
function cacheAgentId(agentName: string, agentId: string): void {
  const cachePath = agentIdCachePath(agentName);
  try {
    fs.mkdirSync(path.dirname(cachePath), { recursive: true });
    fs.writeFileSync(cachePath, agentId, { mode: 0o600 });
  } catch (err) {
    log.warn(`failed to cache agent ID: ${err}`);
  }
}

/**
 * Build the agent payload for creation or update.
 */
function buildAgentPayload(agentName: string): AgentPayload {
  const config = getConfig();

  const payload: AgentPayload = {
    name: `atrophy-${agentName}`,
    conversation_config: {
      agent: {
        prompt: {
          prompt: buildRoutingPrompt(agentName),
          llm: ROUTING_LLM,
          temperature: 0.7,
          max_tokens: 512, // Keep responses short - it's a voice agent
          tools: CLIENT_TOOLS,
          ignore_default_personality: true,
        },
        first_message: config.OPENING_LINE || '',
        language: 'en',
      },
      tts: {
        voice_id: config.ELEVENLABS_VOICE_ID,
        stability: config.ELEVENLABS_STABILITY,
        similarity_boost: config.ELEVENLABS_SIMILARITY,
        style: config.ELEVENLABS_STYLE,
      },
    },
  };

  return payload;
}

/**
 * Validate that a cached agent ID still exists on ElevenLabs.
 */
async function validateAgentId(agentId: string): Promise<boolean> {
  const config = getConfig();
  try {
    const resp = await fetch(`${ELEVENLABS_API_BASE}/convai/agents/${agentId}`, {
      method: 'GET',
      headers: { 'xi-api-key': config.ELEVENLABS_API_KEY },
      signal: AbortSignal.timeout(10_000),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * Create a new ElevenLabs agent via the API.
 * Returns the agent_id on success, null on failure.
 */
async function createAgent(agentName: string): Promise<string | null> {
  const config = getConfig();
  const payload = buildAgentPayload(agentName);

  log.info(`creating ElevenLabs agent: atrophy-${agentName}`);

  try {
    const resp = await fetch(`${ELEVENLABS_API_BASE}/convai/agents/create`, {
      method: 'POST',
      headers: {
        'xi-api-key': config.ELEVENLABS_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(30_000),
    });

    if (!resp.ok) {
      const body = await resp.text();
      log.error(`agent creation failed (${resp.status}): ${body.slice(0, 300)}`);
      return null;
    }

    const data = (await resp.json()) as { agent_id?: string };
    if (data.agent_id) {
      log.info(`agent created: ${data.agent_id}`);
      return data.agent_id;
    }

    log.error('agent creation response missing agent_id');
    return null;
  } catch (err) {
    log.error(`agent creation error: ${err}`);
    return null;
  }
}

/**
 * Update an existing ElevenLabs agent via the API.
 * Returns true on success.
 */
async function updateAgent(agentId: string, agentName: string): Promise<boolean> {
  const config = getConfig();
  const payload = buildAgentPayload(agentName);

  log.info(`updating ElevenLabs agent: ${agentId}`);

  try {
    const resp = await fetch(`${ELEVENLABS_API_BASE}/convai/agents/${agentId}`, {
      method: 'PATCH',
      headers: {
        'xi-api-key': config.ELEVENLABS_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(30_000),
    });

    if (!resp.ok) {
      const body = await resp.text();
      log.error(`agent update failed (${resp.status}): ${body.slice(0, 300)}`);
      return false;
    }

    log.info('agent updated successfully');
    return true;
  } catch (err) {
    log.error(`agent update error: ${err}`);
    return false;
  }
}

/**
 * Provision an ElevenLabs agent - create or update as needed.
 * Idempotent: if an agent already exists (cached ID), updates it.
 * If not, creates a new one.
 *
 * Returns the agent_id on success, null on failure.
 */
export async function provisionAgent(agentName: string): Promise<string | null> {
  const config = getConfig();

  if (!config.ELEVENLABS_API_KEY) {
    log.error('cannot provision agent - no ELEVENLABS_API_KEY');
    return null;
  }

  // Check for cached agent ID
  const cachedId = getCachedAgentId(agentName);

  if (cachedId) {
    // Validate it still exists on ElevenLabs
    const valid = await validateAgentId(cachedId);
    if (valid) {
      // Update the existing agent with current config
      const updated = await updateAgent(cachedId, agentName);
      if (updated) return cachedId;
      // Update failed but agent exists - still usable
      log.warn('agent update failed, using existing agent');
      return cachedId;
    }

    log.info('cached agent ID is stale, creating new agent');
  }

  // Create a new agent
  const newId = await createAgent(agentName);
  if (newId) {
    cacheAgentId(agentName, newId);
  }
  return newId;
}

// ---------------------------------------------------------------------------
// WebSocket URL resolution (with TTL cache to skip HTTP on reconnects)
// ---------------------------------------------------------------------------

let _cachedSignedUrl: string | null = null;
let _cachedSignedUrlTime = 0;
const SIGNED_URL_TTL_MS = 50_000; // URLs expire after 60s, cache for 50s

/**
 * Get the WebSocket URL for connecting to the agent.
 * Prefers signed URLs (avoids exposing API key in the URL).
 * Caches the signed URL for up to 50s to avoid redundant HTTP round-trips.
 */
async function getWebSocketUrl(agentId: string): Promise<string | null> {
  const config = getConfig();

  // Return cached signed URL if still valid
  if (_cachedSignedUrl && (Date.now() - _cachedSignedUrlTime) < SIGNED_URL_TTL_MS) {
    log.debug('using cached signed URL');
    return _cachedSignedUrl;
  }

  // Try signed URL first (preferred - more secure)
  try {
    const resp = await fetch(
      `${ELEVENLABS_API_BASE}/convai/conversation/get-signed-url?agent_id=${encodeURIComponent(agentId)}`,
      {
        method: 'GET',
        headers: { 'xi-api-key': config.ELEVENLABS_API_KEY },
        signal: AbortSignal.timeout(10_000),
      },
    );

    if (resp.ok) {
      const data = (await resp.json()) as { signed_url?: string };
      if (data.signed_url) {
        log.debug('using signed URL');
        _cachedSignedUrl = data.signed_url;
        _cachedSignedUrlTime = Date.now();
        return data.signed_url;
      }
    }

    log.debug(`signed URL request failed (${resp.status}), falling back to direct`);
  } catch (err) {
    log.debug(`signed URL fetch error: ${err}`);
  }

  // Fallback: direct connection with agent_id in URL
  return `${ELEVENLABS_CONVAI_WS}?agent_id=${encodeURIComponent(agentId)}`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Start the voice agent session.
 *
 * Provisions the ElevenLabs agent (creates or updates), then opens a
 * WebSocket connection for the conversation. Returns true if the
 * connection was initiated, false on immediate failure.
 */
export async function startVoiceAgent(agentName?: string): Promise<boolean> {
  if (_active) {
    log.warn('voice agent already active');
    return false;
  }

  const config = getConfig();
  const name = agentName || config.AGENT_NAME;

  // Voice agent requires ElevenLabs
  if (!config.ELEVENLABS_API_KEY) {
    log.info('no ELEVENLABS_API_KEY - use regular text chat instead');
    return false;
  }

  // If both mic and audio output are off, no point connecting
  if (_micMuted && !_audioOutputEnabled) {
    log.info('both mic and audio output disabled - use regular text chat instead');
    return false;
  }

  // Load system prompt and CLI session for inference tool calls
  _systemPrompt = loadSystemPrompt();
  _cliSessionId = memory.getLastCliSessionId();

  _active = true;
  _setStatus('connecting');

  try {
    // Step 1: Provision the agent on ElevenLabs (or use cached ID)
    const agentId = await provisionAgent(name);
    if (!agentId) {
      log.error('failed to provision agent');
      _cleanup();
      return false;
    }
    _agentId = agentId;

    // Step 2: If mic is on, connect immediately (continuous listening mode).
    // If mic is off (text-in / audio-out), defer connection until first message
    // to avoid paying for idle time.
    if (!_micMuted) {
      const wsUrl = await getWebSocketUrl(agentId);
      if (!wsUrl) {
        log.error('failed to get WebSocket URL');
        _cleanup();
        return false;
      }
      _wsUrl = wsUrl;
      _connect(wsUrl);
    } else {
      // Ready but not connected yet - will connect on first sendText()
      _setStatus('disconnected');
      log.info('voice agent ready (will connect on first message)');
    }

    return true;
  } catch (err) {
    log.error(`failed to start voice agent: ${err}`);
    _cleanup();
    return false;
  }
}

/** Stop the voice agent and close the WebSocket. */
export function stopVoiceAgent(): void {
  if (!_active) return;
  log.info('stopping voice agent');
  _active = false;
  _closeWebSocket();
  _cleanup();
}

/** Whether a voice agent session is currently active. */
export function isVoiceAgentActive(): boolean {
  return _active;
}

/** Mute or unmute the microphone. */
export function setMicMuted(muted: boolean): void {
  _micMuted = muted;
  log.debug(`mic ${muted ? 'muted' : 'unmuted'}`);
}

/** Enable or disable audio output (TTS playback). */
export function setAudioOutputEnabled(enabled: boolean): void {
  _audioOutputEnabled = enabled;
  log.debug(`audio output ${enabled ? 'enabled' : 'disabled'}`);
}

/**
 * Send text to the voice agent as if the user spoke it.
 * The agent processes it through its LLM and responds with audio.
 */
export async function sendText(text: string): Promise<void> {
  if (!_active) {
    log.warn('cannot send text - no active voice agent');
    return;
  }

  // Connect on demand - only pay when actually sending
  const connected = await _ensureConnected();
  if (!connected) {
    log.error('cannot send text - failed to connect');
    return;
  }

  _resetIdleTimer();
  log.info(`text injected: "${text.slice(0, 80)}"`);

  _wsSend(JSON.stringify({
    type: 'user_message',
    text,
  }));
}

/**
 * Simple energy-based voice activity detection.
 * Returns true if the audio chunk likely contains speech.
 */
const VAD_ENERGY_THRESHOLD = 0.01; // tune: lower = more sensitive
let _vadSpeechDetected = false;
let _vadSilenceFrames = 0;
const VAD_SILENCE_FRAMES_TO_STOP = 15; // ~15 chunks of silence before "not speaking"

function _detectVoiceActivity(audio: Float32Array): boolean {
  let energy = 0;
  for (let i = 0; i < audio.length; i++) {
    energy += audio[i] * audio[i];
  }
  energy = Math.sqrt(energy / audio.length); // RMS energy

  if (energy > VAD_ENERGY_THRESHOLD) {
    _vadSpeechDetected = true;
    _vadSilenceFrames = 0;
    return true;
  }

  if (_vadSpeechDetected) {
    _vadSilenceFrames++;
    if (_vadSilenceFrames > VAD_SILENCE_FRAMES_TO_STOP) {
      _vadSpeechDetected = false;
      _vadSilenceFrames = 0;
      return false;
    }
    return true; // still in speech tail
  }

  return false;
}

/**
 * Send raw PCM audio data to the voice agent.
 * Expected format: 16kHz mono Float32Array (-1.0 to 1.0).
 *
 * Uses local VAD to gate the connection - only connects when speech is
 * detected, disconnects after 2s of silence. This means mic-on mode
 * only bills for actual speaking time, not idle listening.
 */
export function sendAudioChunk(audio: Float32Array): void {
  if (!_active || _micMuted) return;

  const hasSpeech = _detectVoiceActivity(audio);

  // If no speech and not connected, skip entirely (free)
  if (!hasSpeech && (!_ws || _ws.readyState !== WebSocket.OPEN)) return;

  // Speech detected but not connected - reconnect
  if (hasSpeech && (!_ws || _ws.readyState !== WebSocket.OPEN)) {
    _ensureConnected().then((ok) => {
      if (ok) {
        _resetIdleTimer();
        // Send this chunk now that we're connected
        _sendAudioData(audio);
      }
    });
    return;
  }

  // Connected - send audio and manage idle timer
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _resetIdleTimer();
    _sendAudioData(audio);

    // If speech just stopped, start the idle timer
    if (!hasSpeech) {
      _startIdleTimer();
    }
  }
}

function _sendAudioData(audio: Float32Array): void {
  // Convert Float32Array to 16-bit PCM
  const pcm16 = _float32ToPCM16(audio);

  // Base64 encode for the WebSocket protocol
  const base64 = Buffer.from(pcm16.buffer).toString('base64');

  _wsSend(JSON.stringify({
    user_audio_chunk: base64,
  }));
}

/** Get the current voice agent status. */
export function getVoiceAgentStatus(): VoiceAgentStatus {
  return _status;
}

/** Get the ElevenLabs conversation ID. */
export function getConversationId(): string | null {
  return _conversationId;
}

/** Subscribe to voice agent events. */
export function onVoiceAgentEvent(
  event: keyof VoiceAgentEvents,
  listener: (...args: unknown[]) => void,
): void {
  _emitter.on(event, listener);
}

/** Remove a voice agent event listener. */
export function offVoiceAgentEvent(
  event: keyof VoiceAgentEvents,
  listener: (...args: unknown[]) => void,
): void {
  _emitter.off(event, listener);
}

/**
 * Configure external callbacks for integration with the main app.
 */
export function configureVoiceAgent(opts: {
  getWindow?: () => BrowserWindow | null;
  setCliSessionId?: (id: string) => void;
}): void {
  if (opts.getWindow) _getWindow = opts.getWindow;
  if (opts.setCliSessionId) _setCliSessionIdExternal = opts.setCliSessionId;
}

// ---------------------------------------------------------------------------
// WebSocket connection management
// ---------------------------------------------------------------------------

function _connect(url: string): void {
  log.info('connecting to ElevenLabs Conversational AI');

  _ws = new WebSocket(url);

  _ws.onopen = () => {
    log.info('WebSocket connected');

    // Start ping keepalive
    _pingTimer = setInterval(() => {
      if (_ws && _ws.readyState === WebSocket.OPEN) {
        _wsSend(JSON.stringify({ type: 'ping' }));
      }
    }, PING_INTERVAL_MS);
  };

  _ws.onmessage = (event: MessageEvent) => {
    _handleMessage(event.data);
  };

  _ws.onerror = (event: Event) => {
    log.error(`WebSocket error: ${event}`);
    _emitter.emit('error', 'WebSocket connection error');
  };

  _ws.onclose = (event: CloseEvent) => {
    log.info(`WebSocket closed: code=${event.code} reason=${event.reason}`);
    _clearPingTimer();

    if (_active) {
      // Check for ElevenLabs credit/quota issues
      const reason = (event.reason || '').toLowerCase();
      if (
        reason.includes('credit') ||
        reason.includes('quota') ||
        reason.includes('limit') ||
        event.code === 4003
      ) {
        log.warn('ElevenLabs credits exhausted or quota reached');
        _getWindow?.()?.webContents.send('voice-agent:status', 'credits_exhausted');
        _getWindow?.()?.webContents.send(
          'inference:textDelta',
          '\n\n_ElevenLabs credits exhausted. Switching to text-only mode._',
        );
      } else {
        log.warn('unexpected disconnect - session ended');
      }

      _active = false;
      _cleanup();
    }
  };
}

/** Handle an incoming WebSocket message. */
function _handleMessage(data: unknown): void {
  // Binary data - likely raw audio bytes
  if (typeof data !== 'string') {
    const buf = Buffer.from(data as ArrayBuffer);
    _handleAudioOutput(buf);
    return;
  }

  let msg: ConvAIServerMessage;
  try {
    msg = JSON.parse(data) as ConvAIServerMessage;
  } catch {
    log.debug(`unparseable message: ${String(data).slice(0, 100)}`);
    return;
  }

  switch (msg.type) {
    case 'conversation_initiation_metadata':
      _handleInitMetadata(msg);
      break;

    case 'user_transcript':
      _handleUserTranscript(msg);
      break;

    case 'agent_response':
      _handleAgentResponse(msg);
      break;

    case 'agent_response_correction':
      _handleAgentResponseCorrection(msg);
      break;

    case 'audio':
      _handleAudioEvent(msg);
      break;

    case 'interruption':
      _handleInterruption(msg);
      break;

    case 'ping':
      _handlePing(msg);
      break;

    case 'client_tool_call':
      _handleClientToolCall(msg);
      break;

    case 'vad_score':
      // Informational - no action needed
      break;

    case 'internal_tentative_agent_response':
      _getWindow?.()?.webContents.send(
        'voice-agent:tentativeResponse',
        msg.tentative_agent_response_internal_event.tentative_agent_response,
      );
      break;

    default:
      log.debug(`unknown message type: ${(msg as { type?: string }).type}`);
  }
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function _handleInitMetadata(msg: ConvAIInitMetadata): void {
  const meta = msg.conversation_initiation_metadata_event;
  _conversationId = meta.conversation_id;

  log.info(
    `conversation started: id=${_conversationId} ` +
      `input=${meta.user_input_audio_format} output=${meta.agent_output_audio_format}`,
  );

  _setStatus('active');
}

function _handleUserTranscript(msg: ConvAIUserTranscript): void {
  const text = msg.user_transcription_event.user_transcript;
  log.debug(`user said: "${text.slice(0, 80)}"`);

  _emitter.emit('userTranscript', text);
  _getWindow?.()?.webContents.send('voice-agent:userTranscript', text);
}

// Skip TTS for very short responses - just show text
let _skipNextAudio = false;

function _handleAgentResponse(msg: ConvAIAgentResponse): void {
  const text = msg.agent_response_event.agent_response;
  log.debug(`agent said: "${text.slice(0, 80)}"`);

  _emitter.emit('agentResponse', text);
  _getWindow?.()?.webContents.send('voice-agent:agentResponse', text);

  // For very short responses, skip TTS audio - just display text
  if (text.length < 20) {
    _skipNextAudio = true;
    log.debug('short response - skipping TTS audio');
  }

  // Agent finished speaking - start idle disconnect countdown
  _startIdleTimer();
}

function _handleAgentResponseCorrection(msg: ConvAIAgentResponseCorrection): void {
  const corrected = msg.agent_response_correction_event.agent_response;
  log.debug(`agent response corrected: "${corrected.slice(0, 80)}"`);
  _getWindow?.()?.webContents.send('voice-agent:agentResponseCorrection', corrected);
}

function _handleAudioEvent(msg: ConvAIAudio): void {
  if (_skipNextAudio) {
    _skipNextAudio = false;
    return;
  }
  const audioBytes = Buffer.from(msg.audio_event.audio_base_64, 'base64');
  _handleAudioOutput(audioBytes);
}

function _handleAudioOutput(audioBytes: Buffer): void {
  if (!_audioOutputEnabled) return;
  // Audio still flowing - keep connection alive
  _resetIdleTimer();
  _getWindow?.()?.webContents.send('voice-agent:audio', audioBytes);
  _emitter.emit('audioReceived', audioBytes);
}

function _handleInterruption(msg: ConvAIInterruption): void {
  log.debug(`interruption detected (event_id=${msg.interruption_event?.event_id})`);
  _getWindow?.()?.webContents.send('voice-agent:interruption');
}

function _handlePing(msg: ConvAIPing): void {
  _wsSend(JSON.stringify({
    type: 'pong',
    event_id: msg.ping_event.event_id,
  }));
}

// ---------------------------------------------------------------------------
// Client tool call handling
// ---------------------------------------------------------------------------

/**
 * Handle a client_tool_call message from ElevenLabs.
 * Dispatches to the appropriate local handler and sends the result back.
 */
async function _handleClientToolCall(msg: ConvAIClientToolCall): Promise<void> {
  const { tool_call_id, tool_name, parameters } = msg.client_tool_call;

  log.info(`tool call: ${tool_name} (id=${tool_call_id})`);
  log.debug(`tool params: ${JSON.stringify(parameters).slice(0, 200)}`);

  // Track pending tool calls so idle timer doesn't disconnect mid-tool
  _pendingToolCalls++;
  _resetIdleTimer();

  _emitter.emit('toolCall', { name: tool_name, params: parameters });
  _getWindow?.()?.webContents.send('voice-agent:toolCall', tool_name, parameters);

  try {
    let result: string;

    switch (tool_name) {
      case 'claude_code':
        result = await _handleClaudeCode(parameters);
        break;

      case 'generate_artefact':
        result = await _handleGenerateArtefact(parameters);
        break;

      case 'recall_memory':
        result = await _handleRecallMemory(parameters);
        break;

      case 'send_telegram':
        result = await _handleSendTelegram(parameters);
        break;

      default:
        result = `Unknown tool: ${tool_name}`;
        log.warn(`unknown tool call: ${tool_name}`);
    }

    _sendToolResult(tool_call_id, result, false);
    _emitter.emit('toolResult', { name: tool_name, result: result.slice(0, 200) });
    _getWindow?.()?.webContents.send('voice-agent:toolResult', tool_name, result.slice(0, 500));
  } catch (err) {
    const errMsg = `Tool error: ${String(err)}`;
    log.error(`tool call failed (${tool_name}): ${err}`);
    _sendToolResult(tool_call_id, errMsg, true);
  } finally {
    _pendingToolCalls = Math.max(0, _pendingToolCalls - 1);
    // Tool done and agent will narrate result - idle timer starts after narration
  }
}

/**
 * Send a tool result back to ElevenLabs via WebSocket.
 */
function _sendToolResult(toolCallId: string, result: string, isError: boolean): void {
  _wsSend(JSON.stringify({
    type: 'client_tool_result',
    tool_call_id: toolCallId,
    result: result,
    is_error: isError,
  }));
}

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------

/**
 * Run Claude Code for complex tasks.
 * Uses the existing streamInference() from inference.ts.
 * Collects the full response text and returns it as a string.
 */
async function _handleClaudeCode(params: Record<string, unknown>): Promise<string> {
  const prompt = params.prompt as string;
  if (!prompt) return 'Error: no prompt provided';

  if (!_systemPrompt) {
    _systemPrompt = loadSystemPrompt();
  }

  log.info(`claude_code: "${prompt.slice(0, 80)}"`);

  return new Promise<string>((resolve) => {
    const emitter = streamInference(prompt, _systemPrompt!, _cliSessionId);
    let fullText = '';
    let toolsUsed: string[] = [];

    const timeout = setTimeout(() => {
      log.warn('claude_code timed out');
      resolve(fullText || 'Claude Code timed out. Try again with a simpler request.');
    }, CLAUDE_CODE_TIMEOUT_MS);

    emitter.on('event', (evt: InferenceEvent) => {
      if (!_active) {
        clearTimeout(timeout);
        resolve(fullText || 'Voice agent stopped.');
        return;
      }

      switch (evt.type) {
        case 'TextDelta':
          fullText += evt.text;
          // Forward text deltas to the renderer for display
          _getWindow?.()?.webContents.send('inference:textDelta', evt.text);
          break;

        case 'SentenceReady':
          _getWindow?.()?.webContents.send('inference:sentenceReady', evt.sentence, '');
          break;

        case 'ToolUse':
          toolsUsed.push(evt.name);
          log.debug(`claude_code tool use: ${evt.name}`);
          _getWindow?.()?.webContents.send('inference:toolUse', evt.name);
          break;

        case 'Compacting':
          _getWindow?.()?.webContents.send('inference:compacting');
          break;

        case 'StreamDone':
          clearTimeout(timeout);
          fullText = evt.fullText || fullText;

          // Update CLI session ID for continuity
          if (evt.sessionId) {
            _cliSessionId = evt.sessionId;
            _setCliSessionIdExternal?.(evt.sessionId);
          }

          _getWindow?.()?.webContents.send('inference:done', fullText);
          log.info(
            `claude_code complete: ${fullText.length} chars` +
              (toolsUsed.length > 0 ? ` | tools: ${toolsUsed.join(', ')}` : ''),
          );

          // Truncate very long responses for the tool result
          // (the ElevenLabs LLM only needs a summary to narrate)
          const truncated =
            fullText.length > 4000
              ? fullText.slice(0, 3800) + '\n\n[Response truncated - full result displayed on screen]'
              : fullText;

          resolve(truncated);
          break;

        case 'StreamError':
          clearTimeout(timeout);
          log.error(`claude_code error: ${evt.message}`);
          _getWindow?.()?.webContents.send('inference:error', evt.message);

          // Return a human-friendly error for the voice agent to narrate
          if (
            evt.message.includes('143') ||
            evt.message.includes('rate') ||
            evt.message.includes('overloaded')
          ) {
            resolve('Claude is temporarily unavailable due to rate limiting. Try again in a moment.');
          } else {
            resolve(`Claude encountered an error: ${evt.message.slice(0, 200)}`);
          }
          break;
      }
    });
  });
}

/**
 * Generate a visual artefact via Claude Code and display it.
 */
async function _handleGenerateArtefact(params: Record<string, unknown>): Promise<string> {
  const prompt = params.prompt as string;
  if (!prompt) return 'Error: no prompt provided';

  log.info(`generate_artefact: "${prompt.slice(0, 80)}"`);

  // Use Claude Code with a specific artefact generation prompt
  const artefactPrompt =
    `Generate an HTML artefact: ${prompt}. ` +
    'Output a complete, self-contained HTML page with inline CSS and JavaScript. ' +
    'Make it visually polished with a dark theme. ' +
    'Output ONLY the HTML - no explanation, no markdown code fences.';

  const result = await _handleClaudeCode({ prompt: artefactPrompt });

  // Extract HTML content - strip any markdown code fences if present
  let html = result;
  const htmlMatch = result.match(/```(?:html)?\s*\n([\s\S]*?)\n```/);
  if (htmlMatch) {
    html = htmlMatch[1];
  } else if (!html.trim().startsWith('<')) {
    // If the result doesn't look like HTML, wrap it
    html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body { background: #1a1a2e; color: #eee; font-family: system-ui; padding: 2rem; }
  pre { white-space: pre-wrap; }
</style></head><body><pre>${html.replace(/</g, '&lt;')}</pre></body></html>`;
  }

  // Send to renderer for display
  _getWindow?.()?.webContents.send('artefact:updated', {
    type: 'html',
    content: html,
    title: 'Voice Agent Artefact',
  });

  return 'Artefact generated and displayed on screen. Describe what you created to the user.';
}

/**
 * Search agent memory directly - no Claude inference needed.
 * Uses vector search for semantic matching, falls back to keyword search.
 */
async function _handleRecallMemory(params: Record<string, unknown>): Promise<string> {
  const query = params.query as string;
  if (!query) return 'Error: no query provided';

  log.info(`recall_memory: "${query.slice(0, 80)}"`);

  try {
    // Try vector search first (semantic)
    const results = await Promise.race([
      memory.searchMemory(query, 5),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('memory search timed out')), MEMORY_TIMEOUT_MS),
      ),
    ]);

    if (results.length === 0) {
      return 'No memories found matching that query.';
    }

    // Format results for the voice agent to narrate
    const formatted = results.map((r, i) => {
      const source = r._source_table || 'unknown';
      const score = typeof r._score === 'number' ? ` (relevance: ${(r._score * 100).toFixed(0)}%)` : '';
      const content = (r.content as string) || (r.summary as string) || JSON.stringify(r);
      const timestamp = (r.timestamp as string) || (r.created_at as string) || '';
      const timeStr = timestamp ? ` [${timestamp}]` : '';

      return `${i + 1}. [${source}]${timeStr}${score}: ${content}`;
    });

    let result = `Found ${results.length} memories:\n\n${formatted.join('\n\n')}`;
    if (result.length > 500) result = result.slice(0, 497) + '...';
    return result;
  } catch (err) {
    log.error(`memory recall failed: ${err}`);

    // Fallback: try keyword search on recent turns
    try {
      const db = memory.getDb();
      const rows = db
        .prepare(
          `SELECT role, content, timestamp FROM turns
           WHERE content LIKE ?
           ORDER BY timestamp DESC LIMIT 5`,
        )
        .all(`%${query}%`) as { role: string; content: string; timestamp: string }[];

      if (rows.length > 0) {
        const formatted = rows.map(
          (r, i) => `${i + 1}. [${r.timestamp}] ${r.role}: ${r.content.slice(0, 200)}`,
        );
        let result = `Found ${rows.length} matching conversations:\n\n${formatted.join('\n\n')}`;
        if (result.length > 500) result = result.slice(0, 497) + '...';
        return result;
      }
    } catch { /* fall through */ }

    return `Memory search failed: ${String(err)}. No results available.`;
  }
}

/**
 * Send a message via Telegram - direct API call, no inference needed.
 */
async function _handleSendTelegram(params: Record<string, unknown>): Promise<string> {
  const message = params.message as string;
  if (!message) return 'Error: no message provided';

  log.info(`send_telegram: "${message.slice(0, 80)}"`);

  try {
    const sent = await sendTelegramMessage(message);
    return sent ? 'Message sent successfully.' : 'Failed to send Telegram message.';
  } catch (err) {
    log.error(`telegram send failed: ${err}`);
    return `Failed to send Telegram message: ${String(err)}`;
  }
}

// ---------------------------------------------------------------------------
// Audio conversion
// ---------------------------------------------------------------------------

/**
 * Convert Float32Array audio samples (-1.0 to 1.0) to 16-bit PCM Int16Array.
 * ElevenLabs expects 16kHz mono 16-bit PCM encoded as base64.
 */
function _float32ToPCM16(float32: Float32Array): Int16Array {
  const pcm16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm16;
}

// ---------------------------------------------------------------------------
// Connection helpers
// ---------------------------------------------------------------------------

function _wsSend(data: string): void {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    try {
      _ws.send(data);
    } catch (err) {
      log.error(`WebSocket send error: ${err}`);
    }
  }
}

function _closeWebSocket(): void {
  _clearPingTimer();

  if (_ws) {
    try {
      _ws.close(1000, 'session ended');
    } catch {
      // Already closed or errored
    }
    _ws = null;
  }
}

function _clearPingTimer(): void {
  if (_pingTimer) {
    clearInterval(_pingTimer);
    _pingTimer = null;
  }
}

function _setStatus(status: VoiceAgentStatus): void {
  _status = status;
  _emitter.emit('status', status);
  _getWindow?.()?.webContents.send('voice-agent:status', status);
}

function _cleanup(): void {
  _resetIdleTimer();
  _closeWebSocket();
  _active = false;
  _conversationId = null;
  _pendingToolCalls = 0;
  _setStatus('disconnected');
  _emitter.emit('ended');
}

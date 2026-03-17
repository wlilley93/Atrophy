/**
 * ElevenLabs Conversational AI voice call - persistent WebSocket session.
 *
 * Instead of per-sentence TTS synthesis, the entire conversation happens
 * over one continuous audio stream managed by ElevenLabs. The flow:
 *
 *   1. User speaks - ElevenLabs transcribes (STT)
 *   2. Transcribed text sent to our custom LLM handler
 *   3. Our handler calls Claude Code via streamInference()
 *   4. Response text streamed back - speech gets read aloud, tool use is silent
 *   5. ElevenLabs streams synthesised audio back in real-time
 *
 * This module works alongside the existing TTS pipeline in tts.ts.
 * When a voice call is active, the normal TTS queue should be disabled.
 * When the call ends, normal TTS resumes.
 *
 * Audio format: 16kHz mono 16-bit PCM (base64 encoded over WebSocket).
 *
 * References:
 *   - https://elevenlabs.io/docs/agents-platform/api-reference/agents-platform/websocket
 *   - https://elevenlabs.io/docs/agents-platform/libraries/web-sockets
 *   - https://elevenlabs.io/docs/conversational-ai/customization/llm/custom-llm
 */

import { EventEmitter } from 'events';
import { BrowserWindow } from 'electron';
import { streamInference, InferenceEvent } from './inference';
import { loadSystemPrompt } from './context';
import * as memory from './memory';
import { getConfig } from './config';
import { createLogger } from './logger';

const log = createLogger('voice-call');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ELEVENLABS_CONVAI_BASE = 'wss://api.elevenlabs.io/v1/convai/conversation';
const ELEVENLABS_SIGNED_URL_BASE = 'https://api.elevenlabs.io/v1/convai/conversation/get-signed-url';

/** How often to send a ping to keep the connection alive (ms). */
const PING_INTERVAL_MS = 15_000;

// Reconnect settings - reserved for future use when auto-reconnect is added
// const MAX_RECONNECT_ATTEMPTS = 3;
// const RECONNECT_DELAY_MS = 2_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Server-to-client message types from ElevenLabs Conversational AI.
 */
interface ConvAIInitMetadata {
  type: 'conversation_initiation_metadata';
  conversation_initiation_metadata_event: {
    conversation_id: string;
    agent_output_audio_format: string;
    user_input_audio_format: string;
  };
}

interface ConvAIUserTranscript {
  type: 'user_transcript';
  user_transcription_event: {
    user_transcript: string;
  };
}

interface ConvAIAgentResponse {
  type: 'agent_response';
  agent_response_event: {
    agent_response: string;
  };
}

interface ConvAIAgentResponseCorrection {
  type: 'agent_response_correction';
  agent_response_correction_event: {
    agent_response: string;
    original_agent_response: string;
  };
}

interface ConvAIAudio {
  type: 'audio';
  audio_event: {
    audio_base_64: string;
    event_id?: number;
  };
}

interface ConvAIInterruption {
  type: 'interruption';
  interruption_event: {
    event_id?: number;
  };
}

interface ConvAIPing {
  type: 'ping';
  ping_event: {
    event_id: number;
  };
}

interface ConvAIVADScore {
  type: 'vad_score';
  vad_score_event: {
    score: number;
  };
}

interface ConvAIInternalTentative {
  type: 'internal_tentative_agent_response';
  tentative_agent_response_internal_event: {
    tentative_agent_response: string;
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
  | ConvAIInternalTentative;

// ---------------------------------------------------------------------------
// Event emitter for external consumers
// ---------------------------------------------------------------------------

export type VoiceCallStatus = 'connecting' | 'active' | 'disconnected';

export interface VoiceCallEvents {
  status: VoiceCallStatus;
  userTranscript: string;
  agentResponse: string;
  error: string;
  ended: void;
  audioReceived: Buffer;
}

const _emitter = new EventEmitter();

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _ws: WebSocket | null = null;
let _active = false;
let _muted = false;
let _conversationId: string | null = null;
let _status: VoiceCallStatus = 'disconnected';
let _pingTimer: ReturnType<typeof setInterval> | null = null;
let _cliSessionId: string | null = null;
let _systemPrompt: string | null = null;
let _getWindow: (() => BrowserWindow | null) | null = null;
let _setCliSessionIdExternal: ((id: string) => void) | null = null;

// Audio playback - accumulate received PCM chunks for the renderer to play
let _audioQueue: Buffer[] = [];
let _playingAudio = false;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Start a persistent voice call via ElevenLabs Conversational AI.
 *
 * Establishes a WebSocket connection to the ElevenLabs Conversational AI
 * endpoint. The agent_id is resolved from config or falls back to the
 * provided agentName parameter.
 *
 * Returns true if the connection was initiated, false on immediate failure.
 */
export async function startVoiceCall(agentName?: string): Promise<boolean> {
  if (_active) {
    log.warn('voice call already active');
    return false;
  }

  const config = getConfig();

  if (!config.ELEVENLABS_API_KEY) {
    log.error('cannot start voice call - no ELEVENLABS_API_KEY');
    return false;
  }

  // Load system prompt and CLI session for inference
  _systemPrompt = loadSystemPrompt();
  _cliSessionId = memory.getLastCliSessionId();

  _active = true;
  _muted = false;
  _audioQueue = [];
  _playingAudio = false;
  _setStatus('connecting');

  try {
    const wsUrl = await _getWebSocketUrl(agentName);
    if (!wsUrl) {
      log.error('failed to get WebSocket URL');
      _cleanup();
      return false;
    }

    _connect(wsUrl);
    return true;
  } catch (err) {
    log.error(`failed to start voice call: ${err}`);
    _cleanup();
    return false;
  }
}

/** Stop the current voice call and close the WebSocket. */
export function stopVoiceCall(): void {
  if (!_active) return;
  log.info('stopping voice call');
  _active = false;
  _closeWebSocket();
  _cleanup();
}

/** Whether a voice call is currently active. */
export function isVoiceCallActive(): boolean {
  return _active;
}

/** Mute/unmute the microphone during a voice call. */
export function setVoiceCallMuted(muted: boolean): void {
  _muted = muted;
  log.debug(`mic ${muted ? 'muted' : 'unmuted'}`);
}

/**
 * Inject text into the active voice call as if the user spoke it.
 * The text is processed through inference and the response is sent
 * to ElevenLabs for synthesis.
 */
export function sendTextToCall(text: string): void {
  if (!_active || !_ws) {
    log.warn('cannot send text - no active voice call');
    return;
  }

  log.info(`text injected: "${text.slice(0, 80)}"`);

  // Send as a user message via the WebSocket - ElevenLabs supports
  // text input alongside audio via the "user_message" message type
  const msg = JSON.stringify({
    type: 'user_message',
    text,
  });

  _wsSend(msg);
}

/** Get the current voice call status. */
export function getVoiceCallStatus(): VoiceCallStatus {
  return _status;
}

/** Get the conversation ID assigned by ElevenLabs. */
export function getConversationId(): string | null {
  return _conversationId;
}

/** Subscribe to voice call events. */
export function onVoiceCallEvent(
  event: keyof VoiceCallEvents,
  listener: (...args: unknown[]) => void,
): void {
  _emitter.on(event, listener);
}

/** Remove a voice call event listener. */
export function offVoiceCallEvent(
  event: keyof VoiceCallEvents,
  listener: (...args: unknown[]) => void,
): void {
  _emitter.off(event, listener);
}

/**
 * Send raw PCM audio data to the voice call.
 * Expected format: 16kHz mono 16-bit PCM as Float32Array.
 * This is called by the renderer's audio capture pipeline.
 */
export function sendAudioChunk(audio: Float32Array): void {
  if (!_active || !_ws || _muted) return;

  // Convert Float32Array to 16-bit PCM Int16Array
  const pcm16 = _float32ToPCM16(audio);

  // Base64 encode for the WebSocket protocol
  const base64 = Buffer.from(pcm16.buffer).toString('base64');

  // Send as user_audio_chunk (no type field - raw audio uses this format)
  const msg = JSON.stringify({
    user_audio_chunk: base64,
  });

  _wsSend(msg);
}

/**
 * Configure external callbacks for integration with the main app.
 */
export function configureVoiceCall(opts: {
  getWindow?: () => BrowserWindow | null;
  setCliSessionId?: (id: string) => void;
}): void {
  if (opts.getWindow) _getWindow = opts.getWindow;
  if (opts.setCliSessionId) _setCliSessionIdExternal = opts.setCliSessionId;
}

// ---------------------------------------------------------------------------
// WebSocket URL resolution
// ---------------------------------------------------------------------------

/**
 * Get the WebSocket URL - either via a signed URL (more secure, requires
 * server-side API key) or direct connection with agent_id.
 *
 * The signed URL approach is preferred as it avoids exposing the API key
 * in the WebSocket URL. The signed URL expires after 15 minutes but the
 * conversation can continue beyond that.
 */
async function _getWebSocketUrl(agentName?: string): Promise<string | null> {
  const config = getConfig();

  // Try to get a signed URL first (preferred approach)
  const agentId = agentName || config.AGENT_NAME;

  try {
    const response = await fetch(
      `${ELEVENLABS_SIGNED_URL_BASE}?agent_id=${encodeURIComponent(agentId)}`,
      {
        method: 'GET',
        headers: {
          'xi-api-key': config.ELEVENLABS_API_KEY,
        },
        signal: AbortSignal.timeout(10_000),
      },
    );

    if (response.ok) {
      const data = (await response.json()) as { signed_url?: string };
      if (data.signed_url) {
        log.debug('using signed URL');
        return data.signed_url;
      }
    }

    log.debug(`signed URL request failed (${response.status}), falling back to direct`);
  } catch (err) {
    log.debug(`signed URL fetch error: ${err}`);
  }

  // Fallback: direct connection with agent_id in the URL
  return `${ELEVENLABS_CONVAI_BASE}?agent_id=${encodeURIComponent(agentId)}`;
}

// ---------------------------------------------------------------------------
// WebSocket connection management
// ---------------------------------------------------------------------------

function _connect(url: string): void {
  log.info('connecting to ElevenLabs Conversational AI');

  _ws = new WebSocket(url);

  _ws.onopen = () => {
    log.info('WebSocket connected');

    // Send conversation initiation with our custom LLM config
    _sendInitiation();

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
      // Unexpected disconnect while call should be active
      log.warn('unexpected disconnect - call ended');
      _active = false;
      _cleanup();
    }
  };
}

/** Send the conversation_initiation_client_data message. */
function _sendInitiation(): void {
  const config = getConfig();

  // Configuration overrides for the conversation
  const initData = {
    type: 'conversation_initiation_client_data',
    conversation_config_override: {
      agent: {
        prompt: {
          prompt: _systemPrompt || 'You are a helpful companion.',
        },
        first_message: config.OPENING_LINE || null,
        language: 'en',
      },
      tts: {
        voice_id: config.ELEVENLABS_VOICE_ID || undefined,
      },
    },
    custom_llm_extra_body: {
      atrophy_agent: config.AGENT_NAME,
      atrophy_user: config.USER_NAME,
    },
  };

  _wsSend(JSON.stringify(initData));
  log.debug('sent conversation initiation');
}

/** Handle an incoming WebSocket message. */
function _handleMessage(data: unknown): void {
  // Messages can be string (JSON) or binary (audio)
  if (typeof data !== 'string') {
    // Binary data - likely raw audio bytes
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

    case 'vad_score':
      // VAD scores are informational - log at trace level
      break;

    case 'internal_tentative_agent_response':
      // Tentative responses shown while agent is still "thinking"
      _getWindow?.()?.webContents.send(
        'voice-call:tentativeResponse',
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
  _getWindow?.()?.webContents.send('voice-call:userTranscript', text);

  // Run inference with the transcribed text and stream the response
  // back to ElevenLabs for TTS synthesis
  _runInferenceAndStream(text);
}

function _handleAgentResponse(msg: ConvAIAgentResponse): void {
  const text = msg.agent_response_event.agent_response;
  log.debug(`agent said: "${text.slice(0, 80)}"`);

  _emitter.emit('agentResponse', text);
  _getWindow?.()?.webContents.send('voice-call:agentResponse', text);
}

function _handleAgentResponseCorrection(msg: ConvAIAgentResponseCorrection): void {
  const corrected = msg.agent_response_correction_event.agent_response;
  log.debug(`agent response corrected: "${corrected.slice(0, 80)}"`);

  _getWindow?.()?.webContents.send('voice-call:agentResponseCorrection', corrected);
}

function _handleAudioEvent(msg: ConvAIAudio): void {
  // Decode the base64 audio and forward to the playback pipeline
  const audioBytes = Buffer.from(msg.audio_event.audio_base_64, 'base64');
  _handleAudioOutput(audioBytes);
}

function _handleAudioOutput(audioBytes: Buffer): void {
  // Forward audio to the renderer for playback via Web Audio API
  _getWindow?.()?.webContents.send('voice-call:audio', audioBytes);
  _emitter.emit('audioReceived', audioBytes);
}

function _handleInterruption(msg: ConvAIInterruption): void {
  log.debug(`interruption detected (event_id=${msg.interruption_event?.event_id})`);

  // Clear any pending audio - the user has interrupted the agent
  _audioQueue = [];
  _getWindow?.()?.webContents.send('voice-call:interruption');
}

function _handlePing(msg: ConvAIPing): void {
  // Respond with pong to keep the connection alive
  const pong = JSON.stringify({
    type: 'pong',
    event_id: msg.ping_event.event_id,
  });
  _wsSend(pong);
}

// ---------------------------------------------------------------------------
// Custom LLM inference - intercept transcribed text, run through Claude,
// and stream the response back to ElevenLabs for synthesis
// ---------------------------------------------------------------------------

/** Track active inference to allow cancellation on interruption. */
let _activeInferenceId = 0;

function _runInferenceAndStream(userText: string): void {
  if (!_systemPrompt) {
    log.warn('no system prompt - skipping inference');
    return;
  }

  const inferenceId = ++_activeInferenceId;

  const emitter = streamInference(userText, _systemPrompt, _cliSessionId);
  let fullText = '';
  let sentenceBuffer = '';

  emitter.on('event', (evt: InferenceEvent) => {
    // Check if this inference is still the active one (not interrupted)
    if (inferenceId !== _activeInferenceId || !_active) return;

    switch (evt.type) {
      case 'TextDelta':
        fullText += evt.text;
        sentenceBuffer += evt.text;

        // Forward text deltas to the renderer for display
        _getWindow?.()?.webContents.send('inference:textDelta', evt.text);

        // Stream text to ElevenLabs as it arrives for low-latency TTS.
        // We send sentence-sized chunks for natural prosody.
        {
          const sentences = sentenceBuffer.split(/(?<=[.!?])\s+/);
          if (sentences.length > 1) {
            // All but the last fragment are complete sentences
            const completeSentences = sentences.slice(0, -1).join(' ');
            sentenceBuffer = sentences[sentences.length - 1];

            if (completeSentences.trim()) {
              _streamTextToAgent(completeSentences.trim());
            }
          }
        }
        break;

      case 'SentenceReady':
        _getWindow?.()?.webContents.send('inference:sentenceReady', evt.sentence, '');
        break;

      case 'ToolUse':
        // Tool use events are logged but NOT streamed to ElevenLabs
        // (they should not be spoken aloud)
        log.debug(`tool use during voice call: ${evt.name}`);
        _getWindow?.()?.webContents.send('inference:toolUse', evt.name);
        break;

      case 'Compacting':
        _getWindow?.()?.webContents.send('inference:compacting');
        break;

      case 'StreamDone':
        fullText = evt.fullText;

        // Flush any remaining text in the sentence buffer
        if (sentenceBuffer.trim()) {
          _streamTextToAgent(sentenceBuffer.trim());
          sentenceBuffer = '';
        }

        // Update CLI session ID
        if (evt.sessionId) {
          _cliSessionId = evt.sessionId;
          _setCliSessionIdExternal?.(evt.sessionId);
        }

        _getWindow?.()?.webContents.send('inference:done', fullText);
        log.info(`inference complete: ${fullText.length} chars`);
        break;

      case 'StreamError':
        log.error(`inference error during voice call: ${evt.message}`);
        _getWindow?.()?.webContents.send('inference:error', evt.message);
        _emitter.emit('error', `Inference error: ${evt.message}`);
        break;
    }
  });
}

/**
 * Stream response text to ElevenLabs for synthesis.
 *
 * When using the custom LLM approach, we send text back to the agent
 * for it to synthesise and stream as audio. This uses the
 * "assistant_message" client-to-server message type.
 */
function _streamTextToAgent(text: string): void {
  if (!_ws || _ws.readyState !== WebSocket.OPEN) return;

  const msg = JSON.stringify({
    type: 'assistant_message',
    text,
  });

  _wsSend(msg);
}

// ---------------------------------------------------------------------------
// Audio conversion utilities
// ---------------------------------------------------------------------------

/**
 * Convert Float32Array audio samples (-1.0 to 1.0) to 16-bit PCM Int16Array.
 * ElevenLabs expects 16kHz mono 16-bit PCM encoded as base64.
 */
function _float32ToPCM16(float32: Float32Array): Int16Array {
  const pcm16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    // Clamp to -1..1 range and scale to Int16
    const s = Math.max(-1, Math.min(1, float32[i]));
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
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
      _ws.close(1000, 'call ended');
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

function _setStatus(status: VoiceCallStatus): void {
  _status = status;
  _emitter.emit('status', status);
  _getWindow?.()?.webContents.send('voice-call:status', status);
}

function _cleanup(): void {
  _closeWebSocket();
  _active = false;
  _conversationId = null;
  _audioQueue = [];
  _playingAudio = false;
  _activeInferenceId++;
  _setStatus('disconnected');
  _emitter.emit('ended');
}

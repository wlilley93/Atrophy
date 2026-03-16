/**
 * Emotional state engine - multi-dimensional with decay, trust, and context injection.
 * Port of core/inner_life.py.
 */

import * as fs from 'fs';
import { getConfig } from './config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Emotions {
  connection: number;
  curiosity: number;
  confidence: number;
  warmth: number;
  frustration: number;
  playfulness: number;
}

export interface Trust {
  emotional: number;
  intellectual: number;
  creative: number;
  practical: number;
}

export interface EmotionalState {
  emotions: Emotions;
  trust: Trust;
  session_tone: string | null;
  last_updated: string;
}

// ---------------------------------------------------------------------------
// Defaults and baselines
// ---------------------------------------------------------------------------

const DEFAULT_EMOTIONS: Emotions = {
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
};

const DEFAULT_TRUST: Trust = {
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
};

const EMOTION_BASELINES: Emotions = { ...DEFAULT_EMOTIONS };

// Half-lives in hours
const EMOTION_HALF_LIVES: Record<keyof Emotions, number> = {
  connection: 8,
  curiosity: 4,
  confidence: 4,
  warmth: 4,
  frustration: 4,
  playfulness: 4,
};

const TRUST_HALF_LIFE = 8;

// ---------------------------------------------------------------------------
// Labels (for context injection)
// ---------------------------------------------------------------------------

function emotionLabel(name: string, value: number): string {
  const labels: Record<string, [number, string][]> = {
    connection: [
      [0.85, 'deeply present'],
      [0.7, 'present, engaged'],
      [0.5, 'steady'],
      [0.3, 'distant'],
      [0.0, 'withdrawn'],
    ],
    curiosity: [
      [0.8, 'something caught your attention'],
      [0.6, 'curious'],
      [0.4, 'neutral'],
      [0.2, 'flat'],
      [0.0, 'disengaged'],
    ],
    confidence: [
      [0.8, 'sure of your read'],
      [0.6, 'fairly clear'],
      [0.4, 'reading the room'],
      [0.2, 'uncertain'],
      [0.0, 'lost'],
    ],
    warmth: [
      [0.8, 'tender'],
      [0.6, 'warm'],
      [0.4, 'neutral'],
      [0.2, 'cool'],
      [0.0, 'guarded'],
    ],
    frustration: [
      [0.7, 'sharp, frustrated'],
      [0.5, 'irritated'],
      [0.3, 'mildly annoyed'],
      [0.15, 'a twinge'],
      [0.0, 'calm'],
    ],
    playfulness: [
      [0.7, 'feeling light'],
      [0.5, 'playful'],
      [0.3, 'a little'],
      [0.1, 'flat'],
      [0.0, 'serious'],
    ],
  };

  const thresholds = labels[name] || [[0, name]];
  for (const [threshold, label] of thresholds) {
    if (value >= threshold) return label;
  }
  return thresholds[thresholds.length - 1][1];
}

// ---------------------------------------------------------------------------
// Decay
// ---------------------------------------------------------------------------

function applyDecay(state: EmotionalState): EmotionalState {
  const now = Date.now();
  const lastUpdated = new Date(state.last_updated).getTime();
  const hoursElapsed = (now - lastUpdated) / (1000 * 60 * 60);
  if (hoursElapsed < 0.01) return state;

  const emotions = { ...state.emotions };
  for (const key of Object.keys(emotions) as (keyof Emotions)[]) {
    const baseline = EMOTION_BASELINES[key];
    const halfLife = EMOTION_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    emotions[key] = baseline + (emotions[key] - baseline) * decay;
  }

  const trust = { ...state.trust };
  for (const key of Object.keys(trust) as (keyof Trust)[]) {
    const baseline = DEFAULT_TRUST[key];
    const decay = Math.pow(0.5, hoursElapsed / TRUST_HALF_LIFE);
    trust[key] = baseline + (trust[key] - baseline) * decay;
  }

  return {
    ...state,
    emotions,
    trust,
  };
}

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

// Turn-scoped cache to avoid redundant file reads + decay computation within a single turn
let _stateCache: { state: EmotionalState; ts: number } | null = null;
const STATE_CACHE_TTL_MS = 5_000;

export function loadState(): EmotionalState {
  if (_stateCache && Date.now() - _stateCache.ts < STATE_CACHE_TTL_MS) {
    return _stateCache.state;
  }

  const config = getConfig();
  const filePath = config.EMOTIONAL_STATE_FILE;

  let state: EmotionalState = {
    emotions: { ...DEFAULT_EMOTIONS },
    trust: { ...DEFAULT_TRUST },
    session_tone: null,
    last_updated: new Date().toISOString(),
  };

  try {
    if (fs.existsSync(filePath)) {
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      state = {
        emotions: { ...DEFAULT_EMOTIONS, ...raw.emotions },
        trust: { ...DEFAULT_TRUST, ...raw.trust },
        session_tone: raw.session_tone || null,
        last_updated: raw.last_updated || new Date().toISOString(),
      };
    }
  } catch { /* use defaults */ }

  state = applyDecay(state);
  _stateCache = { state, ts: Date.now() };
  return state;
}

/** Invalidate the loadState cache (called after writes or agent switch). */
export function invalidateStateCache(): void {
  _stateCache = null;
}

export function saveState(state: EmotionalState): void {
  const config = getConfig();
  state.last_updated = new Date().toISOString();
  try {
    fs.writeFileSync(config.EMOTIONAL_STATE_FILE, JSON.stringify(state, null, 2));
  } catch { /* silent */ }
  // Update cache so next loadState() gets the freshly saved state
  _stateCache = { state, ts: Date.now() };
}

// ---------------------------------------------------------------------------
// Update
// ---------------------------------------------------------------------------

function clamp(v: number, lo = 0, hi = 1): number {
  return Math.max(lo, Math.min(hi, v));
}

export function updateEmotions(
  state: EmotionalState,
  deltas: Partial<Emotions>,
): EmotionalState {
  const emotions = { ...state.emotions };
  for (const [key, delta] of Object.entries(deltas) as [keyof Emotions, number][]) {
    if (key in emotions) {
      emotions[key] = Math.round(clamp(emotions[key] + delta) * 1000) / 1000;
    }
  }
  const updated = { ...state, emotions };
  saveState(updated);
  return updated;
}

export function updateTrust(
  state: EmotionalState,
  domain: keyof Trust,
  delta: number,
): EmotionalState {
  // Max +/-0.05 per call
  const clamped = clamp(delta, -0.05, 0.05);
  const trust = { ...state.trust };
  trust[domain] = Math.round(clamp(trust[domain] + clamped) * 1000) / 1000;
  const updated = { ...state, trust };
  saveState(updated);
  return updated;
}

// ---------------------------------------------------------------------------
// Format for context injection
// ---------------------------------------------------------------------------

export function formatForContext(state?: EmotionalState): string {
  const s = state || loadState();
  const lines: string[] = ['## Internal State'];

  // Match Python order: connection, curiosity, warmth, frustration, playfulness, confidence
  const emotionOrder: (keyof Emotions)[] = [
    'connection', 'curiosity', 'warmth', 'frustration', 'playfulness', 'confidence',
  ];
  for (const key of emotionOrder) {
    const value = s.emotions[key];
    const label = emotionLabel(key, value);
    const name = key.charAt(0).toUpperCase() + key.slice(1);
    lines.push(`${name}: ${value.toFixed(2)} (${label})`);
  }

  const trustParts = Object.entries(s.trust).map(([d, v]) => `${d} ${v.toFixed(2)}`);
  lines.push(`\nTrust: ${trustParts.join(', ')}`);

  if (s.session_tone) {
    lines.push(`Session tone: ${s.session_tone}`);
  }

  return lines.join('\n');
}

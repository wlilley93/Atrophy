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
    connection: [[0.7, 'present, engaged'], [0.4, 'attentive'], [0, 'distant']],
    curiosity: [[0.7, 'deeply curious'], [0.4, 'interested'], [0, 'disengaged']],
    confidence: [[0.7, 'grounded, sure'], [0.4, 'steady'], [0, 'uncertain']],
    warmth: [[0.7, 'warm, open'], [0.4, 'neutral'], [0, 'guarded']],
    frustration: [[0.6, 'frustrated'], [0.3, 'mildly tense'], [0, 'calm']],
    playfulness: [[0.6, 'playful'], [0.3, 'light'], [0, 'serious']],
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
    last_updated: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

export function loadState(): EmotionalState {
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

  return applyDecay(state);
}

export function saveState(state: EmotionalState): void {
  const config = getConfig();
  state.last_updated = new Date().toISOString();
  try {
    fs.writeFileSync(config.EMOTIONAL_STATE_FILE, JSON.stringify(state, null, 2));
  } catch { /* silent */ }
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
      emotions[key] = clamp(emotions[key] + delta);
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
  trust[domain] = clamp(trust[domain] + clamped);
  const updated = { ...state, trust };
  saveState(updated);
  return updated;
}

// ---------------------------------------------------------------------------
// Format for context injection
// ---------------------------------------------------------------------------

export function formatForContext(state?: EmotionalState): string {
  const s = state || loadState();
  const lines: string[] = ['## Inner State'];

  for (const [key, value] of Object.entries(s.emotions)) {
    lines.push(`- ${key}: ${emotionLabel(key, value)} (${value.toFixed(2)})`);
  }

  lines.push('');
  lines.push('## Trust');
  for (const [key, value] of Object.entries(s.trust)) {
    lines.push(`- ${key}: ${value.toFixed(2)}`);
  }

  if (s.session_tone) {
    lines.push(`\nSession tone: ${s.session_tone}`);
  }

  return lines.join('\n');
}

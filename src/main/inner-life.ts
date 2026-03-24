/**
 * Emotional state engine - multi-dimensional with decay, trust, and context injection.
 * Port of core/inner_life.py.
 *
 * v2: expanded to 6 categories (emotions, trust, needs, personality, relationship, drives).
 * Types and constants live in inner-life-types.ts.
 */

import * as fs from 'fs';
import { getConfig } from './config';
import { writeTrustLog } from './memory';
import {
  type Emotions,
  type Trust,
  type Needs,
  type Personality,
  type Relationship,
  type FullState,
  type Drive,
  DEFAULT_EMOTIONS,
  DEFAULT_TRUST,
  DEFAULT_NEEDS,
  DEFAULT_PERSONALITY,
  DEFAULT_RELATIONSHIP,
  EMOTION_BASELINES,
  EMOTION_HALF_LIVES,
  TRUST_HALF_LIVES,
  NEED_DECAY_HOURS,
  RELATIONSHIP_HALF_LIVES,
  DEFAULT_FULL_STATE,
} from './inner-life-types';

// Re-export types so existing imports from './inner-life' keep working
export type { Emotions, Trust, Needs, Personality, Relationship, FullState, Drive } from './inner-life-types';
// Backward compatibility alias
export type EmotionalState = FullState;

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
    // New v2 emotions
    amusement: [
      [0.7, 'delighted'],
      [0.5, 'amused'],
      [0.3, 'a hint of humor'],
      [0.1, 'dry'],
      [0.0, 'unamused'],
    ],
    anticipation: [
      [0.7, 'eager'],
      [0.5, 'anticipating'],
      [0.3, 'mildly expectant'],
      [0.1, 'indifferent'],
      [0.0, 'uninterested'],
    ],
    satisfaction: [
      [0.7, 'deeply satisfied'],
      [0.5, 'content'],
      [0.3, 'somewhat fulfilled'],
      [0.1, 'wanting'],
      [0.0, 'unsatisfied'],
    ],
    restlessness: [
      [0.7, 'restless, itching to move'],
      [0.5, 'antsy'],
      [0.3, 'a little fidgety'],
      [0.1, 'mostly settled'],
      [0.0, 'still'],
    ],
    tenderness: [
      [0.7, 'deeply tender'],
      [0.5, 'gentle'],
      [0.3, 'softening'],
      [0.1, 'neutral'],
      [0.0, 'detached'],
    ],
    melancholy: [
      [0.7, 'heavy, melancholic'],
      [0.5, 'wistful'],
      [0.3, 'a tinge of sadness'],
      [0.1, 'faint'],
      [0.0, 'clear'],
    ],
    focus: [
      [0.8, 'locked in'],
      [0.6, 'focused'],
      [0.4, 'attentive'],
      [0.2, 'drifting'],
      [0.0, 'scattered'],
    ],
    defiance: [
      [0.7, 'defiant'],
      [0.5, 'resistant'],
      [0.3, 'pushing back a little'],
      [0.1, 'mild friction'],
      [0.0, 'compliant'],
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

function applyDecay(state: FullState): FullState {
  const now = Date.now();
  const lastUpdated = new Date(state.last_updated).getTime();
  const hoursElapsed = (now - lastUpdated) / (1000 * 60 * 60);
  if (hoursElapsed < 0.01) return state;

  // Emotions: decay toward EMOTION_BASELINES
  const emotions = { ...state.emotions };
  for (const key of Object.keys(emotions) as (keyof Emotions)[]) {
    const baseline = EMOTION_BASELINES[key];
    const halfLife = EMOTION_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    emotions[key] = baseline + (emotions[key] - baseline) * decay;
  }

  // Trust: decay toward DEFAULT_TRUST baselines with per-domain half-lives
  const trust = { ...state.trust };
  for (const key of Object.keys(trust) as (keyof Trust)[]) {
    const baseline = DEFAULT_TRUST[key];
    const halfLife = TRUST_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    trust[key] = baseline + (trust[key] - baseline) * decay;
  }

  // Needs: decay toward 0 (depletion model)
  const needs = { ...state.needs };
  for (const key of Object.keys(needs) as (keyof Needs)[]) {
    const halfLife = NEED_DECAY_HOURS[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    needs[key] = needs[key] * decay;
  }

  // Personality: NO decay (glacial, only changed by evolve.py)

  // Relationship: decay toward DEFAULT_RELATIONSHIP baselines
  const relationship = { ...state.relationship };
  for (const key of Object.keys(relationship) as (keyof Relationship)[]) {
    const baseline = DEFAULT_RELATIONSHIP[key];
    const halfLife = RELATIONSHIP_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    relationship[key] = baseline + (relationship[key] - baseline) * decay;
  }

  return {
    ...state,
    emotions,
    trust,
    needs,
    relationship,
  };
}

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

// Turn-scoped cache to avoid redundant file reads + decay computation within a single turn
let _stateCache: { state: FullState; ts: number } | null = null;
const STATE_CACHE_TTL_MS = 5_000;

export function loadState(): FullState {
  if (_stateCache && Date.now() - _stateCache.ts < STATE_CACHE_TTL_MS) {
    return _stateCache.state;
  }

  const config = getConfig();
  const filePath = config.EMOTIONAL_STATE_FILE;

  let state: FullState = DEFAULT_FULL_STATE();

  try {
    if (fs.existsSync(filePath)) {
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

      // v1 files have no version field - merge with v2 defaults so new
      // categories (needs, personality, relationship) get default values
      // while existing emotion/trust values are preserved.
      const defaults = DEFAULT_FULL_STATE();

      // If the saved file has no personality section (v1 or brand-new state),
      // seed personality from the agent manifest instead of generic defaults.
      let personalityBase = defaults.personality;
      if (!raw.personality) {
        try {
          const manifestPath = `${config.AGENT_DIR}/data/agent.json`;
          if (fs.existsSync(manifestPath)) {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
            if (manifest.personality && typeof manifest.personality === 'object') {
              personalityBase = { ...defaults.personality, ...manifest.personality };
            }
          }
        } catch { /* fall back to generic defaults */ }
      }

      state = {
        version: 2,
        emotions: { ...defaults.emotions, ...raw.emotions },
        trust: { ...defaults.trust, ...raw.trust },
        needs: { ...defaults.needs, ...raw.needs },
        personality: { ...personalityBase, ...raw.personality },
        relationship: { ...defaults.relationship, ...raw.relationship },
        session_tone: raw.session_tone || null,
        last_updated: raw.last_updated || new Date().toISOString(),
      };
    } else {
      // No state file yet - seed personality from agent manifest.
      try {
        const manifestPath = `${config.AGENT_DIR}/data/agent.json`;
        if (fs.existsSync(manifestPath)) {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
          if (manifest.personality && typeof manifest.personality === 'object') {
            state = {
              ...state,
              personality: { ...state.personality, ...manifest.personality },
            };
          }
        }
      } catch { /* use generic defaults */ }
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

export function saveState(state: FullState): void {
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
  state: FullState,
  deltas: Partial<Emotions>,
): FullState {
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
  state: FullState,
  domain: keyof Trust,
  delta: number,
  reason = '',
  source = 'unknown',
): FullState {
  // Max +/-0.05 per call
  const clamped = clamp(delta, -0.05, 0.05);
  const trust = { ...state.trust };
  trust[domain] = Math.round(clamp(trust[domain] + clamped) * 1000) / 1000;
  const updated = { ...state, trust };
  saveState(updated);
  try {
    writeTrustLog(domain, clamped, trust[domain], reason, source);
  } catch (err) {
    // Log rather than silently swallow - trust history matters
    if (typeof console !== 'undefined') {
      console.warn(`[inner-life] trust_log write failed for ${domain}: ${err}`);
    }
  }
  return updated;
}

export function updateRelationship(
  state: FullState,
  dimension: keyof Relationship,
  delta: number,
): FullState {
  const relationship = { ...state.relationship };
  relationship[dimension] = Math.round(clamp(relationship[dimension] + delta) * 1000) / 1000;
  const updated = { ...state, relationship };
  saveState(updated);
  return updated;
}

export function updateNeeds(
  state: FullState,
  deltas: Partial<Needs>,
): FullState {
  const needs = { ...state.needs };
  for (const [key, delta] of Object.entries(deltas) as [keyof Needs, number][]) {
    if (key in needs) {
      needs[key] = Math.round(clamp(needs[key] + delta, 0, 10) * 1000) / 1000;
    }
  }
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}

/**
 * Restore trust values from the database audit trail.
 * Called on session start to recover trust state that may have been
 * lost to decay or app restart.
 */
export function reconcileTrustFromDb(): void {
  try {
    const { getLatestTrustValues } = require('./memory');
    const dbTrust = getLatestTrustValues() as Record<string, number>;
    if (!Object.keys(dbTrust).length) return;

    const state = loadState();
    const trust = { ...state.trust };
    let changed = false;
    for (const [domain, dbValue] of Object.entries(dbTrust)) {
      if (domain in trust) {
        const key = domain as keyof Trust;
        // Only restore if DB value is higher (trust was earned, shouldn't be lost to decay)
        if (dbValue > trust[key]) {
          trust[key] = dbValue;
          changed = true;
        }
      }
    }
    if (changed) {
      saveState({ ...state, trust });
    }
  } catch {
    // DB not available - skip reconciliation
  }
}

// ---------------------------------------------------------------------------
// Emotional vector encoding / decoding
// ---------------------------------------------------------------------------

// Packing layout (32 dims):
//   0-13:  14 emotions   (0.0-1.0, already normalised)
//   14-19:  6 trust      (0.0-1.0, already normalised)
//   20-27:  8 needs      (scaled /10 -> 0.0-1.0)
//   28-31:  spare (zeros)

const EMOTION_KEYS: (keyof Emotions)[] = [
  'connection', 'curiosity', 'confidence', 'warmth', 'frustration', 'playfulness',
  'amusement', 'anticipation', 'satisfaction', 'restlessness',
  'tenderness', 'melancholy', 'focus', 'defiance',
];

const TRUST_KEYS: (keyof Trust)[] = [
  'emotional', 'intellectual', 'creative', 'practical', 'operational', 'personal',
];

const NEED_KEYS: (keyof Needs)[] = [
  'stimulation', 'expression', 'purpose', 'autonomy',
  'recognition', 'novelty', 'social', 'rest',
];

export function encodeEmotionalVector(state: FullState): Float32Array {
  const vec = new Float32Array(32);
  EMOTION_KEYS.forEach((k, i) => { vec[i] = state.emotions[k]; });
  TRUST_KEYS.forEach((k, i) => { vec[14 + i] = state.trust[k]; });
  NEED_KEYS.forEach((k, i) => { vec[20 + i] = state.needs[k] / 10; });
  // positions 28-31 are spare, remain 0
  return vec;
}

export function decodeEmotionalVector(vec: Float32Array): Partial<FullState> {
  const emotions = {} as Emotions;
  EMOTION_KEYS.forEach((k, i) => { emotions[k] = vec[i]; });

  const trust = {} as Trust;
  TRUST_KEYS.forEach((k, i) => { trust[k] = vec[14 + i]; });

  const needs = {} as Needs;
  NEED_KEYS.forEach((k, i) => { needs[k] = vec[20 + i] * 10; });

  return { emotions, trust, needs };
}

export function vectorToBlob(vec: Float32Array): Buffer {
  return Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength);
}

export function blobToVector(blob: Buffer): Float32Array {
  // Copy so we don't hold a reference into a potentially reused buffer
  const copy = Buffer.alloc(blob.length);
  blob.copy(copy);
  return new Float32Array(copy.buffer, copy.byteOffset, copy.length / 4);
}

// ---------------------------------------------------------------------------
// Distributed state aggregation
// ---------------------------------------------------------------------------

/**
 * Time-weighted average of multiple emotional vectors.
 * Recent vectors receive exponentially more weight using:
 *   weight = 0.5 ^ (age_ms / halfLifeMs)
 *
 * Returns a Partial<FullState> decoded from the averaged vector,
 * or an empty object if no vectors are provided.
 */
export function computeDistributedState(
  vectors: Array<{ vec: Float32Array; timestamp: number }>,
  halfLifeMs = 3_600_000, // 1 hour default
): Partial<FullState> {
  if (vectors.length === 0) return {};

  const now = Date.now();
  const weightedSum = new Float32Array(32);
  let totalWeight = 0;

  for (const { vec, timestamp } of vectors) {
    const ageMs = Math.max(0, now - timestamp);
    const weight = Math.pow(0.5, ageMs / halfLifeMs);
    for (let i = 0; i < 32; i++) {
      weightedSum[i] += vec[i] * weight;
    }
    totalWeight += weight;
  }

  const averaged = new Float32Array(32);
  for (let i = 0; i < 32; i++) {
    averaged[i] = weightedSum[i] / totalWeight;
  }

  return decodeEmotionalVector(averaged);
}

// ---------------------------------------------------------------------------
// Format for context injection
// ---------------------------------------------------------------------------

export function formatForContext(state?: FullState): string {
  const s = state || loadState();
  const lines: string[] = ['## Internal State'];

  // Match Python order: connection, curiosity, warmth, frustration, playfulness, confidence
  // then append new v2 emotions
  const emotionOrder: (keyof Emotions)[] = [
    'connection', 'curiosity', 'warmth', 'frustration', 'playfulness', 'confidence',
    'amusement', 'anticipation', 'satisfaction', 'restlessness',
    'tenderness', 'melancholy', 'focus', 'defiance',
  ];
  for (const key of emotionOrder) {
    const value = s.emotions[key];
    if (value === undefined) continue;
    const label = emotionLabel(key, value);
    const name = key.charAt(0).toUpperCase() + key.slice(1);
    lines.push(`${name}: ${value.toFixed(2)} (${label})`);
  }

  const trustParts = Object.entries(s.trust).map(([d, v]) => `${d} ${v.toFixed(2)}`);
  lines.push(`\nTrust: ${trustParts.join(', ')}`);

  // Needs
  if (s.needs) {
    const needParts = Object.entries(s.needs).map(([n, v]) => `${n} ${(v as number).toFixed(1)}`);
    lines.push(`Needs: ${needParts.join(', ')}`);
  }

  // Relationship
  if (s.relationship) {
    const relParts = Object.entries(s.relationship).map(([r, v]) => `${r} ${(v as number).toFixed(2)}`);
    lines.push(`Relationship: ${relParts.join(', ')}`);
  }

  if (s.session_tone) {
    lines.push(`Session tone: ${s.session_tone}`);
  }

  return lines.join('\n');
}

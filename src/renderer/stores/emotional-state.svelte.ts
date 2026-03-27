/**
 * Inner life / emotional state - mirrors the agent's current feelings.
 * Updated via IPC from the main process after each inference turn.
 */

/** 14-dimensional emotional state matching inner-life-types.ts Emotions interface. */
export interface EmotionalState {
  connection: number;
  curiosity: number;
  confidence: number;
  warmth: number;
  frustration: number;
  playfulness: number;
  amusement: number;
  anticipation: number;
  satisfaction: number;
  restlessness: number;
  tenderness: number;
  melancholy: number;
  focus: number;
  defiance: number;
}

/** 6-domain trust model matching inner-life-types.ts Trust interface. */
export interface TrustState {
  emotional: number;
  intellectual: number;
  creative: number;
  practical: number;
  operational: number;
  personal: number;
}

export const emotionalState = $state<EmotionalState>({
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
  amusement: 0.2,
  anticipation: 0.3,
  satisfaction: 0.4,
  restlessness: 0.2,
  tenderness: 0.3,
  melancholy: 0.1,
  focus: 0.5,
  defiance: 0.05,
});

export const trustState = $state<TrustState>({
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
  operational: 0.5,
  personal: 0.5,
});

/** Apply an update from the main process (partial - only changed keys). */
export function applyEmotionUpdate(data: { emotions: Record<string, number>; trust: Record<string, number> }): void {
  if (data.emotions) {
    for (const [key, val] of Object.entries(data.emotions)) {
      if (key in emotionalState) {
        (emotionalState as unknown as Record<string, number>)[key] = val;
      }
    }
  }
  if (data.trust) {
    for (const [key, val] of Object.entries(data.trust)) {
      if (key in trustState) {
        (trustState as unknown as Record<string, number>)[key] = val;
      }
    }
  }
}

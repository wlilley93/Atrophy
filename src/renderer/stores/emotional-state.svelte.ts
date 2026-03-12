/**
 * Inner life / emotional state - mirrors the agent's current feelings.
 */

export interface EmotionalState {
  connection: number;
  curiosity: number;
  confidence: number;
  warmth: number;
  frustration: number;
  playfulness: number;
}

export interface TrustState {
  emotional: number;
  intellectual: number;
  creative: number;
  practical: number;
}

export const emotionalState = $state<EmotionalState>({
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
});

export const trustState = $state<TrustState>({
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
});

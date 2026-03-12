/**
 * Reactive session state.
 */

export type AppPhase = 'boot' | 'setup' | 'ready' | 'shutdown';
export type InferenceState = 'idle' | 'thinking' | 'streaming' | 'compacting';

// Svelte 5 runes - these are module-level reactive state
export const session = $state({
  phase: 'boot' as AppPhase,
  inferenceState: 'idle' as InferenceState,
  isRecording: false,
  idleSeconds: 0,
});

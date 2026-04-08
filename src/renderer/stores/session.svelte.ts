/**
 * Reactive session state.
 */

export type AppPhase = 'boot' | 'setup' | 'ready' | 'shutdown';
export type InferenceState = 'idle' | 'thinking' | 'streaming' | 'compacting';

// Svelte 5 runes - these are module-level reactive state
export const session = $state({
  phase: 'boot' as AppPhase,
  inferenceState: 'idle' as InferenceState,
  // Short human-readable label of what the agent is doing right this moment.
  // Driven by inference:thinkingDelta and inference:toolUse events. Cleared
  // on inference:done / inference:error / agent switch. The transcript's
  // ThinkingIndicator renders this next to the pulsing brain so the user
  // can see "thinking" / "using Bash" / "using Read" while waiting.
  currentActivity: '' as string,
  isRecording: false,
  idleSeconds: 0,
});

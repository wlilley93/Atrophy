/**
 * TTS playback queue state.
 */

export const audio = $state({
  queue: [] as string[],
  isPlaying: false,
  vignetteOpacity: 0,
});

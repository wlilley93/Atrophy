/**
 * Shared sentence/clause boundary detection for TTS synthesis.
 *
 * Constants are used by both inference paths (direct-spawn and tmux).
 * The `splitSentences` function is used by the tmux path for complete
 * messages; the direct-spawn path uses the constants inline for
 * incremental streaming.
 */

export const SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
export const CLAUSE_RE = /(?<=[,; \u2013\-])\s+/;
export const CLAUSE_SPLIT_THRESHOLD = 120;

/**
 * Split text into sentence-ish chunks for TTS synthesis.
 * Long sentences (>= CLAUSE_SPLIT_THRESHOLD) get further broken on clause boundaries
 * to keep TTS latency low.
 */
export function splitSentences(text: string): string[] {
  const sentences: string[] = [];
  const buffer = text;

  // Split on sentence boundaries first
  const parts = buffer.split(SENTENCE_RE);
  for (let i = 0; i < parts.length; i++) {
    const segment = parts[i].trim();
    if (!segment) continue;

    // For long segments, try clause-level splitting
    if (segment.length >= CLAUSE_SPLIT_THRESHOLD) {
      const cparts = segment.split(CLAUSE_RE);
      if (cparts.length > 1) {
        // Emit all but the last clause segment joined together, then the last separately
        const toEmit = cparts.slice(0, -1).join(' ').trim();
        const remainder = cparts[cparts.length - 1].trim();
        if (toEmit) sentences.push(toEmit);
        if (remainder) sentences.push(remainder);
        continue;
      }
    }
    sentences.push(segment);
  }

  return sentences;
}

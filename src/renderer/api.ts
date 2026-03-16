/**
 * Typed access to the preload API exposed via contextBridge.
 * Import this instead of using `(window as any).atrophy`.
 */
import type { AtrophyAPI } from '../preload/index';

/** The preload API, or null if not available (e.g. in tests). */
export const api: AtrophyAPI | null = (window as { atrophy?: AtrophyAPI }).atrophy ?? null;

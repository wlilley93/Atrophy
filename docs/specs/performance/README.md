# Performance

Optimizations applied to the Electron app to minimize perceived latency and keep the main thread responsive.

---

## Context Prefetch Cache (v1.2.4)

**Problem**: Every inference turn runs `buildAgencyContext()` which makes 2-6 synchronous SQLite queries plus 1-2 synchronous file reads on the Electron main thread. First-turn is worst at ~50-200ms because it opens 5+ other agent databases for cross-agent summaries. This is the primary cause of user-perceived lag between typing a message and seeing the thinking indicator.

**Solution**: Prefetch + cache, not worker threads. Worker threads would require serializing better-sqlite3 connections across thread boundaries (not supported - native addon). Instead:

1. `prefetchContext()` runs all queries during idle time and stores results in a module-level `ContextCache`
2. `buildAgencyContext()` reads from cache via `getCached(key, fallback)` with a 30-second TTL
3. If the cache is stale, queries fall through to direct execution (same behavior as before)

**Trigger points** (all via `setImmediate` to avoid blocking current work):
- App startup, after initialization completes
- After each `StreamDone` event (preloads for next message)
- After agent switch (invalidate + re-prefetch)

**Cached data**:
- `recentTurns` - last 4 agent turns (drift detection, adaptive effort)
- `sessionMood` - current session mood
- `recentSummaries` - last 10 summaries (session patterns)
- `lastSessionTime` - previous session start time (time gap)
- `activeThreads` - all active threads
- `crossAgentSummaries` - recent summaries from other agents' databases
- `emotionalState` - loaded + decayed emotional state

**Emotional state turn cache**: `loadState()` in `inner-life.ts` has a separate 5-second cache that eliminates the double read-parse-decay that occurred every turn (once for signal detection, once for `formatForContext()`). `saveState()` updates this cache so subsequent reads within the turn see the freshly written state.

**Result**:
- First-turn latency: ~50-200ms to ~0ms (prefetched during idle)
- Subsequent turn latency: ~5-20ms to ~0ms (cached from post-StreamDone prefetch)
- Emotional state double-load: eliminated
- No architecture changes, no new dependencies, no IPC changes

---

## Database Indexes (v1.2.4)

Added `idx_summaries_session_id` on `summaries(session_id)` to speed up cross-agent summary lookups in `getOtherAgentsRecentSummaries()`. This query joins summaries to sessions and was doing a full table scan on each other agent's database.

---

## Previous Optimizations

### Token Efficiency (v1.1.3)

Reduced token usage by ~65% through context trimming and prompt compression. See changelog for details.

### Lazy Brain Frames (v1.2.3)

Brain frame PNGs for the thinking indicator are loaded lazily instead of at startup. Memoized markdown rendering. Reduced polling intervals.

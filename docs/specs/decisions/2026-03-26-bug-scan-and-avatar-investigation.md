# 2026-03-26 - Bug Scan, Fixes, and Avatar Investigation

## Summary

Session covered three areas:
1. Repo-wide bug scan - 7 bugs found and fixed
2. Avatar regression investigation - companion's face replaced by static blue orb
3. CCBot stale-stderr notification explained

---

## 1. Bug Fixes (all applied, not yet committed)

### Files changed

```
src/main/channels/switchboard.ts    - MCP queue race condition
src/main/tts.ts                     - WriteStream error handling
src/main/channels/cron/scheduler.ts - Stale closure + disabled job reschedule
src/main/inference.ts               - Dead process ref leak
src/main/memory.ts                  - FD accumulation on agent switch
src/main/app.ts                     - closeForPath import + call in switchAgent
```

### Bug details

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `switchboard.ts` | **TOCTOU race** - `readFileSync` then `writeFileSync('[]')` on MCP queue file. Python MCP server can append envelopes between read and clear, silently dropping messages. | Atomic rename-then-restore: rename queue to temp, write empty `[]` immediately, read temp, delete temp. |
| 2+6 | `tts.ts` | **Unhandled WriteStream error** - no `error` listener on the WriteStream. Disk errors crash the process (unhandled stream event). Finish Promise has no reject path, so if the stream errors during flush, the TTS pipeline hangs forever (no more audio for the session). | Added early `error` listener, check `streamError` during write loop, added reject callback to finish Promise. |
| 3 | `scheduler.ts` | **Stale closure** - `delayMs` captured at schedule time, not re-evaluated when the 24h-capped timer fires. Jobs due in ~24h can be skipped entirely when `getNextRun()` returns the *next* occurrence because the intended one is now seconds in the past. | Re-evaluate remaining delay from `job.nextRun` inside the callback with a 5s tolerance window. |
| 7 | `scheduler.ts` | **Disabled job still rescheduled** - `.finally()` callback calls `scheduleCalendarJob()` after `executeJob()` disables the job via circuit breaker. Creates a stale timer and misleading `nextRun`. | Added `if (job.disabled) return` guard at top of `scheduleCalendarJob`. |
| 4 | `inference.ts` | **Dead process ref in `_allProcesses`** - `stopInference` removes from `_activeProcesses` but not `_allProcesses`. Concurrent calls from GUI and Telegram paths leave stale entries. | Added `_allProcesses.delete(proc)` in `stopInference`. |
| 5 | `memory.ts` + `app.ts` | **FD accumulation** - `connect()` caches DB connections per path, never closed on agent switch. Repeated switching accumulates open file descriptors toward the 256 limit. | Added `closeForPath(dbPath)` export. Called in `switchAgent` before config reload. |

### Verification

- `npx tsc --noEmit` passes cleanly (no new errors)
- Pre-existing diagnostics in `app.ts` (Switchboard type mismatch at line 644) and `daemon.ts` are unrelated

---

## 2. Avatar Investigation (unresolved - needs dev mode testing)

### Symptom

Companion agent's face video replaced by the static blue canvas orb (procedural fallback).

### What was checked

- **Files exist**: 34 `.mp4` loop files + `ambient_loop.mp4` in `~/.atrophy/agents/companion/avatar/`
- **Codec**: H.264/AVC - fully supported by Electron 34's Chromium
- **Permissions**: world-readable, play fine in QuickTime
- **CSP**: `media-src 'self' file:` explicitly allows file:// media
- **No protocol handler**: no custom Electron protocol registered for file access
- **No recent code changes**: OrbAvatar.svelte and window.ts avatar handlers unchanged in last 2 commits
- **Config**: `AVATAR_ENABLED: false` in config.json, but OrbAvatar doesn't check this flag
- **Running app**: packaged build at `~/Desktop/Atrophy.app`, built from commit `c0996f8` at 09:39

### Likely causes (ranked)

1. **Video element error** - Chromium's `<video>` hits an error loading from `file://` path. Could be a sandboxing issue in the packaged app, a codec negotiation failure, or a file access permission blocked by macOS sandbox. The `onVideoError` handler silently sets `videoError = true` and shows the canvas.
2. **Timing/reactivity** - `agents.current` not set before the effect runs, or a generation mismatch discarding the async result.
3. **Electron sandbox interaction** - `sandbox: true` in webPreferences may block `file://` video loading in newer Electron versions.

### Debug logging added

Added `console.log`/`console.error` to `OrbAvatar.svelte`:
- Effect trigger: logs agent name, ambient mode, change flags
- `onVideoCanPlay`: logs successful video load
- `onVideoError`: logs error code and message from `videoEl.error`
- Loop load: logs count and first file name

### Next steps

1. Run `pnpm dev` to start a dev instance
2. Open devtools (Cmd+Option+I) and check console for `[OrbAvatar]` logs
3. The logs will reveal whether:
   - The effect fires at all (agent name set?)
   - Loops are found (IPC handler working?)
   - Video errors (what error code?)
4. If it's an error code 4 (MEDIA_ERR_SRC_NOT_SUPPORTED), try registering a custom protocol
5. If it's a sandbox issue, consider using `net.fetch` + `protocol.handle` for local file serving
6. Remove the debug logging before shipping

---

## 3. CCBot Stale-Stderr Notification

### What happened

macOS notification: "ccbot may be stuck - Process alive but stderr log stale ... minutes. Restarting."

### Explanation

CCBot's health monitor watches stderr log freshness for each agent process. When the log hasn't been written to within the configured timeout, it assumes the process is stuck and restarts it.

### Common causes

- Long-running tool call (web search, MCP call) that produces no stderr
- Process idle between messages
- Actual hang (e.g. waiting on dead MCP server)

### Not a code bug

This is expected behavior from the health monitor. May need threshold tuning if it's triggering too aggressively on legitimate long operations (deep research tasks can run 6+ hours per the dispatch timeout).

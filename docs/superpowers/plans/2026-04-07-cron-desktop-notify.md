# Cron Desktop Notification with TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a macOS notification with a "Play" button when dispatched cron jobs produce output and the user is not away, triggering TTS playback on click.

**Architecture:** The telegram daemon emits an event after cron dispatch inference completes. A listener in app.ts shows an Electron Notification with an action button. On click, it synthesizes TTS using the agent's voice and plays it via the existing `playAudio()` pipeline (main process only, no renderer needed).

**Tech Stack:** Electron `Notification` API, existing `synthesise()` + `playAudio()` from tts.ts

**Spec:** `docs/superpowers/specs/2026-04-07-cron-desktop-notify-design.md`

---

### Task 1: Add Electron Notification with action button to notify.ts

**Files:**
- Modify: `src/main/notify.ts`

- [ ] **Step 1: Add Electron Notification import and new function**

Add to `src/main/notify.ts`:

```typescript
import { Notification } from 'electron';

/**
 * Show a macOS notification with a "Play" action button for cron output.
 * Returns a promise that resolves to true if the user clicked "Play".
 */
export function sendCronNotification(
  agentDisplayName: string,
  jobLabel: string,
  previewText: string,
): Promise<boolean> {
  return new Promise((resolve) => {
    const config = getConfig();
    if (!config.NOTIFICATIONS_ENABLED) {
      resolve(false);
      return;
    }

    const notification = new Notification({
      title: agentDisplayName,
      subtitle: jobLabel,
      body: previewText.length > 120 ? previewText.slice(0, 117) + '...' : previewText,
      silent: true,
      actions: [{ type: 'button', text: 'Play' }],
      hasReply: false,
    });

    let acted = false;

    notification.on('action', (_event, index) => {
      if (index === 0 && !acted) {
        acted = true;
        resolve(true);
      }
    });

    notification.on('close', () => {
      if (!acted) resolve(false);
    });

    // Auto-dismiss after 30 seconds if not interacted with
    setTimeout(() => {
      if (!acted) {
        acted = true;
        notification.close();
        resolve(false);
      }
    }, 30_000);

    notification.show();
  });
}
```

- [ ] **Step 2: Verify it compiles**

Run: `pnpm typecheck`
Expected: No new errors

- [ ] **Step 3: Commit**

```bash
git add src/main/notify.ts
git commit -m "feat(notify): add cron notification with Play action button"
```

---

### Task 2: Emit cron output event from telegram daemon

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts`

- [ ] **Step 1: Add EventEmitter import and export**

Near the top of `src/main/channels/telegram/daemon.ts`, add an exported event emitter for cron output:

```typescript
import { EventEmitter } from 'events';

// Emitted when a dispatched cron job's inference completes with output.
// Listeners receive: { agentName, agentDisplayName, jobName, text }
export const cronOutputEmitter = new EventEmitter();
```

- [ ] **Step 2: Emit the event after cron dispatch inference completes**

Find the block around line 870 where the cron dispatch response is finalized (after `log.info(`[${agentName}] completed in ${elapsed}`);`). Add the emission right after this log line:

```typescript
    // Notify desktop if this was a cron dispatch with output
    if (isCronDispatch && finalText) {
      const jobMatch = sourceLabel?.match(/cron:[\w]+\.([\w_]+)/);
      const jobName = jobMatch ? jobMatch[1].replace(/_/g, ' ') : 'Scheduled job';
      cronOutputEmitter.emit('output', {
        agentName,
        agentDisplayName: agent.display_name || agentName,
        jobName,
        text: finalText,
      });
    }
```

Note: `agent` is in scope here - it's the agent config object used throughout the dispatch function. `sourceLabel` contains the envelope source (e.g. `Scheduled job result - cron:general_montgomery.dashboard_brief`).

- [ ] **Step 3: Verify it compiles**

Run: `pnpm typecheck`
Expected: No new errors

- [ ] **Step 4: Commit**

```bash
git add src/main/channels/telegram/daemon.ts
git commit -m "feat(cron): emit event when dispatched cron output is ready"
```

---

### Task 3: Wire notification + TTS in app.ts

**Files:**
- Modify: `src/main/app.ts`

- [ ] **Step 1: Add imports**

Add near the other imports in `src/main/app.ts`:

```typescript
import { sendCronNotification } from './notify';
import { cronOutputEmitter } from './channels/telegram/daemon';
import { synthesise, playAudio } from './tts';
```

Check that `synthesise` and `playAudio` aren't already imported. If they are, just add `sendCronNotification` and `cronOutputEmitter`.

- [ ] **Step 2: Add the listener after cron scheduler starts**

Find the section where the cron scheduler is started (around `cronScheduler.start()`). After the cron scheduler start block, add:

```typescript
    // Listen for dispatched cron output - show notification with Play button
    cronOutputEmitter.on('output', async (data: { agentName: string; agentDisplayName: string; jobName: string; text: string }) => {
      // Only notify if user is at their desk
      if (isAway()) return;

      const jobLabel = data.jobName.charAt(0).toUpperCase() + data.jobName.slice(1);
      const played = await sendCronNotification(data.agentDisplayName, jobLabel, data.text);

      if (played) {
        log.info(`[cron-notify] Playing TTS for ${data.agentName}.${data.jobName}`);
        try {
          // Reload config for the agent to get the right voice
          const cfg = getConfig();
          const prevAgent = cfg.AGENT_NAME;
          if (cfg.AGENT_NAME !== data.agentName) {
            cfg.reloadForAgent(data.agentName);
          }

          const audioPath = await synthesise(data.text);
          if (audioPath) {
            await playAudio(audioPath);
          }

          // Restore config
          if (cfg.AGENT_NAME !== prevAgent) {
            cfg.reloadForAgent(prevAgent);
          }
        } catch (err) {
          log.error(`[cron-notify] TTS failed: ${err}`);
        }
      }
    });
```

- [ ] **Step 3: Verify it compiles**

Run: `pnpm typecheck`
Expected: No new errors

- [ ] **Step 4: Manual test**

Build and install:
```bash
pnpm run pack
kill $(pgrep -f "Atrophy.app/Contents/MacOS/Atrophy") 2>/dev/null
sleep 2
rm -rf ~/Applications/Atrophy.app
cp -R dist/mac-arm64/Atrophy.app ~/Applications/Atrophy.app
echo "[]" > ~/.atrophy/crash-log.json
open ~/Applications/Atrophy.app
```

Wait for a dispatched cron job to fire (e.g. Montgomery's dashboard_brief runs every 4 hours, or heartbeat runs periodically). When it fires:
- A macOS notification should appear with the agent name and preview text
- Clicking "Play" should trigger TTS playback of the full response
- If the user is away, no notification should appear

For faster testing, temporarily trigger a heartbeat job from the app's Jobs tab in Settings.

- [ ] **Step 5: Commit**

```bash
git add src/main/app.ts
git commit -m "feat(cron): wire notification + TTS playback for desktop delivery"
```

---

## Summary

| Task | Description | File |
|------|-------------|------|
| 1 | Electron Notification with Play button | `notify.ts` |
| 2 | Emit event from telegram daemon | `daemon.ts` |
| 3 | Wire notification + TTS in app boot | `app.ts` |

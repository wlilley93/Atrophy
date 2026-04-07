# Cron Output Desktop Notification with TTS

**Date**: 2026-04-07
**Status**: Draft

## Problem

When cron jobs produce dispatched output (e.g. Montgomery's dashboard brief, flash reports), the results only go to Telegram. If the user is at their desk (not away), they don't see or hear the output until they check Telegram.

## Solution

When a dispatched cron job produces output and the user is not away, show a macOS notification with the agent name, a brief preview, and a "Play" action button. Clicking "Play" synthesizes TTS for the full output and plays it through the existing audio pipeline - no app window focus needed.

## Flow

```
Cron job completes with output
  -> switchboard routes to agent
  -> telegram daemon receives (existing)
     -> dispatches to telegram (existing, unchanged)
     -> NEW: if !isAway(), emit 'cron:output-ready' event
  -> main process listener picks up event
     -> show Electron Notification with "Play" action
     -> on action click: synthesize TTS, play audio
```

## Implementation

### Notification trigger

In `src/main/channels/telegram/daemon.ts`, after the existing dispatch logic for cron output, add an event emission when the user is not away. This happens after inference completes (so the formatted response text is available), not on raw cron output.

The event carries:
- `agentName` - for display and TTS voice selection
- `agentDisplayName` - for the notification title
- `text` - the full formatted response text (post-inference)
- `jobName` - for the notification subtitle

### Notification display

In `src/main/notify.ts`, add a new function `sendCronNotification()` that uses Electron's `Notification` class (not AppleScript) to show a notification with:
- **Title**: agent display name (e.g. "General Montgomery")
- **Body**: first 100 chars of the response text, truncated with "..."
- **Subtitle**: job name in human-readable form (e.g. "Dashboard Brief")
- **Actions**: `[{ type: 'button', text: 'Play' }]`

On the `'action'` event, call the TTS pipeline to synthesize and play the full text.

### TTS playback

The existing `synthesise()` and `enqueueAudio()` functions in `tts.ts` handle synthesis and playback. The notification handler:

1. Temporarily reloads config for the agent (to get the right voice)
2. Calls `synthesise(text)` to generate audio
3. Calls `playAudio(audioPath)` or sends the audio buffer to the renderer for Web Audio playback

Since TTS playback currently requires the renderer (Web Audio API), the notification handler sends an IPC message to the renderer to play the audio. The renderer doesn't need to be focused - Web Audio plays in the background.

### Guard conditions

Only show the notification when ALL of:
- `!isAway()` - user is not away
- `config.NOTIFICATIONS_ENABLED` - notifications are enabled
- The cron output was dispatched (has the `dispatch` flag)
- Inference completed successfully (has response text)

### What changes

| File | Change |
|------|--------|
| `src/main/channels/telegram/daemon.ts` | Emit event after cron dispatch inference completes |
| `src/main/notify.ts` | Add `sendCronNotification()` using Electron Notification API |
| `src/main/app.ts` | Listen for cron output event, wire notification + TTS |

### What doesn't change

- Cron runner, scheduler, job definitions
- Telegram dispatch flow (notification is additive, not replacing)
- TTS pipeline internals
- Desktop transcript/conversation
- Status tracking

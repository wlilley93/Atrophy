# Per-Agent Delivery Channel Mode

**Date:** 2026-03-26
**Status:** Approved

## Problem

Cron job output currently routes exclusively through Telegram. There is no status-based routing (desktop when active, Telegram when away) and no way to send to both channels simultaneously. Agents in shared Telegram groups should be able to deliver to both desktop and Telegram at once so both the user at their computer and friends in the group see updates.

## Solution

Repurpose the existing (but unused) `notify_via` manifest field as a per-agent delivery channel mode. Three values:

| Value | Desktop (voice/GUI) | Telegram | Use case |
|-------|---------------------|----------|----------|
| `"auto"` | When user is active | When user is away | Default - personal agents |
| `"telegram"` | Never | Always | Telegram-only agents |
| `"both"` | Always | Always | Agents in shared groups |

### Manifest storage

Root-level field in `agent.json`:

```json
{
  "name": "general_montgomery",
  "notify_via": "both",
  ...
}
```

Default is `"auto"` if the field is missing.

### Routing decision point

The telegram daemon's `onMessage` callback in `registerAgentSwitchboard()` is where all dispatched cron output flows. This is the single decision point.

When a cron envelope arrives with `metadata.dispatch === true`:

1. Read `notify_via` from the agent's config (default `"auto"`)
2. Read user status via `getStatus()`
3. Determine which channels to deliver to:
   - `"auto"` + active -> desktop only
   - `"auto"` + away -> telegram only
   - `"telegram"` -> telegram only
   - `"both"` -> desktop AND telegram
4. Execute delivery for each selected channel

### Desktop delivery

For desktop delivery, the cron output needs to go through inference and appear in the transcript with TTS. The telegram daemon already calls `dispatchToAgent()` which runs `streamInference()`. For desktop delivery, we add a parallel path:

1. Send `inference:textDelta` / `inference:done` events to `mainWindow.webContents` so the transcript shows the response
2. TTS synthesis happens in the existing inference event handler (SentenceReady events)

The simplest implementation: extract a `dispatchToDesktop()` function that runs inference and pipes events to the renderer, mirroring how `dispatchToAgent()` pipes to Telegram. Both functions call `streamInference()` with the same prompt - the difference is where the output goes.

For `"both"` mode, run inference once and fan out the result text to both channels rather than running inference twice.

### Settings UI

In SettingsTab's agent list, add a delivery mode dropdown next to each agent:

```
[Companion]    [auto ▾]      [mute] [enable]
[Montgomery]   [both ▾]      [mute] [enable]
```

Dropdown options: Auto, Telegram, Both.

Saves via `saveAgentConfig(agentName, { NOTIFY_VIA: value })`.

### Config plumbing

- `Config` class: add `NOTIFY_VIA: string` field, default `'auto'`
- Constructor: `this.NOTIFY_VIA = 'auto';`
- `reloadForAgent()`: `this.NOTIFY_VIA = (_agentManifest.notify_via as string) || 'auto';`
- `AGENT_KEY_ROOT`: add `NOTIFY_VIA: 'notify_via'`

## Files changed

| File | Change |
|------|--------|
| `src/main/config.ts` | Add `NOTIFY_VIA` field, default, manifest loading, key mapping |
| `src/main/channels/telegram/daemon.ts` | Routing logic in onMessage: check notify_via + status, add `dispatchToDesktop()`, fan-out for "both" mode |
| `src/main/status.ts` | No changes needed - `getStatus()` already returns active/away |
| `src/renderer/components/settings/SettingsTab.svelte` | Add delivery mode dropdown per agent |
| `src/preload/index.ts` | No changes needed - config already exposed via `getConfig()` |

## Edge cases

- **Desktop not available (menu bar mode, no window):** Fall back to telegram regardless of setting. Check `mainWindow` before attempting desktop delivery.
- **Telegram not configured for agent:** Skip telegram delivery. Only deliver to desktop.
- **"both" mode inference:** Run inference once, send the full response text to both channels. Don't run inference twice.
- **Non-cron messages (user messages from Telegram):** This setting only affects cron/job output delivery. User messages from Telegram always respond on Telegram. User messages from desktop always respond on desktop.

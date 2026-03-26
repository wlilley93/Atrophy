# src/main/notify.ts - macOS Native Notifications

**Line count:** ~50 lines  
**Dependencies:** `child_process`, `./config`, `./logger`  
**Purpose:** Send macOS native notifications via AppleScript

## Overview

This module provides a simple wrapper for sending macOS native notifications using `osascript` (AppleScript). It's gated by the `NOTIFICATIONS_ENABLED` config flag.

**Port of:** `core/notify.py`

## sendNotification

```typescript
export function sendNotification(
  title: string,
  body: string,
  subtitle = '',
): void {
  const config = getConfig();
  if (!config.NOTIFICATIONS_ENABLED) return;

  // Escape for AppleScript string literals
  const escape = (s: string) =>
    s.replace(/\\/g, '\\\\')
      .replace(/"/g, '\\"')
      .replace(/\n/g, ' ')
      .replace(/\r/g, ' ');

  const t = escape(title);
  const b = escape(body);
  const s = escape(subtitle);

  const script = subtitle
    ? `display notification "${b}" with title "${t}" subtitle "${s}"`
    : `display notification "${b}" with title "${t}"`;

  try {
    // Pass script via stdin using osascript's '-' flag to avoid
    // shell injection from quotes in notification text
    execSync('osascript -', {
      input: script,
      timeout: 5000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch (e) {
    log.error(`failed: ${e}`);
  }
}
```

**Purpose:** Send macOS native notification.

**Parameters:**
- `title`: Notification title
- `body`: Notification body
- `subtitle`: Optional subtitle

**Security features:**
1. String escaping for AppleScript literals
2. Script passed via stdin (`osascript -`) to avoid shell injection
3. 5-second timeout

**Escaping:**
- Backslash → `\\`
- Double quote → `\"`
- Newline → space
- Carriage return → space

## Usage Examples

```typescript
// Simple notification
sendNotification('Morning Brief', 'Here\'s your daily update');

// With subtitle
sendNotification('Heartbeat', 'Thinking of you', 'Quick check-in');

// From heartbeat job
sendNotification('Heartbeat', message);

// From morning-brief job
sendNotification('Morning Brief', brief.slice(0, 200));
```

## Configuration

Gated by `NOTIFICATIONS_ENABLED` in config:

```typescript
const config = getConfig();
if (!config.NOTIFICATIONS_ENABLED) return;
```

**Default:** `true`

**Disable via:** Settings panel or config.json

## Error Handling

```typescript
try {
  execSync('osascript -', {
    input: script,
    timeout: 5000,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
} catch (e) {
  log.error(`failed: ${e}`);
}
```

**Behavior:** Errors are logged but don't throw - notifications are non-critical.

## File I/O

None - uses system notification service via AppleScript.

## Exported API

| Function | Purpose |
|----------|---------|
| `sendNotification(title, body, subtitle)` | Send macOS notification |

## See Also

- `src/main/jobs/heartbeat.ts` - Uses sendNotification
- `src/main/jobs/morning-brief.ts` - Uses sendNotification
- `src/main/config.ts` - NOTIFICATIONS_ENABLED config

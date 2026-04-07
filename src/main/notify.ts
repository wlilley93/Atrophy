/**
 * macOS native notification helper.
 * Port of core/notify.py.
 *
 * Uses AppleScript (osascript) for reliability.
 * Gated by NOTIFICATIONS_ENABLED config.
 */

import { execSync } from 'child_process';
import { Notification } from 'electron';
import { getConfig } from './config';
import { createLogger } from './logger';

const log = createLogger('notify');

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

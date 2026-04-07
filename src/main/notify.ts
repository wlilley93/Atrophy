/**
 * macOS native notification helper.
 *
 * Uses Electron's Notification API so notifications show the Atrophy
 * app icon instead of the generic Script Editor icon.
 * Gated by NOTIFICATIONS_ENABLED config.
 */

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

  try {
    const notification = new Notification({
      title,
      subtitle: subtitle || undefined,
      body: body.replace(/\n/g, ' ').slice(0, 200),
      silent: false,
    });
    notification.show();
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

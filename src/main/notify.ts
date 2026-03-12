/**
 * macOS native notification helper.
 * Port of core/notify.py.
 *
 * Uses AppleScript (osascript) for reliability.
 * Gated by NOTIFICATIONS_ENABLED config.
 */

import { execSync } from 'child_process';
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
    // Use -e with double quotes and pass the script via stdin to avoid
    // shell injection from single quotes in notification text
    execSync('osascript', {
      input: script,
      timeout: 5000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch (e) {
    log.error(`failed: ${e}`);
  }
}

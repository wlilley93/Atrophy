/**
 * macOS native notification helper.
 * Port of core/notify.py.
 *
 * Uses AppleScript (osascript) for reliability.
 * Gated by NOTIFICATIONS_ENABLED config.
 */

import { execSync } from 'child_process';
import { getConfig } from './config';

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
    execSync(`osascript -e '${script}'`, { timeout: 5000, stdio: 'pipe' });
  } catch (e) {
    console.log(`[notify] failed: ${e}`);
  }
}

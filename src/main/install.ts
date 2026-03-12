/**
 * Login item management for Atrophy.
 *
 * Uses Electron's built-in app.setLoginItemSettings() instead of
 * manual launchd plist generation (which the Python version used).
 *
 * The app can be set to launch at login in menu bar mode (--app flag).
 */

import { app } from 'electron';

export function isLoginItemEnabled(): boolean {
  const settings = app.getLoginItemSettings();
  return settings.openAtLogin;
}

export function enableLoginItem(): void {
  app.setLoginItemSettings({
    openAtLogin: true,
    openAsHidden: true,
    args: ['--app'],
  });
}

export function disableLoginItem(): void {
  app.setLoginItemSettings({
    openAtLogin: false,
  });
}

export function toggleLoginItem(enabled: boolean): void {
  if (enabled) {
    enableLoginItem();
  } else {
    disableLoginItem();
  }
}

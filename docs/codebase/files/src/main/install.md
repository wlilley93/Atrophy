# src/main/install.ts - Login Item Management

**Dependencies:** `electron`  
**Purpose:** Manage macOS login item (launch at login) using Electron's built-in API

## Overview

This module manages whether the app launches automatically at user login. It uses Electron's built-in `app.setLoginItemSettings()`.

The app can be set to launch at login in menu bar mode (`--app` flag).

## Functions

### isLoginItemEnabled

```typescript
export function isLoginItemEnabled(): boolean {
  const settings = app.getLoginItemSettings();
  return settings.openAtLogin;
}
```

**Returns:** `true` if app is set to launch at login

### enableLoginItem

```typescript
export function enableLoginItem(): void {
  app.setLoginItemSettings({
    openAtLogin: true,
    openAsHidden: true,
    args: ['--app'],
  });
}
```

**Settings:**
- `openAtLogin: true` - Launch at login
- `openAsHidden: true` - Start hidden (menu bar mode)
- `args: ['--app']` - Launch with `--app` flag for menu bar mode

### disableLoginItem

```typescript
export function disableLoginItem(): void {
  app.setLoginItemSettings({
    openAtLogin: false,
  });
}
```

**Purpose:** Remove from login items

### toggleLoginItem

```typescript
export function toggleLoginItem(enabled: boolean): void {
  if (enabled) {
    enableLoginItem();
  } else {
    disableLoginItem();
  }
}
```

**Purpose:** Enable or disable login item based on boolean

## IPC Handlers

In `src/main/ipc/system.ts`:

```typescript
ipcMain.handle('install:isEnabled', () => {
  return isLoginItemEnabled();
});

ipcMain.handle('install:toggle', (_event, enabled: boolean) => {
  toggleLoginItem(enabled);
});
```

## macOS Behavior

When enabled, macOS will:
1. Launch the app at user login
2. Start with `--app` flag (menu bar mode)
3. Keep the app hidden (only tray icon visible)

## Exported API

| Function | Purpose |
|----------|---------|
| `isLoginItemEnabled()` | Check if login item is enabled |
| `enableLoginItem()` | Enable login item |
| `disableLoginItem()` | Disable login item |
| `toggleLoginItem(enabled)` | Toggle login item state |

## See Also

- `src/main/ipc/system.ts` - install:* IPC handlers
- `src/renderer/components/Settings.svelte` - Login item toggle UI

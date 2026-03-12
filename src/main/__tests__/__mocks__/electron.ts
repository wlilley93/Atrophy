/**
 * Minimal mock of the electron module for vitest.
 * Only stubs the properties accessed at module-level in config.ts.
 */

export const app = {
  isPackaged: false,
  getPath: (name: string) => `/tmp/atrophy-test/${name}`,
  getName: () => 'atrophy-test',
  getVersion: () => '0.0.0-test',
};

export const ipcMain = {
  handle: () => {},
  on: () => {},
};

export const BrowserWindow = class {
  constructor() {}
};

export default { app, ipcMain, BrowserWindow };

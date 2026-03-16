/**
 * Entry point for the Electron main process.
 *
 * In production (packaged app), bootstrap.ts is the real entry point.
 * It detects hot bundles and loads app.ts from either the hot bundle
 * or the frozen asar.
 *
 * In development, electron-vite points here directly, and we just
 * load app.ts which does everything.
 */

import './app';

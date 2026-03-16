/**
 * Thin bootstrap - the only file that MUST stay in the asar.
 *
 * Its job: detect a hot bundle at ~/.atrophy/bundle/out/main/app.js,
 * then dynamically import either the hot version or the frozen app.js.
 *
 * This file should rarely change. Changes here require a DMG release.
 * Everything else can ship via hot bundle updates.
 */

import { app } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { pathToFileURL } from 'url';

const USER_DATA = process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy');
const BUNDLE_DIR = path.join(USER_DATA, 'bundle');
const MANIFEST_PATH = path.join(BUNDLE_DIR, 'bundle-manifest.json');
const HOT_APP = path.join(BUNDLE_DIR, 'out', 'main', 'app.js');
const FROZEN_APP = path.join(__dirname, 'app.js');

// Sentinel file to detect boot crashes - if present at startup, the last
// hot boot crashed within 10 seconds so we skip the hot bundle this time.
const BOOT_SENTINEL = path.join(BUNDLE_DIR, '.booting');

// ---------------------------------------------------------------------------
// Semver comparison (inlined - bootstrap must not import app modules)
// ---------------------------------------------------------------------------

function isNewer(a: string, b: string): boolean {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const va = pa[i] || 0;
    const vb = pb[i] || 0;
    if (va > vb) return true;
    if (va < vb) return false;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot(): Promise<void> {
  // Skip hot loading in dev
  if (process.env.ELECTRON_RENDERER_URL || !app.isPackaged) {
    await import(pathToFileURL(FROZEN_APP).href);
    return;
  }

  // Allow force-skipping hot bundle for debugging
  if (process.env.ATROPHY_SKIP_HOT_BUNDLE === '1') {
    console.log('[bootstrap] ATROPHY_SKIP_HOT_BUNDLE=1, using frozen app');
    await import(pathToFileURL(FROZEN_APP).href);
    return;
  }

  let useHot = false;

  try {
    // Check if last hot boot crashed (sentinel still present from a dead process)
    if (fs.existsSync(BOOT_SENTINEL)) {
      // Check if the PID in the sentinel is still alive (race condition guard)
      let stale = true;
      try {
        const pid = parseInt(fs.readFileSync(BOOT_SENTINEL, 'utf-8').trim(), 10);
        if (pid && pid !== process.pid) {
          try { process.kill(pid, 0); stale = false; } catch { /* process dead - sentinel is stale */ }
        }
      } catch { /* unreadable sentinel */ }

      if (stale) {
        console.warn('[bootstrap] previous hot boot crashed, skipping hot bundle this time');
        try { fs.unlinkSync(BOOT_SENTINEL); } catch { /* ignore */ }
        // Fall through to frozen
      }
    } else if (fs.existsSync(MANIFEST_PATH) && fs.existsSync(HOT_APP)) {
      const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));
      if (manifest?.version && isNewer(manifest.version, app.getVersion())) {
        useHot = true;
      }
    }
  } catch {
    // Any error reading manifest - fall through to frozen
  }

  if (useHot) {
    // Write boot sentinel with PID - cleared after 10 seconds of successful running
    try {
      fs.mkdirSync(BUNDLE_DIR, { recursive: true });
      fs.writeFileSync(BOOT_SENTINEL, String(process.pid));
    } catch { /* non-fatal */ }

    // Tell the app code it's running from a hot bundle
    process.env.ATROPHY_HOT_BOOT = '1';

    try {
      console.log(`[bootstrap] loading hot bundle from ${HOT_APP}`);
      await import(pathToFileURL(HOT_APP).href);

      // Clear sentinel after 10 seconds - boot succeeded
      setTimeout(() => {
        try { fs.unlinkSync(BOOT_SENTINEL); } catch { /* already gone */ }
      }, 10_000).unref();

      return;
    } catch (err) {
      console.error('[bootstrap] hot bundle failed, falling back to frozen:', err);
      // Remove bad manifest so we don't retry next boot
      try { fs.unlinkSync(MANIFEST_PATH); } catch { /* ignore */ }
      try { fs.unlinkSync(BOOT_SENTINEL); } catch { /* ignore */ }
    }
  }

  // Frozen fallback
  try {
    await import(pathToFileURL(FROZEN_APP).href);
  } catch (fatalErr) {
    console.error('[bootstrap] FATAL: frozen app.js failed to load:', fatalErr);
    const { dialog } = await import('electron');
    dialog.showErrorBox(
      'Atrophy failed to start',
      `The app could not load. Try reinstalling.\n\n${fatalErr instanceof Error ? fatalErr.message : String(fatalErr)}`,
    );
    app.exit(1);
  }
}

boot();

/**
 * Downloads avatar assets from GitHub Releases on first launch.
 * Assets are extracted to ~/.atrophy/agents/<name>/avatar/.
 *
 * Supports per-agent asset URLs via agent.json `avatar_asset_url` field.
 * Falls back to the default Xan asset URL for the xan agent.
 */

import * as fs from 'fs';
import * as path from 'path';
import { execFile } from 'child_process';
import { BrowserWindow } from 'electron';
import { BUNDLE_ROOT, USER_DATA } from './config';
import { createLogger } from './logger';

const log = createLogger('avatar-downloader');

const DEFAULT_AVATAR_URL =
  'https://github.com/wlilley93/Atrophy/releases/download/avatar-assets-v1/xan-avatar-v1.tar.gz';
const AMBIENT_VIDEO_URL =
  'https://github.com/wlilley93/Atrophy/releases/download/avatar-assets-v1/xan_ambient.mp4';
const MARKER = '.avatar-complete';
const AMBIENT_MARKER = '.ambient-complete';

/** Check if avatar assets are already present for the given agent. */
export function isAvatarComplete(agentName: string): boolean {
  const avatarDir = path.join(USER_DATA, 'agents', agentName, 'avatar');
  if (fs.existsSync(path.join(avatarDir, MARKER))) return true;
  // Also accept if loops dir exists with at least one mp4
  const loopsDir = path.join(avatarDir, 'loops');
  if (fs.existsSync(loopsDir)) {
    try {
      const entries = fs.readdirSync(loopsDir);
      if (entries.some((e) => e.endsWith('.mp4'))) return true;
    } catch { /* empty */ }
  }
  return false;
}

/**
 * Resolve the avatar asset URL for a given agent.
 * Checks agent.json for `avatar_asset_url`, falls back to default for xan.
 */
function resolveAssetUrl(agentName: string): string | null {
  // Check agent manifests (user data first, then bundle)
  for (const base of [USER_DATA, BUNDLE_ROOT]) {
    const jsonPath = path.join(base, 'agents', agentName, 'data', 'agent.json');
    try {
      if (!fs.existsSync(jsonPath)) continue;
      const manifest = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
      if (manifest.avatar_asset_url) return manifest.avatar_asset_url;
    } catch { continue; }
  }
  // Default fallback for xan
  if (agentName === 'xan') return DEFAULT_AVATAR_URL;
  return null;
}

/**
 * Download and extract avatar assets. Non-blocking, non-fatal.
 *
 * Events emitted to the renderer (via win.webContents.send):
 *   avatar:download-start
 *   avatar:download-progress  { percent, transferred, total }
 *   avatar:download-complete
 *   avatar:download-error     string
 */
export async function ensureAvatarAssets(
  agentName: string,
  win: BrowserWindow | null,
): Promise<void> {
  if (isAvatarComplete(agentName)) return;

  const assetUrl = resolveAssetUrl(agentName);
  if (!assetUrl) {
    // No asset URL configured - signal completion so listeners don't hang
    win?.webContents.send('avatar:download-complete');
    return;
  }

  const agentDir = path.join(USER_DATA, 'agents', agentName);
  fs.mkdirSync(agentDir, { recursive: true });
  const tarPath = path.join(agentDir, `${agentName}-avatar.tar.gz`);

  log.info(`downloading avatar assets for ${agentName}...`);
  win?.webContents.send('avatar:download-start');

  try {
    // Download
    const res = await fetch(assetUrl, { redirect: 'follow' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const total = parseInt(res.headers.get('content-length') || '0', 10);
    let transferred = 0;
    let lastEmit = 0;

    const fileStream = fs.createWriteStream(tarPath);
    const reader = res.body?.getReader();
    if (!reader) throw new Error('no response body');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      fileStream.write(value);
      transferred += value.byteLength;

      const now = Date.now();
      if (total > 0 && now - lastEmit > 500) {
        const percent = Math.round((transferred / total) * 100);
        win?.webContents.send('avatar:download-progress', { percent, transferred, total });
        lastEmit = now;
      }
    }

    await new Promise<void>((resolve, reject) => {
      fileStream.end(() => resolve());
      fileStream.on('error', reject);
    });

    log.info('extracting avatar assets...');

    // Extract - tar contents have avatar/ at root
    await new Promise<void>((resolve, reject) => {
      execFile('tar', ['-xzf', tarPath, '-C', agentDir], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });

    // Write marker
    const avatarDir = path.join(agentDir, 'avatar');
    fs.mkdirSync(avatarDir, { recursive: true });
    fs.writeFileSync(path.join(avatarDir, MARKER), new Date().toISOString());

    // Cleanup tar
    fs.unlinkSync(tarPath);

    log.info('avatar assets ready');
    win?.webContents.send('avatar:download-complete');
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`avatar download failed: ${msg}`);
    win?.webContents.send('avatar:download-error', msg);
    // Cleanup partial tar
    try { fs.unlinkSync(tarPath); } catch { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Ambient video download (xan_ambient.mp4)
// ---------------------------------------------------------------------------

/** Path where the ambient video is stored after download. */
export function getAmbientVideoPath(): string {
  return path.join(USER_DATA, 'assets', 'xan_ambient.mp4');
}

/** Check if ambient video is already downloaded. */
export function isAmbientVideoReady(): boolean {
  const assetsDir = path.join(USER_DATA, 'assets');
  return fs.existsSync(path.join(assetsDir, AMBIENT_MARKER));
}

/**
 * Download the ambient video if not already present.
 * Reuses the same progress events as avatar download.
 */
export async function ensureAmbientVideo(
  win: BrowserWindow | null,
): Promise<void> {
  if (isAmbientVideoReady()) return;

  const assetsDir = path.join(USER_DATA, 'assets');
  fs.mkdirSync(assetsDir, { recursive: true });
  const outPath = getAmbientVideoPath();

  log.info('downloading ambient video...');
  win?.webContents.send('avatar:download-start');

  try {
    const res = await fetch(AMBIENT_VIDEO_URL, { redirect: 'follow' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const total = parseInt(res.headers.get('content-length') || '0', 10);
    let transferred = 0;
    let lastEmit = 0;

    const fileStream = fs.createWriteStream(outPath);
    const reader = res.body?.getReader();
    if (!reader) throw new Error('no response body');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      fileStream.write(value);
      transferred += value.byteLength;

      const now = Date.now();
      if (total > 0 && now - lastEmit > 500) {
        const percent = Math.round((transferred / total) * 100);
        win?.webContents.send('avatar:download-progress', { percent, transferred, total });
        lastEmit = now;
      }
    }

    await new Promise<void>((resolve, reject) => {
      fileStream.end(() => resolve());
      fileStream.on('error', reject);
    });

    // Write marker
    fs.writeFileSync(path.join(assetsDir, AMBIENT_MARKER), new Date().toISOString());
    log.info('ambient video ready');
    win?.webContents.send('avatar:download-complete');
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.error(`ambient video download failed: ${msg}`);
    win?.webContents.send('avatar:download-error', msg);
    // Cleanup partial download
    try { fs.unlinkSync(outPath); } catch { /* ignore */ }
  }
}

/**
 * Hot bundle updater - pulls new compiled JS from GitHub on boot.
 *
 * Instead of rebuilding and distributing a new DMG for every change,
 * this module downloads pre-built `out/` bundles from GitHub Releases
 * to `~/.atrophy/bundle/`. On the NEXT boot, the app loads from the
 * hot bundle instead of the frozen one inside the .app.
 *
 * Architecture:
 *   - bootstrap.ts (frozen in asar) is the entry point. It never changes.
 *   - app.ts (hot-loadable) contains all real app logic.
 *   - bootstrap.ts checks for ~/.atrophy/bundle/out/main/app.js and
 *     require()s it if the version is newer than the frozen one.
 *   - Preload + renderer are also loaded from the hot bundle.
 *   - Native modules (better-sqlite3 etc.) always resolve from the asar.
 *
 * Release asset convention:
 *   - A GitHub Release tagged `bundle-vX.Y.Z` (or any tag)
 *   - Must contain `bundle.tar.gz` - a tarball of the `out/` directory
 *     (excluding out/main/index.js which is the bootstrap)
 *   - Must contain `bundle-manifest.json` with { version, sha256, timestamp }
 *
 * Boot sequence (handled by bootstrap.ts):
 *   1. bootstrap.ts reads bundle-manifest.json, compares version
 *   2. If newer, sets ATROPHY_HOT_BOOT=1 and require()s hot app.js
 *   3. app.ts calls getHotBundlePaths() for preload/renderer paths
 *   4. If hot app.js throws, bootstrap falls back to frozen app.js
 *
 * Background check (called AFTER app is ready):
 *   1. checkForBundleUpdate() - queries GitHub for newer bundle
 *   2. If found, downloads + extracts to ~/.atrophy/bundle/
 *   3. Next boot picks it up automatically
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { app } from 'electron';
import { createLogger } from './logger';

const log = createLogger('bundle-updater');

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const USER_DATA = process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy');
const BUNDLE_DIR = path.join(USER_DATA, 'bundle');
const MANIFEST_PATH = path.join(BUNDLE_DIR, 'bundle-manifest.json');
const HOT_OUT_DIR = path.join(BUNDLE_DIR, 'out');
const STAGING_DIR = path.join(BUNDLE_DIR, '_staging');

// GitHub release settings
const GH_OWNER = 'wlilley93';
const GH_REPO = 'Atrophy';
const BUNDLE_ASSET_NAME = 'bundle.tar.gz';
const MANIFEST_ASSET_NAME = 'bundle-manifest.json';

// ---------------------------------------------------------------------------
// Manifest
// ---------------------------------------------------------------------------

interface BundleManifest {
  version: string;
  sha256: string;
  timestamp: string;
  tag?: string;
}

function readLocalManifest(): BundleManifest | null {
  try {
    if (!fs.existsSync(MANIFEST_PATH)) return null;
    return JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Boot-time: check if a hot bundle exists and return override paths
// ---------------------------------------------------------------------------

export interface HotBundlePaths {
  main: string;       // path to out/main/app.js (bootstrap stays frozen)
  preload: string;    // path to out/preload/index.js
  renderer: string;   // path to out/renderer/index.html
  version: string;    // hot bundle version string
}

/**
 * Check if a valid hot bundle exists at ~/.atrophy/bundle/out/.
 * Returns override paths if valid, null if app should use frozen bundle.
 *
 * Called synchronously at boot BEFORE app.whenReady().
 */
export function getHotBundlePaths(): HotBundlePaths | null {
  // Skip in dev mode
  if (process.env.ELECTRON_RENDERER_URL) return null;

  // Skip if not packaged (dev build)
  if (!app.isPackaged) return null;

  const manifest = readLocalManifest();
  if (!manifest) return null;

  // Validate the hot bundle directory has the expected structure
  // Main process code is in app.js (bootstrap.ts stays frozen in the asar)
  const mainPath = path.join(HOT_OUT_DIR, 'main', 'app.js');
  const preloadPath = path.join(HOT_OUT_DIR, 'preload', 'index.js');
  const rendererPath = path.join(HOT_OUT_DIR, 'renderer', 'index.html');

  if (!fs.existsSync(mainPath) || !fs.existsSync(preloadPath) || !fs.existsSync(rendererPath)) {
    log.warn('hot bundle directory incomplete, falling back to frozen bundle');
    return null;
  }

  // Compare versions: only use hot bundle if it's newer than the frozen one
  const frozenVersion = app.getVersion();
  if (!isNewer(manifest.version, frozenVersion)) {
    log.debug(`hot bundle ${manifest.version} is not newer than frozen ${frozenVersion}`);
    return null;
  }

  log.info(`using hot bundle v${manifest.version} (frozen: v${frozenVersion})`);

  return {
    main: mainPath,
    preload: preloadPath,
    renderer: rendererPath,
    version: manifest.version,
  };
}

/**
 * Simple semver comparison: is `a` newer than `b`?
 * Handles x.y.z format. Returns true if a > b.
 */
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
// Background: check GitHub for newer bundle and download
// ---------------------------------------------------------------------------

interface GitHubAsset {
  name: string;
  browser_download_url: string;
  size: number;
}

interface GitHubRelease {
  tag_name: string;
  assets: GitHubAsset[];
  prerelease: boolean;
  draft: boolean;
}

/**
 * Check GitHub Releases for a newer bundle and download it.
 * Runs in the background after app is ready. Non-blocking, non-fatal.
 *
 * @param onProgress Optional callback for download progress (0-100)
 * @returns The new version string if updated, null if already current
 */
export async function checkForBundleUpdate(
  onProgress?: (percent: number) => void,
): Promise<string | null> {
  // Skip in dev
  if (process.env.ELECTRON_RENDERER_URL || !app.isPackaged) return null;

  try {
    // Fetch latest releases from GitHub
    const release = await fetchLatestBundleRelease();
    if (!release) {
      log.debug('no bundle release found on GitHub');
      return null;
    }

    // Find the manifest asset
    const manifestAsset = release.assets.find((a) => a.name === MANIFEST_ASSET_NAME);
    const bundleAsset = release.assets.find((a) => a.name === BUNDLE_ASSET_NAME);

    if (!manifestAsset || !bundleAsset) {
      log.debug(`release ${release.tag_name} missing bundle assets`);
      return null;
    }

    // Download and parse remote manifest
    const remoteManifest = await fetchJson<BundleManifest>(manifestAsset.browser_download_url);
    if (!remoteManifest?.version) {
      log.warn('invalid remote bundle manifest');
      return null;
    }

    // Compare against both frozen version and existing hot bundle
    const frozenVersion = app.getVersion();
    const localManifest = readLocalManifest();
    const currentVersion = localManifest?.version || frozenVersion;

    if (!isNewer(remoteManifest.version, currentVersion)) {
      log.debug(`remote ${remoteManifest.version} is not newer than current ${currentVersion}`);
      return null;
    }

    log.info(`new bundle available: v${remoteManifest.version} (current: v${currentVersion})`);

    // Download bundle tarball to staging
    fs.mkdirSync(STAGING_DIR, { recursive: true });
    const tarPath = path.join(STAGING_DIR, BUNDLE_ASSET_NAME);

    await downloadFile(bundleAsset.browser_download_url, tarPath, bundleAsset.size, onProgress);

    // Verify SHA-256 if provided
    if (remoteManifest.sha256) {
      const hash = await hashFile(tarPath);
      if (hash !== remoteManifest.sha256) {
        log.error(`SHA-256 mismatch: expected ${remoteManifest.sha256}, got ${hash}`);
        cleanupStaging();
        return null;
      }
      log.debug('SHA-256 verified');
    }

    // Extract tarball to staging/out/
    const stagingOut = path.join(STAGING_DIR, 'out');
    fs.mkdirSync(stagingOut, { recursive: true });
    await extractTarGz(tarPath, stagingOut);

    // Validate extracted bundle has expected structure
    // Main process app code is app.js (bootstrap index.js stays frozen in asar)
    if (
      !fs.existsSync(path.join(stagingOut, 'main', 'app.js')) ||
      !fs.existsSync(path.join(stagingOut, 'preload', 'index.js')) ||
      !fs.existsSync(path.join(stagingOut, 'renderer', 'index.html'))
    ) {
      log.error('extracted bundle missing required files');
      cleanupStaging();
      return null;
    }

    // Atomic swap: move staging -> live
    // Remove old hot bundle
    if (fs.existsSync(HOT_OUT_DIR)) {
      fs.rmSync(HOT_OUT_DIR, { recursive: true, force: true });
    }

    // Move staging/out to bundle/out
    fs.renameSync(stagingOut, HOT_OUT_DIR);

    // Write manifest
    fs.writeFileSync(MANIFEST_PATH, JSON.stringify(remoteManifest, null, 2));

    // Cleanup staging
    cleanupStaging();

    log.info(`bundle v${remoteManifest.version} ready for next boot`);
    return remoteManifest.version;
  } catch (e) {
    log.error(`bundle update check failed: ${e}`);
    cleanupStaging();
    return null;
  }
}

/**
 * Get the currently active bundle version (hot or frozen).
 */
export function getActiveBundleVersion(): string {
  const manifest = readLocalManifest();
  const frozenVersion = app.getVersion();

  // If hot bundle is active (would be selected on boot), return its version
  const hotPaths = getHotBundlePaths();
  if (hotPaths) return hotPaths.version;

  return frozenVersion;
}

/**
 * Get info about pending bundle update (downloaded but not yet active).
 */
export function getPendingBundleInfo(): { version: string; pendingRestart: boolean } | null {
  const manifest = readLocalManifest();
  if (!manifest) return null;

  const frozenVersion = app.getVersion();
  const hotPaths = getHotBundlePaths();

  // If hot bundle exists but isn't active yet (e.g. first download, app still running)
  if (manifest && isNewer(manifest.version, frozenVersion) && !hotPaths) {
    return { version: manifest.version, pendingRestart: true };
  }

  // If hot bundle version is newer than what's currently running
  // (downloaded during this session)
  if (manifest && isNewer(manifest.version, getActiveBundleVersion())) {
    return { version: manifest.version, pendingRestart: true };
  }

  return null;
}

/**
 * Clear the hot bundle, reverting to the frozen app bundle on next boot.
 */
export function clearHotBundle(): void {
  try {
    if (fs.existsSync(BUNDLE_DIR)) {
      fs.rmSync(BUNDLE_DIR, { recursive: true, force: true });
      log.info('hot bundle cleared');
    }
  } catch (e) {
    log.error(`failed to clear hot bundle: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, {
      headers: { 'Accept': 'application/json', 'User-Agent': 'Atrophy-Updater' },
    });
    if (!res.ok) return null;
    return await res.json() as T;
  } catch {
    return null;
  }
}

async function fetchLatestBundleRelease(): Promise<GitHubRelease | null> {
  // Check all recent releases for one with bundle assets
  const releases = await fetchJson<GitHubRelease[]>(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/releases?per_page=10`,
  );
  if (!releases) return null;

  for (const release of releases) {
    if (release.draft || release.prerelease) continue;
    const hasBundleAssets = release.assets.some((a) => a.name === BUNDLE_ASSET_NAME) &&
                            release.assets.some((a) => a.name === MANIFEST_ASSET_NAME);
    if (hasBundleAssets) return release;
  }

  return null;
}

async function downloadFile(
  url: string,
  destPath: string,
  totalSize: number,
  onProgress?: (percent: number) => void,
): Promise<void> {
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Atrophy-Updater' },
  });
  if (!res.ok || !res.body) {
    throw new Error(`download failed: ${res.status} ${res.statusText}`);
  }

  const fd = fs.openSync(destPath, 'w');
  let downloaded = 0;

  try {
    const reader = res.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      fs.writeSync(fd, value);
      downloaded += value.length;
      if (onProgress && totalSize > 0) {
        onProgress(Math.min(100, Math.round((downloaded / totalSize) * 100)));
      }
    }
  } finally {
    fs.closeSync(fd);
  }
}

// ---------------------------------------------------------------------------
// File helpers
// ---------------------------------------------------------------------------

async function hashFile(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

async function extractTarGz(tarPath: string, destDir: string): Promise<void> {
  // Use system tar (available on macOS and Linux)
  const { execFile } = await import('child_process');
  const { promisify } = await import('util');
  const execFileAsync = promisify(execFile);

  await execFileAsync('tar', ['xzf', tarPath, '-C', destDir], {
    timeout: 60_000,
  });
}

function cleanupStaging(): void {
  try {
    if (fs.existsSync(STAGING_DIR)) {
      fs.rmSync(STAGING_DIR, { recursive: true, force: true });
    }
  } catch { /* best effort */ }
}

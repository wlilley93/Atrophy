# src/main/bundle-updater.ts - Hot Bundle Updater

**Dependencies:** `fs`, `path`, `os`, `crypto`, `electron`, `./logger`  
**Purpose:** Download pre-built bundles from GitHub Releases for over-the-air updates

## Overview

Instead of rebuilding and distributing a new DMG for every change, this module downloads pre-built `out/` bundles from GitHub Releases to `~/.atrophy/bundle/`. On the next boot, the app loads from the hot bundle instead of the frozen one inside the .app.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Bundle Update Flow                            │
│                                                                   │
│  bootstrap.ts (frozen in asar) - Entry point                    │
│       │                                                           │
│       ▼                                                           │
│  Check ~/.atrophy/bundle/bundle-manifest.json                    │
│       │                                                           │
│       ├── If newer version exists                                │
│       │   └──▶ Load hot bundle (ATROPHY_HOT_BOOT=1)             │
│       │                                                           │
│       └── If no hot bundle or same version                       │
│           └──▶ Load frozen bundle from asar                       │
│                                                                   │
│  After app ready:                                                │
│  checkForBundleUpdate() - Background check for newer bundle      │
│       │                                                           │
│       ├── If newer found                                         │
│       │   ├── Download bundle.tar.gz                             │
│       │   ├── Verify SHA-256                                     │
│       │   ├── Extract to staging                                 │
│       │   ├── Swap with atomic rename                            │
│       │   └──▶ Next boot uses new bundle                         │
│       │                                                           │
│       └── If current or error                                    │
│           └──▶ Continue with current bundle                       │
└─────────────────────────────────────────────────────────────────┘
```

## Paths

```typescript
const USER_DATA = process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy');
const BUNDLE_DIR = path.join(USER_DATA, 'bundle');
const MANIFEST_PATH = path.join(BUNDLE_DIR, 'bundle-manifest.json');
const HOT_OUT_DIR = path.join(BUNDLE_DIR, 'out');
const STAGING_DIR = path.join(BUNDLE_DIR, '_staging');

const GH_OWNER = 'wlilley93';
const GH_REPO = 'Atrophy';
const BUNDLE_ASSET_NAME = 'bundle.tar.gz';
const MANIFEST_ASSET_NAME = 'bundle-manifest.json';
```

## Bundle Manifest

```typescript
interface BundleManifest {
  version: string;
  sha256: string;
  timestamp: string;
  tag?: string;
}
```

**Fields:**
- `version`: Semver version (e.g., `1.2.7`)
- `sha256`: SHA-256 hash of bundle.tar.gz for integrity verification
- `timestamp`: ISO 8601 timestamp of build
- `tag`: GitHub release tag (optional)

## getHotBundlePaths

```typescript
export interface HotBundlePaths {
  main: string;       // path to out/main/app.js
  preload: string;    // path to out/preload/index.js
  renderer: string;   // path to out/renderer/index.html
  version: string;    // hot bundle version string
}

export function getHotBundlePaths(): HotBundlePaths | null {
  // Skip in dev mode
  if (process.env.ELECTRON_RENDERER_URL) return null;
  if (!app.isPackaged) return null;

  const manifest = readLocalManifest();
  if (!manifest) return null;

  // Validate hot bundle directory structure
  const mainPath = path.join(HOT_OUT_DIR, 'main', 'app.js');
  const preloadPath = path.join(HOT_OUT_DIR, 'preload', 'index.js');
  const rendererPath = path.join(HOT_OUT_DIR, 'renderer', 'index.html');

  if (!fs.existsSync(mainPath) || !fs.existsSync(preloadPath) || 
      !fs.existsSync(rendererPath)) {
    log.warn('hot bundle directory incomplete, falling back to frozen bundle');
    return null;
  }

  // Compare versions: only use hot bundle if newer than frozen
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
```

**Validation:**
1. Check manifest exists
2. Verify directory structure (main/app.js, preload/index.js, renderer/index.html)
3. Compare versions - only use hot bundle if newer than frozen

**Note:** Main process code is in `app.js` - `index.js` stays frozen in asar as bootstrap.

## Semver Comparison

```typescript
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
```

**Purpose:** Compare semver strings (e.g., `1.2.7` vs `1.2.6`)

## checkForBundleUpdate

```typescript
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

    // Find bundle and manifest assets
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
    if (
      !fs.existsSync(path.join(stagingOut, 'main', 'app.js')) ||
      !fs.existsSync(path.join(stagingOut, 'preload', 'index.js')) ||
      !fs.existsSync(path.join(stagingOut, 'renderer', 'index.html'))
    ) {
      log.error('extracted bundle missing required files');
      cleanupStaging();
      return null;
    }

    // Two-step rename swap: keeps old bundle available if crash occurs mid-swap
    const backupDir = path.join(BUNDLE_DIR, '_old');

    // Step 1: Move old live bundle to _old backup
    if (fs.existsSync(backupDir)) {
      fs.rmSync(backupDir, { recursive: true, force: true });
    }
    if (fs.existsSync(HOT_OUT_DIR)) {
      fs.renameSync(HOT_OUT_DIR, backupDir);
    }

    // Step 2: Move staging/out to bundle/out
    fs.renameSync(stagingOut, HOT_OUT_DIR);

    // Step 3: Write manifest
    fs.writeFileSync(MANIFEST_PATH, JSON.stringify(remoteManifest, null, 2));

    // Step 4: Remove the _old backup now that swap is complete
    if (fs.existsSync(backupDir)) {
      fs.rmSync(backupDir, { recursive: true, force: true });
    }

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
```

**Flow:**
1. Fetch latest release from GitHub
2. Find bundle.tar.gz and bundle-manifest.json assets
3. Download and verify manifest
4. Compare versions (check against both frozen and hot bundle)
5. Download bundle tarball
6. Verify SHA-256 hash
7. Extract to staging
8. Validate structure
9. Atomic swap (old → _old, staging → out)
10. Write new manifest
11. Clean up

**Atomic swap:** Two-step rename ensures old bundle is available if crash occurs mid-swap.

## getActiveBundleVersion

```typescript
export function getActiveBundleVersion(): string {
  const frozenVersion = app.getVersion();

  // If hot bundle is active (would be selected on boot), return its version
  const hotPaths = getHotBundlePaths();
  if (hotPaths) return hotPaths.version;

  return frozenVersion;
}
```

**Purpose:** Get currently active bundle version (hot or frozen)

## getPendingBundleInfo

```typescript
export function getPendingBundleInfo(): { version: string; downloadedAt: string } | null {
  const manifest = readLocalManifest();
  if (!manifest) return null;

  const frozenVersion = app.getVersion();
  const hotPaths = getHotBundlePaths();

  // If hot bundle exists and is different from what would be selected on boot
  if (hotPaths && hotPaths.version !== frozenVersion) {
    return {
      version: manifest.version,
      downloadedAt: manifest.timestamp,
    };
  }

  return null;
}
```

**Purpose:** Get info about downloaded but not-yet-active bundle

## clearHotBundle

```typescript
export function clearHotBundle(): void {
  if (fs.existsSync(HOT_OUT_DIR)) {
    fs.rmSync(HOT_OUT_DIR, { recursive: true, force: true });
  }
  if (fs.existsSync(MANIFEST_PATH)) {
    fs.unlinkSync(MANIFEST_PATH);
  }
  log.info('hot bundle cleared - will use frozen bundle on next boot');
}
```

**Purpose:** Clear hot bundle and revert to frozen version

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/bundle/bundle-manifest.json` | getHotBundlePaths, checkForBundleUpdate |
| Write | `~/.atrophy/bundle/bundle-manifest.json` | checkForBundleUpdate (after download) |
| Read/Write | `~/.atrophy/bundle/out/` | Hot bundle directory |
| Read/Write | `~/.atrophy/bundle/_staging/` | Download/extraction staging |
| Read/Write | `~/.atrophy/bundle/_old/` | Backup during swap |

## Exported API

| Function | Purpose |
|----------|---------|
| `getHotBundlePaths()` | Get hot bundle paths if valid |
| `checkForBundleUpdate(onProgress)` | Check GitHub for newer bundle |
| `getActiveBundleVersion()` | Get currently active version |
| `getPendingBundleInfo()` | Get pending update info |
| `clearHotBundle()` | Clear hot bundle, revert to frozen |

## See Also

- `src/main/bootstrap.ts` - Uses getHotBundlePaths() at boot
- `src/main/updater.ts` - DMG auto-updater (electron-updater)
- `src/main/ipc/system.ts` - bundle:* IPC handlers

# src/main/bootstrap.ts - Hot Bundle Loader

**Line count:** ~130 lines  
**Dependencies:** Node.js built-ins only (`electron`, `path`, `fs`, `os`, `url`)  
**Purpose:** Production entry point that detects and loads hot bundles from `~/.atrophy/bundle/`

## Overview

`bootstrap.ts` is the actual entry point for the packaged Electron application. Its sole responsibility is to detect whether a hot bundle exists and load it, falling back to the frozen (bundled) app if not. This enables over-the-air updates without requiring a full DMG reinstall - code changes can ship via GitHub Releases as `bundle.tar.gz` and load on the next restart.

The design prioritizes reliability: any error loading a hot bundle results in immediate fallback to the frozen app, ensuring the app always starts.

## Key Concepts

### Hot Bundle vs Frozen App

| Term | Location | Update Mechanism |
|------|----------|------------------|
| **Frozen app** | `<App Bundle>/Contents/Resources/out/main/app.js` | DMG release (manual install) |
| **Hot bundle** | `~/.atrophy/bundle/out/main/app.js` | Auto-downloaded from GitHub Releases |

The frozen app is the version shipped with the DMG installer. The hot bundle is a newer version downloaded automatically by `bundle-updater.ts`. Bootstrap decides which to load at runtime.

### Boot Sentinel (Crash Detection)

A sentinel file at `~/.atrophy/bundle/.booting` tracks whether the last hot boot completed successfully. The sentinel is written before loading the hot bundle and deleted after 10 seconds of successful execution. If the sentinel exists at startup, the previous hot boot crashed and the frozen app is used instead.

## Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     bootstrap.ts starts                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────────┐
              │  Dev mode? (ELECTRON_RENDERER) │
              └───────────────────────────────┘
                       │              │
                      Yes            No
                       │              │
                       ▼              ▼
              ┌────────────────┐  ┌─────────────────────────┐
              │ Load frozen    │  │ ATROPHY_SKIP_HOT_BUNDLE?│
              │ app.js         │  └─────────────────────────┘
              └────────────────┘           │        │
                                          Yes      No
                                           │        │
                                           ▼        ▼
                                   ┌──────────────────────────┐
                                   │ .booting exists? (crash) │
                                   └──────────────────────────┘
                                           │        │
                                          Yes      No
                                           │        │
                                           ▼        ▼
                                   ┌────────────┐  ┌──────────────┐
                                   │ Use frozen │  │ manifest >   │
                                   │ app        │  │ app version? │
                                   └────────────┘  └──────────────┘
                                                           │     │
                                                          Yes   No
                                                           │     │
                                                           ▼     ▼
                                                   ┌──────────┐ ┌──────────┐
                                                   │ Use hot  │ │ Use      │
                                                   │ bundle   │ │ frozen   │
                                                   └──────────┘ └──────────┘
```

## Constants and Paths

```typescript
const USER_DATA = process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy');
const BUNDLE_DIR = path.join(USER_DATA, 'bundle');
const MANIFEST_PATH = path.join(BUNDLE_DIR, 'bundle-manifest.json');
const HOT_APP = path.join(BUNDLE_DIR, 'out', 'main', 'app.js');
const FROZEN_APP = path.join(__dirname, 'app.js');
const BOOT_SENTINEL = path.join(BUNDLE_DIR, '.booting');
```

| Constant | Purpose |
|----------|---------|
| `USER_DATA` | Root directory for user data (`~/.atrophy/`), overridable via `ATROPHY_DATA` env var |
| `BUNDLE_DIR` | Hot bundle directory at `~/.atrophy/bundle/` |
| `MANIFEST_PATH` | JSON manifest containing version, SHA-256, timestamp of hot bundle |
| `HOT_APP` | Main process entry point in hot bundle |
| `FROZEN_APP` | Main process entry point in frozen (bundled) app |
| `BOOT_SENTINEL` | Crash detection sentinel file (contains PID of booting process) |

## Functions

### `isNewer(a: string, b: string): boolean`

Compares two semver strings (e.g., `"1.2.7"` vs `"1.2.6"`). Returns `true` if `a` is greater than `b`.

**Implementation:**
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

**Why inlined:** Bootstrap must not import from `app.ts` or other app modules (circular dependency risk). Semver comparison is duplicated here to keep bootstrap self-contained.

### `boot(): Promise<void>`

The main boot function. Executes the decision tree for determining which app bundle to load.

#### Step 1: Dev Mode Check

```typescript
if (process.env.ELECTRON_RENDERER_URL || !app.isPackaged) {
  await import(pathToFileURL(FROZEN_APP).href);
  return;
}
```

In development mode (detected via `ELECTRON_RENDERER_URL` set by electron-vite dev server, or `app.isPackaged === false`), the frozen app is loaded directly. Hot bundles are a production-only feature.

#### Step 2: Force Skip (Debug Escape Hatch)

```typescript
if (process.env.ATROPHY_SKIP_HOT_BUNDLE === '1') {
  console.log('[bootstrap] ATROPHY_SKIP_HOT_BUNDLE=1, using frozen app');
  await import(pathToFileURL(FROZEN_APP).href);
  return;
}
```

Allows developers or users to force-skip the hot bundle for debugging. Set the environment variable before launching:

```bash
ATROPHY_SKIP_HOT_BUNDLE=1 /Applications/Atrophy.app/Contents/MacOS/Atrophy
```

#### Step 3: Crash Detection (Boot Sentinel)

```typescript
if (fs.existsSync(BOOT_SENTINEL)) {
  // Check if the PID in the sentinel is still alive
  let stale = true;
  try {
    const pid = parseInt(fs.readFileSync(BOOT_SENTINEL, 'utf-8').trim(), 10);
    if (pid && pid !== process.pid) {
      try { process.kill(pid, 0); stale = false; } catch { /* process dead */ }
    }
  } catch { /* unreadable sentinel */ }

  if (stale) {
    console.warn('[bootstrap] previous hot boot crashed, skipping hot bundle');
    try { fs.unlinkSync(BOOT_SENTINEL); } catch { /* ignore */ }
    // Fall through to frozen
  }
}
```

**How it works:**

1. Before loading a hot bundle, bootstrap writes the current PID to `.booting`
2. After 10 seconds of successful execution, `app.ts` deletes the sentinel
3. If the app crashes within those 10 seconds, the sentinel remains
4. On next launch, bootstrap detects the sentinel and checks if the PID is still alive
5. If the process is dead, the sentinel is stale (last boot crashed) → use frozen app
6. If the process is alive (race condition), proceed with hot bundle check

**PID race condition handling:** The sentinel might exist from a previous run that completed successfully but didn't delete the sentinel in time. By checking `process.kill(pid, 0)`, we verify if the original process is still running. If it's dead, the sentinel is definitely stale. If it's alive, another instance is booting (shouldn't happen due to single-instance lock, but handled gracefully).

#### Step 4: Version Check

```typescript
else if (fs.existsSync(MANIFEST_PATH) && fs.existsSync(HOT_APP)) {
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf-8'));
  if (manifest?.version && isNewer(manifest.version, app.getVersion())) {
    useHot = true;
  }
}
```

Checks:
1. Manifest file exists (written by `bundle-updater.ts` when download completes)
2. Hot app entry point exists
3. Hot bundle version is newer than the frozen app version

All three conditions must be true to use the hot bundle.

#### Step 5: Load Hot Bundle

```typescript
if (useHot) {
  // Write boot sentinel with PID
  try {
    fs.mkdirSync(BUNDLE_DIR, { recursive: true });
    fs.writeFileSync(BOOT_SENTINEL, String(process.pid));
  } catch { /* non-fatal */ }

  // Tell app code it's running from hot bundle
  process.env.ATROPHY_HOT_BOOT = '1';

  try {
    console.log(`[bootstrap] loading hot bundle from ${HOT_APP}`);
    await import(pathToFileURL(HOT_APP).href);

    // Clear sentinel after 10 seconds
    setTimeout(() => {
      try { fs.unlinkSync(BOOT_SENTINEL); } catch { /* already gone */ }
    }, 10_000).unref();

    return;
  } catch (err) {
    console.error('[bootstrap] hot bundle failed, falling back to frozen:', err);
    try { fs.unlinkSync(MANIFEST_PATH); } catch { /* ignore */ }
    try { fs.unlinkSync(BOOT_SENTINEL); } catch { /* ignore */ }
  }
}
```

**Key actions:**

1. **Write sentinel:** Records PID for crash detection
2. **Set `ATROPHY_HOT_BOOT=1`:** Signals to `app.ts` that it's running from a hot bundle (affects resource path resolution)
3. **Dynamic import:** Uses `pathToFileURL` because ES modules require file:// URLs for absolute paths
4. **Clear sentinel:** After 10 seconds, deletes the sentinel (boot succeeded)
5. **Error handling:** On failure, removes both manifest and sentinel to prevent retry loops

**Why `.unref()`:** The timeout is unref'd so it doesn't keep the process alive if the app quits. It's a fire-and-forget cleanup.

#### Step 6: Fallback to Frozen App

```typescript
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
```

If the frozen app fails to load, a dialog is shown and the app exits with code 1. This is a true fatal error - there's nothing left to fall back to.

## Environment Variables

| Variable | Purpose | Set By |
|----------|---------|--------|
| `ATROPHY_HOT_BOOT` | Signals hot bundle execution | bootstrap.ts |
| `ATROPHY_SKIP_HOT_BUNDLE` | Force-skip hot bundle (debug) | User/dev |
| `ATROPHY_DATA` | Override `~/.atrophy/` path | User/dev |
| `ELECTRON_RENDERER_URL` | Dev mode detection | electron-vite dev server |

## Error Handling Philosophy

Bootstrap follows a **fail-soft, always-start** philosophy:

1. **Any hot bundle error → frozen fallback:** Corrupt manifest, missing files, import errors - all result in using the frozen app
2. **Frozen app error → fatal dialog:** No fallback exists, so show user-facing error and exit
3. **Silent cleanup:** Errors deleting sentinel/manifest are ignored (non-fatal)
4. **Best-effort logging:** Console logs for debugging, but no crash if logging fails

This ensures the app always starts unless the frozen bundle itself is corrupted (which requires a reinstall).

## File I/O Summary

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/bundle/.booting` | Startup (crash check) |
| Write | `~/.atrophy/bundle/.booting` | Before hot bundle load |
| Delete | `~/.atrophy/bundle/.booting` | After 10s successful boot |
| Read | `~/.atrophy/bundle/bundle-manifest.json` | Version check |
| Delete | `~/.atrophy/bundle/bundle-manifest.json` | Hot bundle load failure |
| Read | `~/.atrophy/bundle/out/main/app.js` | Hot bundle execution |
| Read | `<bundle>/Resources/out/main/app.js` | Frozen app execution |

## Security Considerations

### 1. No Code Signature Verification

Bootstrap does not verify the hot bundle's code signature. Security relies on:
- GitHub Releases authentication (HTTPS, GitHub's auth)
- The fact that `bundle-updater.ts` downloads from the official repo

**Risk:** If GitHub credentials are compromised, malicious bundles could be served.

**Mitigation:** Future versions could add SHA-256 verification against a known-good hash in the frozen app.

### 2. Path Traversal

The manifest could theoretically contain path traversal attacks (e.g., `"../../../etc/passwd"`). Bootstrap mitigates this by:
- Using `path.join()` which normalizes paths
- Only reading from `~/.atrophy/bundle/` subdirectories
- Never executing arbitrary paths from user input

### 3. PID Spoofing

The sentinel PID check uses `process.kill(pid, 0)` which doesn't require special permissions. However, a malicious process could theoretically reuse a PID.

**Risk:** Low - PID reuse within 10 seconds is extremely unlikely on modern systems.

## Relationship to Other Files

| File | Relationship |
|------|--------------|
| `src/main/index.ts` | Dev mode entry point (not used in production) |
| `src/main/app.ts` | Actual app code, loaded by bootstrap |
| `src/main/bundle-updater.ts` | Downloads hot bundles and writes manifest |
| `electron-builder.yml` | Configures what goes into the frozen bundle |

## Testing Scenarios

### Normal Hot Boot
1. Hot bundle exists, version > frozen version
2. No `.booting` sentinel
3. Result: Hot bundle loads, sentinel cleared after 10s

### Crash Recovery
1. Hot bundle loads, app crashes within 10s
2. Sentinel remains on disk
3. Next boot: sentinel detected, frozen app used

### Manifest Corruption
1. `bundle-manifest.json` contains invalid JSON
2. Result: Caught in try/catch, frozen app used

### Hot Bundle Delete
1. Hot bundle files deleted manually
2. Manifest still exists
3. Result: `fs.existsSync(HOT_APP)` fails, frozen app used

## See Also

- `src/main/bundle-updater.ts` - Downloads and verifies hot bundles
- `src/main/index.ts` - Development entry point
- `.github/workflows/bundle.yml` - CI workflow that creates hot bundle releases

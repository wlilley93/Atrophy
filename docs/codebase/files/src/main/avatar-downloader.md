# src/main/avatar-downloader.ts - Avatar Asset Downloader

**Dependencies:** `fs`, `path`, `child_process`, `electron`, `./config`, `./logger`  
**Purpose:** Download avatar assets from GitHub Releases on first launch

## Overview

This module downloads avatar assets (loop videos, images) from GitHub Releases and extracts them to `~/.atrophy/agents/<name>/avatar/`. It supports per-agent asset URLs via `agent.json` `avatar_asset_url` field, with a fallback to the default Xan asset URL.

## Constants

```typescript
const DEFAULT_AVATAR_URL =
  'https://github.com/wlilley93/Atrophy/releases/download/avatar-assets-v1/xan-avatar-v1.tar.gz';
const AMBIENT_VIDEO_URL =
  'https://github.com/wlilley93/Atrophy/releases/download/avatar-assets-v1/xan_ambient.mp4';
const MARKER = '.avatar-complete';
const AMBIENT_MARKER = '.ambient-complete';
```

**Purpose:** Default asset URLs and completion markers

## isAvatarComplete

```typescript
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
```

**Purpose:** Check if avatar assets are already present

**Validation:**
1. Check for `.avatar-complete` marker file
2. Or check if loops dir has at least one `.mp4` file

## resolveAssetUrl

```typescript
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
```

**Resolution order:**
1. Check user data `agent.json` for `avatar_asset_url`
2. Check bundle `agent.json` for `avatar_asset_url`
3. Fall back to default URL for xan agent
4. Return null if no URL found (no download)

## ensureAvatarAssets

```typescript
export async function ensureAvatarAssets(
  agentName: string,
  win: BrowserWindow | null,
): Promise<void> {
  if (isAvatarComplete(agentName)) return;

  const assetUrl = resolveAssetUrl(agentName);
  if (!assetUrl) {
    // No asset URL configured - signal completion
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

    // Attach error listener to catch disk-full / write errors
    let writeError: Error | null = null;
    fileStream.on('error', (err) => { writeError = err; });

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (writeError) throw writeError;
      fileStream.write(value);
      transferred += value.byteLength;

      const now = Date.now();
      if (total > 0 && now - lastEmit > 500) {
        const percent = Math.round((transferred / total) * 100);
        win?.webContents.send('avatar:download-progress', { percent, transferred, total });
        lastEmit = now;
      }
    }

    if (writeError) throw writeError;

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
```

**Flow:**
1. Check if already complete
2. Resolve asset URL
3. Create agent directory
4. Download tarball with progress tracking
5. Extract to agent directory
6. Write completion marker
7. Cleanup tar file

**Progress events (every 500ms):**
- `avatar:download-start` - Download started
- `avatar:download-progress` - `{ percent, transferred, total }`
- `avatar:download-complete` - Download complete
- `avatar:download-error` - Error message string

**Error handling:**
- Write errors caught via stream error listener
- Partial tar cleaned up on failure
- Non-fatal - errors logged but don't crash app

## Ambient Video Download

### getAmbientVideoPath

```typescript
export function getAmbientVideoPath(): string {
  return path.join(USER_DATA, 'assets', 'xan_ambient.mp4');
}
```

**Purpose:** Get path to ambient video file

### isAmbientVideoReady

```typescript
export function isAmbientVideoReady(): boolean {
  const assetsDir = path.join(USER_DATA, 'assets');
  return fs.existsSync(path.join(assetsDir, AMBIENT_MARKER));
}
```

**Purpose:** Check if ambient video is already downloaded

### ensureAmbientVideo

```typescript
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
```

**Purpose:** Download ambient video if not already present

**Reuses same progress events as avatar download**

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/data/agent.json` | resolveAssetUrl |
| Read | `~/.atrophy/agents/<name>/avatar/.avatar-complete` | isAvatarComplete |
| Write | `~/.atrophy/agents/<name>/<name>-avatar.tar.gz` | Download (temp) |
| Write | `~/.atrophy/agents/<name>/avatar/` | Extract |
| Write | `~/.atrophy/agents/<name>/avatar/.avatar-complete` | Completion marker |
| Read/Write | `~/.atrophy/assets/xan_ambient.mp4` | Ambient video |
| Read/Write | `~/.atrophy/assets/.ambient-complete` | Ambient marker |

## Exported API

| Function | Purpose |
|----------|---------|
| `isAvatarComplete(agentName)` | Check if avatar assets present |
| `ensureAvatarAssets(agentName, win)` | Download and extract avatar |
| `getAmbientVideoPath()` | Get ambient video path |
| `isAmbientVideoReady()` | Check if ambient video present |
| `ensureAmbientVideo(win)` | Download ambient video |

## See Also

- `src/main/ipc/window.ts` - Calls ensureAvatarAssets from mirror setup
- `src/main/create-agent.ts` - Creates avatar directory structure
- `src/renderer/components/OrbAvatar.svelte` - Uses ambient video

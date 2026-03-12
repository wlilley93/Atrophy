# Windows .exe Build Assessment

## Overview

The app is built on Electron (inherently cross-platform), but the implementation is **deeply macOS-specific**. Overall difficulty: **Moderate-to-Hard**.

---

## Easy parts (just config)

- **electron-builder.yml**: Add a `win:` section targeting NSIS installer or portable `.exe` — ~10 lines of YAML
- **Icon**: Convert the `.icns` to `.ico`
- **Auto-update**: `electron-updater` already supports Windows via GitHub Releases
- **Login item**: `app.setLoginItemSettings()` works cross-platform already

## Medium effort (platform branching)

- **Window creation**: macOS-specific props like `vibrancy: 'ultra-dark'`, `titleBarStyle: 'hiddenInset'`, `trafficLightPosition` need `process.platform` guards and Windows alternatives
- **Python path detection**: Currently looks for `/opt/homebrew/bin/python3` etc. — needs `python.exe`, `C:\Python*\` paths
- **better-sqlite3**: Native addon — needs Windows build toolchain (VS Build Tools) or prebuilt binaries. Standard Electron problem, well-documented
- **Whisper binary**: Need a Windows-compiled `whisper-cli.exe`

## Hard parts (real rewrites)

These modules use macOS-only shell commands with no Windows fallback:

| Module | macOS dependency | Windows replacement needed |
|--------|-----------------|---------------------------|
| `tts.ts` | `afplay` for playback, `say` as fallback | PowerShell `[System.Media.SoundPlayer]` or `node-speaker` |
| `notify.ts` | `osascript` (AppleScript) | Electron `Notification` API (actually simpler) |
| `status.ts` | `ioreg -c IOHIDSystem` for idle time | Win32 `GetLastInputInfo` via FFI or `child_process` |
| `cron.ts` | `launchd` plists + `launchctl` | Windows Task Scheduler (`schtasks.exe`) |
| `telegram-daemon.ts` | `launchctl` for daemon management | Windows Service or `schtasks` |

## Blockers

- **No CI/CD** exists yet — need a GitHub Actions workflow with a Windows matrix to build the `.exe`
- **Python scripts** (MCP servers, cron jobs) need Python installed on Windows, and path handling differs (`\` vs `/`)
- **No `.github/workflows/`** directory at all

## Effort Estimates

- **Minimal viable Windows build** (app launches, chat works, no voice/cron/notifications): A few focused sessions of work. Most of the core (inference, memory, config, UI) is platform-agnostic already.
- **Full feature parity**: Significantly more work due to TTS playback, idle detection, scheduled tasks, and whisper binary compilation for Windows.

## Implementation Path

### Phase 1: Build Config
1. Add `win:` section to `electron-builder.yml` (NSIS + portable targets)
2. Convert `.icns` icon to `.ico`
3. Add `process.platform` guards to window creation in `index.ts`
4. Add Windows Python path detection in `config.ts`

### Phase 2: Platform Abstraction
5. Abstract `notify.ts` to use Electron `Notification` API (cross-platform, actually simpler)
6. Abstract `status.ts` idle detection with platform branching
7. Abstract `tts.ts` audio playback (replace `afplay`)
8. Abstract `cron.ts` to support Windows Task Scheduler

### Phase 3: CI/CD
9. Create GitHub Actions workflow with macOS + Windows build matrix
10. Configure code signing for Windows (optional but recommended)
11. Test auto-update flow on Windows

### Phase 4: Native Dependencies
12. Ensure `better-sqlite3` builds on Windows CI (electron-rebuild + VS Build Tools)
13. Compile or source `whisper-cli.exe` for Windows
14. Bundle Python or document Python as a prerequisite

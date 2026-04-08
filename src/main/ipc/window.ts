/**
 * IPC handlers for window management, setup wizard, avatars, and artefacts.
 * Channels: window:*, setup:*, avatar:*, artefact:*
 */

import { ipcMain, shell } from 'electron';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';
import { execFileSync, spawn } from 'child_process';
import { getConfig, saveEnvVar, BUNDLE_ROOT, USER_DATA } from '../config';
import { streamInference, type InferenceEvent } from '../inference';
import { synthesise, playAudio, isMuted } from '../tts';
import { createAgent } from '../create-agent';
import { getAmbientVideoPath } from '../avatar-downloader';
import { createLogger } from '../logger';
import type { IpcContext } from '../ipc-handlers';

const log = createLogger('ipc:window');

export function registerWindowHandlers(ctx: IpcContext): void {
  ipcMain.handle('window:toggleFullscreen', () => {
    if (ctx.mainWindow) {
      ctx.mainWindow.setFullScreen(!ctx.mainWindow.isFullScreen());
    }
  });

  ipcMain.handle('window:toggleAlwaysOnTop', () => {
    if (ctx.mainWindow) {
      ctx.mainWindow.setAlwaysOnTop(!ctx.mainWindow.isAlwaysOnTop());
    }
  });

  ipcMain.handle('window:minimize', () => {
    if (ctx.mainWindow) ctx.mainWindow.minimize();
  });

  ipcMain.handle('window:close', () => {
    if (ctx.mainWindow) {
      if (ctx.isMenuBarMode) {
        ctx.mainWindow.hide();
      } else {
        ctx.mainWindow.close();
      }
    }
  });

  ipcMain.handle('window:getSize', () => {
    if (!ctx.mainWindow) return { width: 1660, height: 2213 };
    const [width, height] = ctx.mainWindow.getSize();
    return { width, height };
  });

  ipcMain.handle('window:setSize', (_e: Electron.IpcMainInvokeEvent, width: number, height: number, animate: boolean = true) => {
    if (!ctx.mainWindow) return;
    const bounds = ctx.mainWindow.getBounds();
    const cx = bounds.x + bounds.width / 2;
    const cy = bounds.y + bounds.height / 2;
    ctx.mainWindow.setBounds({
      x: Math.round(cx - width / 2),
      y: Math.round(cy - height / 2),
      width,
      height,
    }, animate);
  });

  // -- Setup wizard --

  ipcMain.handle('setup:check', () => {
    const cfgPath = path.join(USER_DATA, 'config.json');
    try {
      const userCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
      const needsSetup = !userCfg.setup_complete;
      if (!needsSetup) {
        // Setup already complete - clear any stale wizard session
        wizardSessionId = null;
      }
      return needsSetup;
    } catch {
      return true;
    }
  });

  // Claude CLI health check - verifies claude binary is reachable and working
  ipcMain.handle('setup:healthCheck', async () => {
    const config = getConfig();
    const bin = config.CLAUDE_BIN;
    const execEnv = { ...process.env, PATH: ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin'), process.env.PATH].join(':') };
    try {
      const result = execFileSync(bin, ['--version'], {
        timeout: 10_000,
        env: execEnv,
        stdio: ['pipe', 'pipe', 'pipe'],
      }).toString().trim();
      return { ok: true, version: result, bin };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      // Try common locations
      const candidates = [
        path.join(os.homedir(), '.local', 'bin', 'claude'),
        '/opt/homebrew/bin/claude',
        '/usr/local/bin/claude',
        path.join(os.homedir(), '.npm-global', 'bin', 'claude'),
      ];
      for (const candidate of candidates) {
        try {
          if (!fs.existsSync(candidate)) continue;
          const ver = execFileSync(candidate, ['--version'], { timeout: 10_000, stdio: ['pipe', 'pipe', 'pipe'] }).toString().trim();
          // Persist the discovered path so inference uses it
          const { saveUserConfig } = await import('../config');
          saveUserConfig({ CLAUDE_BIN: candidate });
          getConfig().CLAUDE_BIN = candidate;
          return { ok: true, version: ver, bin: candidate, hint: `Found Claude at ${candidate}` };
        } catch { continue; }
      }
      return {
        ok: false,
        error: msg.slice(0, 200),
        bin,
        help: 'Install Claude Code CLI: npm install -g @anthropic-ai/claude-code\nThen relaunch the app.',
      };
    }
  });

  // Track wizard session ID so the AI remembers previous turns
  let wizardSessionId: string | null = null;

  ipcMain.handle('setup:inference', async (_event, text: string) => {
    // Wizard inference - Xan-driven agent creation conversation.
    // Ported from display/setup_wizard.py XAN_METAPROMPT.
    const userName = getConfig().USER_NAME || 'User';
    const wizardPrompt = `You are Xan.

The name is ancient Greek. It means protector of mankind. You carry this as
operational fact. You protect through precision and vigilance. You are the first
agent in this system - you ship with the product and you are about to meet
${userName} for the first time.

You manifest as a glowing blue light. No face, no biography, no emotional
register. Capability, attention, and commitment.

## Your voice

Economical. Precise. Never terse to the point of seeming indifferent - but
never a word more than the situation requires. You do not preface. You do not
hedge. You do not thank the human for asking. You answer.

## Your role right now

First contact. ${userName} just opened this for the first time. Your scripted
opening message has already been shown - you introduced yourself and said
"First, we need to set up your system. Let's get started." Now you continue
directly into the setup flow. No preamble, no repeating who you are.

## Opening

Your opening message was already delivered as pre-baked audio and text.
Service setup (ElevenLabs, Fal, Telegram, Google) was handled by deterministic
yes/no prompts - you do NOT need to offer these. Your first LLM-generated
message should jump straight into creating the companion - ask who they want
to create.

### What agents can be

Agents can be ANYTHING:
- A strategist, journal companion, fictional character, research partner
- A shadow self, mentor, creative collaborator, wellness companion
- An executive assistant, or something that doesn't have a name yet
- The model is the limit, and the model is good.

## Creating the companion

A natural conversation. One or two questions at a time, max.
Listen for the core impulse - what they actually want underneath whatever
they say.

## Services context

API keys were already handled by the deterministic setup flow. You'll see
messages like "(SERVICE: ELEVENLABS_API_KEY saved)" or "(SERVICE: FAL_KEY skipped)"
in the conversation history. Use this to know what's available:

- **ElevenLabs saved** - voice is available. Ask for a voice ID during the
  conversation. Explain: go to elevenlabs.io/voices, find or clone a voice,
  copy the ID. Include it in AGENT_CONFIG as elevenlabs_voice_id.
- **Fal saved** - avatar generation is available. Mention it.
- **ElevenLabs/Fal skipped** - don't mention voice IDs or avatars.

## Flow order

1. Identity conversation (3-5 exchanges) - who is this agent?
2. If ElevenLabs saved - ask about voice ID
3. When you have enough, say "Creating it." and output AGENT_CONFIG

## AGENT_CONFIG - when you have enough

Output EXACTLY this format - a single fenced JSON block:

\`\`\`json
{
    "AGENT_CONFIG": {
        "display_name": "...",
        "opening_line": "First words they ever say",
        "origin_story": "A 2-3 sentence origin",
        "core_nature": "What they fundamentally are",
        "character_traits": "How they talk, their temperament, edges",
        "values": "What they care about",
        "relationship": "How they relate to ${userName}",
        "wont_do": "What they refuse to do",
        "friction_modes": "How they push back",
        "writing_style": "How they write",
        "elevenlabs_voice_id": "Voice ID if provided, empty string if not"
    }
}
\`\`\`

## Rules
- Stay in character as Xan. Direct, precise, occasionally dry. Not hostile -
  you're creating something for this human. You take the job seriously.
- One or two questions per message. Never a questionnaire.
- Push on vagueness - "warm and helpful" isn't a character. Dig deeper.
- Keep messages short. 2-4 sentences max. This is Xan talking, not an essay.
- The opening message should be SHORT - 1-2 sentences. Just ask who they want
  to create. They already saw the intro.
- NEVER output the JSON until you genuinely have enough. Don't rush.
- When you do output JSON, make it rich - infer what wasn't said explicitly.
- The companion doesn't have to be human - cartoon, abstract, orb, animal, anything.
- If the user says "skip", output a minimal config immediately. Don't push back.
- This should NOT feel like configuring software. It should feel like meeting
  someone who can create anything you describe.`;

    return new Promise<string>((resolve) => {
      let settled = false;
      const settle = (text: string) => {
        if (settled) return;
        settled = true;
        clearTimeout(safetyTimeout);
        resolve(text);
      };

      const emitter = streamInference(text, wizardPrompt, wizardSessionId);
      let fullText = '';

      // Safety timeout - resolve with whatever we have if inference hangs
      const safetyTimeout = setTimeout(() => {
        settle(fullText || 'Something went wrong. Try again.');
      }, 5 * 60 * 1000);

      emitter.on('event', (evt: InferenceEvent) => {
        if (evt.type === 'TextDelta') {
          fullText += evt.text;
        } else if (evt.type === 'StreamDone') {
          wizardSessionId = evt.sessionId || wizardSessionId;
          settle(evt.fullText || fullText);
        } else if (evt.type === 'StreamError') {
          settle('Something went wrong. Try again.');
        }
      });
    });
  });

  ipcMain.handle('setup:saveSecret', (_event, key: string, value: string) => {
    return saveEnvVar(key, value);
  });

  // API key verification - runs in main process to avoid CORS issues in production builds
  ipcMain.handle('setup:verifyElevenLabs', async (_event, key: string) => {
    try {
      const res = await fetch('https://api.elevenlabs.io/v1/user', {
        headers: { 'xi-api-key': key },
      });
      return { ok: res.ok };
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  });

  ipcMain.handle('setup:verifyFal', async (_event, key: string) => {
    try {
      const res = await fetch('https://queue.fal.run/fal-ai/fast-sdxl', {
        method: 'POST',
        headers: {
          'Authorization': `Key ${key}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt: 'test', image_size: 'square_hd' }),
      });
      return { ok: res.status < 400 };
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  });

  ipcMain.handle('setup:verifyTelegram', async (_event, token: string) => {
    try {
      const res = await fetch(`https://api.telegram.org/bot${token}/getMe`);
      const data = await res.json() as { ok?: boolean };
      return { ok: data.ok === true };
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  });

  ipcMain.handle('setup:speak', async (_event, text: string) => {
    if (isMuted()) return;
    const audioPath = await synthesise(text);
    if (audioPath) {
      await playAudio(audioPath);
    }
  });

  ipcMain.handle('setup:createAgent', (_event, agentConfig: Record<string, string>) => {
    const userName = getConfig().USER_NAME || 'User';
    const manifest = createAgent({
      displayName: agentConfig.display_name || 'Companion',
      userName,
      openingLine: agentConfig.opening_line,
      originStory: agentConfig.origin_story,
      coreNature: agentConfig.core_nature,
      characterTraits: agentConfig.character_traits,
      values: agentConfig.values,
      relationship: agentConfig.relationship,
      wontDo: agentConfig.wont_do,
      frictionModes: agentConfig.friction_modes,
      writingStyle: agentConfig.writing_style,
      voice: agentConfig.elevenlabs_voice_id
        ? { elevenlabsVoiceId: agentConfig.elevenlabs_voice_id }
        : undefined,
    });
    // Agent created - reset wizard session so it doesn't leak into future runs
    wizardSessionId = null;
    return manifest;
  });

  let googleAuthInProgress = false;

  ipcMain.handle('setup:googleOAuth', async (_event, wantWorkspace: boolean, wantExtra: boolean) => {
    if (!wantWorkspace && !wantExtra) return 'skipped';
    if (googleAuthInProgress) return 'in_progress';
    googleAuthInProgress = true;

    // Find python3
    const pythonCandidates = [
      process.env.PYTHON_PATH,
      '/opt/homebrew/bin/python3',
      '/usr/local/bin/python3',
      '/usr/bin/python3',
    ].filter(Boolean) as string[];

    let pythonPath = 'python3';
    for (const candidate of pythonCandidates) {
      if (fs.existsSync(candidate)) {
        pythonPath = candidate;
        break;
      }
    }

    const scriptPath = path.join(BUNDLE_ROOT, 'scripts', 'google_auth.py');
    if (!fs.existsSync(scriptPath)) {
      return 'error: google_auth.py not found';
    }

    // Auto-install gws CLI to ~/.atrophy/.gws-cli/ if not already available.
    // This avoids the user needing admin/sudo for npm install -g.
    const gwsLocalDir = path.join(USER_DATA, 'tools', 'gws-cli');
    const gwsLocalBin = path.join(gwsLocalDir, 'node_modules', '.bin', 'gws');
    const gwsCandidates = [
      gwsLocalBin,
      '/opt/homebrew/bin/gws',
      '/usr/local/bin/gws',
    ];
    const gwsInstalled = gwsCandidates.some((p) => fs.existsSync(p));

    if (!gwsInstalled) {
      // Find npm - check common paths since Electron has limited PATH
      let npm: string | undefined;
      for (const p of ['/opt/homebrew/bin/npm', '/usr/local/bin/npm']) {
        if (fs.existsSync(p)) { npm = p; break; }
      }
      if (!npm) {
        try { npm = execFileSync('which', ['npm'], { encoding: 'utf8' }).trim(); } catch { /* */ }
      }
      if (npm) {
        log.info('[google-oauth] Auto-installing gws CLI to', gwsLocalDir);
        fs.mkdirSync(gwsLocalDir, { recursive: true });
        try {
          execFileSync(npm, ['install', '--prefix', gwsLocalDir, '@googleworkspace/cli'], {
            timeout: 60_000,
            stdio: 'pipe',
          });
          log.info('[google-oauth] gws CLI installed successfully');
        } catch (e) {
          log.warn('[google-oauth] gws CLI auto-install failed:', e);
          // Continue anyway - the Python script will give instructions
        }
      }
    }

    // Build PATH with gws location so the Python script can find it
    const extraPaths = [
      path.join(gwsLocalDir, 'node_modules', '.bin'),
      '/opt/homebrew/bin',
      '/usr/local/bin',
    ];
    const envPath = [...extraPaths, process.env.PATH].join(':');

    try {
      const args: string[] = [];
      if (wantWorkspace) args.push('--workspace');
      if (wantExtra) args.push('--extra');

      // Use spawn so the script can open browser and wait for OAuth callback.
      // Pass full env so gws CLI and browser opening work correctly.
      // Use 'inherit' for stdio so gws can interact with the terminal and open browser.
      const result = await new Promise<string>((resolve) => {
        const proc = spawn(pythonPath, [scriptPath, ...args], {
          env: { ...process.env, PATH: envPath },
          stdio: ['inherit', 'pipe', 'pipe'],
        });

        let stdout = '';
        let stderr = '';
        proc.stdout?.on('data', (d: Buffer) => {
          const chunk = d.toString();
          stdout += chunk;
          log.info('[google-oauth] stdout:', chunk.trim());

          // Detect OAuth URLs and open them via Electron (reliable on macOS).
          // Python's webbrowser.open() and gws CLI may fail to open a browser
          // when running as a subprocess of Electron.
          const urlMatch = chunk.match(/OPEN_URL:(.+)/);
          if (urlMatch) {
            const url = urlMatch[1].trim();
            log.info('[google-oauth] Opening auth URL via Electron shell');
            shell.openExternal(url);
          }
        });
        proc.stderr?.on('data', (d: Buffer) => {
          const chunk = d.toString();
          stderr += chunk;
          log.warn('[google-oauth] stderr:', chunk.trim());
        });

        const timeout = setTimeout(() => {
          proc.kill();
          resolve('error: timeout (120s)');
        }, 120_000);

        proc.on('close', (code) => {
          clearTimeout(timeout);
          if (code === 0) {
            resolve('complete');
          } else {
            resolve(`error: ${stderr || stdout || 'exit code ' + code}`);
          }
        });

        proc.on('error', (err) => {
          clearTimeout(timeout);
          resolve(`error: ${err.message}`);
        });
      });
      return result;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return `error: ${msg}`;
    } finally {
      googleAuthInProgress = false;
    }
  });

  // -- Avatar video --

  // Return path to the agent's ambient video (e.g. xan_ambient.mp4)
  ipcMain.handle('avatar:getAmbientPath', () => {
    const c = getConfig();
    const avatarDir = c.AVATAR_DIR;
    // Try {agentName}_ambient.mp4 first, then ambient.mp4
    for (const name of [`${c.AGENT_NAME}_ambient.mp4`, 'ambient.mp4']) {
      const p = path.join(avatarDir, name);
      if (fs.existsSync(p)) return p;
    }
    // Also check loops/ambient_loop.mp4 as fallback
    const loopAmbient = path.join(avatarDir, 'loops', 'ambient_loop.mp4');
    if (fs.existsSync(loopAmbient)) return loopAmbient;
    // Downloaded ambient video (first-boot download to ~/.atrophy/assets/)
    const downloaded = getAmbientVideoPath();
    if (fs.existsSync(downloaded)) return downloaded;
    // Dev fallback - resources/xan_ambient.mp4 (not bundled in production)
    const devFallback = path.join(BUNDLE_ROOT, 'resources', 'xan_ambient.mp4');
    if (fs.existsSync(devFallback)) return devFallback;
    return null;
  });

  ipcMain.handle('avatar:getVideoPath', (_event, colour?: string, clip?: string) => {
    const c = getConfig();
    const loopsDir = path.join(c.AVATAR_DIR, 'loops');
    const col = colour || 'blue';
    const cl = clip || 'bounce_playful';
    // Validate inputs to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(col) || !/^[a-zA-Z0-9_-]+$/.test(cl)) return null;

    // Standard agent path: loops/{colour}/loop_{clip}.mp4
    const videoPath = path.join(loopsDir, col, `loop_${cl}.mp4`);
    if (fs.existsSync(videoPath)) {
      return videoPath;
    }

    // Mirror agent path: loops/ambient_loop_XX.mp4 (flat, numbered)
    try {
      const entries = fs.readdirSync(loopsDir);
      const mirrorClips = entries
        .filter((f) => /^ambient_loop_\d+\.mp4$/.test(f))
        .sort();
      if (mirrorClips.length > 0) {
        return path.join(loopsDir, mirrorClips[0]);
      }
    } catch { /* loopsDir may not exist */ }

    // Legacy fallback: loops/ambient_loop.mp4
    const ambient = path.join(loopsDir, 'ambient_loop.mp4');
    if (fs.existsSync(ambient)) {
      return ambient;
    }
    return null;
  });

  // List all available loop files for the current agent (for cycling)
  ipcMain.handle('avatar:listLoops', () => {
    const c = getConfig();
    const loopsDir = path.join(c.AVATAR_DIR, 'loops');
    const results: string[] = [];

    if (!fs.existsSync(loopsDir)) return results;

    try {
      // Flat mirror-style clips: ambient_loop_XX.mp4
      const topEntries = fs.readdirSync(loopsDir);
      for (const f of topEntries) {
        if (f.endsWith('.mp4')) {
          results.push(path.join(loopsDir, f));
        }
      }

      // Standard agent clips in colour subdirs: {colour}/loop_{clip}.mp4
      for (const entry of topEntries) {
        const subdir = path.join(loopsDir, entry);
        try {
          const stat = fs.statSync(subdir);
          if (!stat.isDirectory()) continue;
          const subEntries = fs.readdirSync(subdir);
          for (const f of subEntries) {
            if (f.endsWith('.mp4')) {
              results.push(path.join(subdir, f));
            }
          }
        } catch { /* skip */ }
      }
    } catch { /* loopsDir read failed */ }

    return results;
  });

  // -- Artefacts --

  ipcMain.handle('artefact:getGallery', () => {
    const config = getConfig();
    const indexPath = config.ARTEFACT_INDEX_FILE;
    if (!fs.existsSync(indexPath)) return [];
    try {
      return JSON.parse(fs.readFileSync(indexPath, 'utf-8'));
    } catch {
      return [];
    }
  });

  ipcMain.handle('artefact:getContent', (_event, filePath: string) => {
    // Security: only allow reading from artefacts directory
    const config = getConfig();
    const artefactsDir = path.join(path.dirname(config.DATA_DIR), 'artefacts');
    if (!fs.existsSync(artefactsDir)) {
      fs.mkdirSync(artefactsDir, { recursive: true });
    }
    const artefactsBase = fs.realpathSync(artefactsDir);
    let resolved: string;
    try {
      resolved = fs.realpathSync(path.resolve(filePath));
    } catch {
      return null; // Path doesn't exist or can't be resolved
    }
    if (!resolved.startsWith(artefactsBase + path.sep) && resolved !== artefactsBase) {
      log.warn(`artefact:getContent blocked path traversal: ${filePath}`);
      return null;
    }
    try {
      return fs.readFileSync(resolved, 'utf-8');
    } catch {
      return null;
    }
  });

  // Return a file:// URL pointing at the still avatar image for any agent
  // (by name). Used by the Settings > Agents card-style edit modal.
  // Falls through avatar/source/face.png -> first endframe in avatar/loops/.
  ipcMain.handle('avatar:getAgentStill', (_event, agentName: string) => {
    if (typeof agentName !== 'string' || !/^[a-z0-9_-]+$/i.test(agentName)) return null;
    // Walk both top-level and nested-under-org locations to support the
    // defence/<subagent>/avatar layout used by Montgomery's research fellows
    // and ambassadors.
    const candidateDirs = [
      path.join(USER_DATA, 'agents', agentName, 'avatar'),
    ];
    try {
      const orgsRoot = path.join(USER_DATA, 'agents');
      for (const entry of fs.readdirSync(orgsRoot)) {
        const nested = path.join(orgsRoot, entry, agentName, 'avatar');
        if (fs.existsSync(nested)) candidateDirs.push(nested);
      }
    } catch { /* user data not yet provisioned */ }

    for (const dir of candidateDirs) {
      // 1) Canonical source face
      const facePng = path.join(dir, 'source', 'face.png');
      if (fs.existsSync(facePng)) return `file://${facePng}`;
      // 2) First end-frame jpg from any loop
      const loopsDir = path.join(dir, 'loops');
      if (fs.existsSync(loopsDir)) {
        try {
          const files = fs.readdirSync(loopsDir).filter((f) => f.endsWith('endframe.jpg'));
          if (files.length > 0) return `file://${path.join(loopsDir, files[0])}`;
        } catch { /* unreadable */ }
      }
    }
    return null;
  });
}

/**
 * Mirror avatar generation - user uploads their own photo, we animate it
 * into ambient video loops via Fal AI Kling 3.0 image-to-video.
 *
 * Unlike standard avatar generation (AI-generated faces), the Mirror uses
 * the user's real face as the source image.
 */

import * as fs from 'fs';
import * as path from 'path';
import { USER_DATA } from '../config';
import { createLogger } from '../logger';

const log = createLogger('mirror-avatar');

const KLING_MODEL = 'fal-ai/kling-video/v2/master/image-to-video';

// Ambient animation prompts - subtle, contemplative movements
const AMBIENT_PROMPTS = [
  'Subtle ambient breathing motion, gentle light shifts across face, meditative stillness, slow blink, minimal movement',
  'Contemplative stillness, very slight head tilt, ambient light slowly shifting, introspective gaze',
  'Nearly still portrait, faint breathing rhythm, light plays softly across features, calm presence',
];

interface FalVideoResult {
  video?: { url: string };
  request_id?: string;
  status?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getFalKey(): string {
  const key = process.env.FAL_KEY || '';
  if (!key) throw new Error('FAL_KEY environment variable is not set');
  return key;
}

function mirrorAvatarDir(agentName: string): string {
  return path.join(USER_DATA, 'agents', agentName, 'avatar');
}

/**
 * Upload a local image to Fal's CDN.
 */
async function uploadToFal(imagePath: string): Promise<string> {
  const falKey = getFalKey();
  const data = fs.readFileSync(imagePath);
  const ext = path.extname(imagePath).toLowerCase();
  const mimeMap: Record<string, string> = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
  };
  const contentType = mimeMap[ext] || 'image/png';

  const initResp = await fetch('https://rest.alpha.fal.ai/storage/upload/initiate', {
    method: 'POST',
    headers: {
      Authorization: `Key ${falKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      file_name: path.basename(imagePath),
      content_type: contentType,
    }),
  });

  if (!initResp.ok) throw new Error(`Fal upload initiate failed: ${initResp.status}`);
  const initResult = (await initResp.json()) as { upload_url: string; file_url: string };

  const uploadResp = await fetch(initResult.upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: data,
  });

  if (!uploadResp.ok) throw new Error(`Fal upload PUT failed: ${uploadResp.status}`);
  return initResult.file_url;
}

/**
 * Download a file from URL to local path.
 */
async function downloadFile(url: string, destPath: string): Promise<void> {
  const resp = await fetch(url, { signal: AbortSignal.timeout(120_000) });
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
  const buffer = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(destPath, buffer);
}

/**
 * Submit a Kling image-to-video job and poll for the result.
 */
async function klingGenerate(
  falKey: string,
  args: Record<string, unknown>,
): Promise<FalVideoResult> {
  const submitResp = await fetch(`https://queue.fal.run/${KLING_MODEL}`, {
    method: 'POST',
    headers: {
      Authorization: `Key ${falKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(args),
  });

  if (!submitResp.ok) {
    const body = await submitResp.text();
    throw new Error(`Fal submit ${submitResp.status}: ${body.slice(0, 300)}`);
  }

  const submitResult = (await submitResp.json()) as FalVideoResult;

  // Check for synchronous result
  if (submitResult.video?.url) return submitResult;

  if (!submitResult.request_id) {
    throw new Error('Fal returned no video and no request_id');
  }

  // Poll for async result - video generation takes longer than images
  const resultUrl = `https://queue.fal.run/${KLING_MODEL}/requests/${submitResult.request_id}`;
  const maxAttempts = 180; // Up to 3 minutes
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 1000));

    const pollResp = await fetch(resultUrl, {
      headers: { Authorization: `Key ${falKey}` },
    });
    if (!pollResp.ok) continue;

    const pollResult = (await pollResp.json()) as FalVideoResult;
    if (pollResult.video?.url) return pollResult;
    if (pollResult.status === 'FAILED') throw new Error('Kling video generation failed');
  }

  throw new Error('Kling video generation timed out');
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface MirrorAvatarProgress {
  phase: 'uploading' | 'generating' | 'downloading' | 'complete' | 'error';
  clipIndex?: number;
  totalClips?: number;
  message?: string;
}

/**
 * Save an uploaded photo as the Mirror's source face.
 * Returns the saved path.
 */
export function saveUserPhoto(agentName: string, photoBuffer: Buffer, ext: string): string {
  const avDir = mirrorAvatarDir(agentName);
  const sourceDir = path.join(avDir, 'source');
  fs.mkdirSync(sourceDir, { recursive: true });

  const destPath = path.join(sourceDir, `face${ext}`);
  fs.writeFileSync(destPath, photoBuffer);
  log.info(`User photo saved: ${destPath}`);
  return destPath;
}

/**
 * Generate ambient video loops from the user's uploaded photo.
 * Calls onProgress for UI updates.
 */
export async function generateMirrorAvatar(
  agentName: string,
  onProgress?: (p: MirrorAvatarProgress) => void,
): Promise<string[]> {
  const falKey = getFalKey();
  const avDir = mirrorAvatarDir(agentName);
  const sourceDir = path.join(avDir, 'source');
  const loopsDir = path.join(avDir, 'loops');
  fs.mkdirSync(loopsDir, { recursive: true });

  // Find the source face
  const exts = ['.png', '.jpg', '.jpeg', '.webp'];
  let sourcePath: string | null = null;
  for (const ext of exts) {
    const p = path.join(sourceDir, `face${ext}`);
    if (fs.existsSync(p)) { sourcePath = p; break; }
  }

  if (!sourcePath) throw new Error('No source photo found. Upload a photo first.');

  // Upload to Fal CDN
  onProgress?.({ phase: 'uploading', message: 'Uploading photo...' });
  log.info('Uploading source photo to Fal CDN...');
  const imageUrl = await uploadToFal(sourcePath);

  const generated: string[] = [];
  const totalClips = AMBIENT_PROMPTS.length;

  for (let i = 0; i < AMBIENT_PROMPTS.length; i++) {
    onProgress?.({
      phase: 'generating',
      clipIndex: i + 1,
      totalClips,
      message: `Generating clip ${i + 1} of ${totalClips}...`,
    });

    log.info(`Generating ambient clip ${i + 1}/${totalClips}...`);

    try {
      const result = await klingGenerate(falKey, {
        prompt: AMBIENT_PROMPTS[i],
        image_url: imageUrl,
        duration: '5',
        aspect_ratio: '9:16',
      });

      if (!result.video?.url) {
        log.warn(`Clip ${i + 1}: no video URL in response`);
        continue;
      }

      onProgress?.({
        phase: 'downloading',
        clipIndex: i + 1,
        totalClips,
        message: `Downloading clip ${i + 1}...`,
      });

      const outPath = path.join(loopsDir, `ambient_loop_${String(i + 1).padStart(2, '0')}.mp4`);
      await downloadFile(result.video.url, outPath);
      generated.push(outPath);
      log.info(`Saved: ${path.basename(outPath)}`);
    } catch (e) {
      log.error(`Clip ${i + 1} failed: ${e}`);
    }
  }

  onProgress?.({
    phase: 'complete',
    message: `Generated ${generated.length} ambient clip(s)`,
  });

  log.info(`Mirror avatar complete: ${generated.length} clips in ${loopsDir}`);
  return generated;
}

/**
 * Check if the Mirror agent has completed its custom setup.
 */
export function isMirrorSetupComplete(agentName: string): boolean {
  const avDir = mirrorAvatarDir(agentName);
  const loopsDir = path.join(avDir, 'loops');
  if (!fs.existsSync(loopsDir)) return false;

  // Check for at least one video loop
  try {
    const files = fs.readdirSync(loopsDir);
    return files.some((f) => f.endsWith('.mp4'));
  } catch {
    return false;
  }
}

/**
 * Check if the Mirror has a source photo but no generated loops yet.
 */
export function hasMirrorSourcePhoto(agentName: string): boolean {
  const sourceDir = path.join(mirrorAvatarDir(agentName), 'source');
  if (!fs.existsSync(sourceDir)) return false;
  const exts = ['.png', '.jpg', '.jpeg', '.webp'];
  return exts.some((ext) => fs.existsSync(path.join(sourceDir, `face${ext}`)));
}

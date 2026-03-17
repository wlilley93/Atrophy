/**
 * Avatar generation - face images via Fal AI, ambient audio via ElevenLabs.
 * Port of scripts/agents/companion/generate_face.py (and idle loop audio).
 *
 * Functions:
 *   generateFace(agentName)          - Fal AI image gen with appearance from agent.json
 *   generateAmbientLoop(agentName)   - ElevenLabs TTS ambient audio to audio/
 *   trimStaticTails(audioPath)       - remove trailing silence via ffprobe
 *   runFullAvatarPipeline(agentName) - orchestrate all steps
 */

import { execSync, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA } from '../config';
import { createLogger } from '../logger';

const log = createLogger('avatar');

// ---------------------------------------------------------------------------
// Fal AI configuration
// ---------------------------------------------------------------------------

const FAL_MODEL = 'fal-ai/flux-general';
const IP_ADAPTER_PATH = 'XLabs-AI/flux-ip-adapter';
const IP_ADAPTER_WEIGHT = 'ip_adapter.safetensors';
const IMAGE_ENCODER_PATH = 'openai/clip-vit-large-patch14';
const DEFAULT_IP_ADAPTER_SCALE = 0.7;
const DEFAULT_INFERENCE_STEPS = 50;
const DEFAULT_GUIDANCE_SCALE = 3.5;
const DEFAULT_IMAGE_WIDTH = 768;
const DEFAULT_IMAGE_HEIGHT = 1024;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentManifest {
  display_name?: string;
  appearance?: AppearanceSpec;
  [key: string]: unknown;
}

interface AppearanceSpec {
  prompt?: string;
  negative_prompt?: string;
  ip_adapter_scale?: number;
  inference_steps?: number;
  guidance_scale?: number;
  width?: number;
  height?: number;
}

interface FalImage {
  url: string;
  content_type?: string;
}

export interface FalResult {
  images?: FalImage[];
  request_id?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function loadAgentManifest(agentName: string): AgentManifest {
  const paths = [
    path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json'),
  ];
  for (const p of paths) {
    try {
      if (fs.existsSync(p)) {
        return JSON.parse(fs.readFileSync(p, 'utf-8')) as AgentManifest;
      }
    } catch {
      continue;
    }
  }
  return {};
}

export function getFalKey(): string {
  const key = process.env.FAL_KEY || '';
  if (!key) {
    throw new Error('FAL_KEY environment variable is not set');
  }
  return key;
}

function avatarDir(agentName: string): string {
  return path.join(USER_DATA, 'agents', agentName, 'avatar');
}

function referenceDir(agentName: string): string {
  return path.join(avatarDir(agentName), 'Reference');
}

function candidatesDir(agentName: string): string {
  return path.join(avatarDir(agentName), 'candidates');
}

function audioDir(agentName: string): string {
  return path.join(avatarDir(agentName), 'audio');
}

/**
 * Get reference images from the agent's avatar/Reference directory.
 * Returns empty array if no references found.
 */
export function getReferenceImages(agentName: string): string[] {
  const refDir = referenceDir(agentName);
  if (!fs.existsSync(refDir)) return [];

  const exts = new Set(['.png', '.jpg', '.jpeg', '.webp']);
  return fs
    .readdirSync(refDir)
    .filter((f) => exts.has(path.extname(f).toLowerCase()))
    .sort()
    .map((f) => path.join(refDir, f));
}

/**
 * Upload a local image to Fal's CDN for use as an IP adapter reference.
 * Returns the uploaded URL.
 */
export async function uploadToFal(imagePath: string): Promise<string> {
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

  // Initiate upload
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

  if (!initResp.ok) {
    throw new Error(`Fal upload initiate failed: ${initResp.status}`);
  }

  const initResult = (await initResp.json()) as { upload_url: string; file_url: string };

  // Upload the file
  const uploadResp = await fetch(initResult.upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: data,
  });

  if (!uploadResp.ok) {
    throw new Error(`Fal upload PUT failed: ${uploadResp.status}`);
  }

  return initResult.file_url;
}

/**
 * Download an image from a URL and save it to the given path.
 */
export async function downloadImage(url: string, destPath: string): Promise<void> {
  const resp = await fetch(url, { signal: AbortSignal.timeout(60_000) });
  if (!resp.ok) {
    throw new Error(`Image download failed: ${resp.status}`);
  }
  const buffer = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(destPath, buffer);
}

// ---------------------------------------------------------------------------
// generateFace
// ---------------------------------------------------------------------------

/**
 * Generate face candidates via Fal AI image generation.
 *
 * Uses the agent's appearance spec from agent.json if available.
 * If reference images exist in avatar/Reference/, uses Flux IP-Adapter
 * for style guidance.
 *
 * Generated images are saved to avatar/candidates/.
 */
export async function generateFace(
  agentName: string,
  perRef = 3,
): Promise<string[]> {
  const falKey = getFalKey();
  const manifest = loadAgentManifest(agentName);
  const appearance = manifest.appearance || {};

  const prompt = appearance.prompt || buildDefaultPrompt(manifest);
  const negativePrompt = appearance.negative_prompt || DEFAULT_NEGATIVE;
  const ipScale = appearance.ip_adapter_scale ?? DEFAULT_IP_ADAPTER_SCALE;
  const steps = appearance.inference_steps ?? DEFAULT_INFERENCE_STEPS;
  const guidance = appearance.guidance_scale ?? DEFAULT_GUIDANCE_SCALE;
  const width = appearance.width ?? DEFAULT_IMAGE_WIDTH;
  const height = appearance.height ?? DEFAULT_IMAGE_HEIGHT;

  const refs = getReferenceImages(agentName);
  const outDir = candidatesDir(agentName);
  fs.mkdirSync(outDir, { recursive: true });

  const generated: string[] = [];

  if (refs.length === 0) {
    // No reference images - generate without IP adapter
    log.info('No reference images found - generating without IP adapter');

    for (let i = 0; i < perRef; i++) {
      log.info(`Generating candidate ${i + 1}/${perRef}...`);
      try {
        const result = await falGenerate(falKey, {
          prompt,
          negative_prompt: negativePrompt,
          num_inference_steps: steps,
          guidance_scale: guidance,
          image_size: { width, height },
          output_format: 'png',
        });

        const images = result.images || [];
        if (images.length === 0) {
          log.warn('No images in response');
          continue;
        }

        const outPath = path.join(outDir, `candidate_${String(i + 1).padStart(2, '0')}.png`);
        await downloadImage(images[0].url, outPath);
        generated.push(outPath);
        log.debug(`Saved: ${path.basename(outPath)}`);
      } catch (e) {
        log.error(`Generation failed: ${e}`);
      }
    }
  } else {
    // Reference images available - use IP adapter
    log.info(`${refs.length} reference image(s) found`);

    for (let refIdx = 0; refIdx < refs.length; refIdx++) {
      const refPath = refs[refIdx];
      const refName = path.parse(refPath).name;
      log.info(`Reference ${refIdx + 1}/${refs.length}: ${path.basename(refPath)}`);

      let refUrl: string;
      try {
        refUrl = await uploadToFal(refPath);
      } catch (e) {
        log.error(`Upload failed: ${e}`);
        continue;
      }

      for (let j = 0; j < perRef; j++) {
        const num = refIdx * perRef + j + 1;
        const total = refs.length * perRef;
        log.info(`[${String(num).padStart(2, '0')}/${String(total).padStart(2, '0')}] Generating...`);

        try {
          const result = await falGenerate(falKey, {
            prompt,
            negative_prompt: negativePrompt,
            num_inference_steps: steps,
            guidance_scale: guidance,
            image_size: { width, height },
            output_format: 'png',
            ip_adapters: [
              {
                path: IP_ADAPTER_PATH,
                weight_name: IP_ADAPTER_WEIGHT,
                image_encoder_path: IMAGE_ENCODER_PATH,
                image_url: refUrl,
                scale: ipScale,
              },
            ],
          });

          const images = result.images || [];
          if (images.length === 0) {
            log.warn('No images in response');
            continue;
          }

          const outPath = path.join(
            outDir,
            `ref${String(refIdx + 1).padStart(2, '0')}_${String(j + 1).padStart(2, '0')}_${refName}.png`,
          );
          await downloadImage(images[0].url, outPath);
          generated.push(outPath);
          log.debug(`Saved: ${path.basename(outPath)}`);
        } catch (e) {
          log.error(`Generation failed: ${e}`);
        }
      }
    }
  }

  log.info(`Generated ${generated.length} candidate(s) in ${outDir}`);
  return generated;
}

/**
 * Call Fal AI's queue API and wait for the result.
 */
export async function falGenerate(
  falKey: string,
  args: Record<string, unknown>,
): Promise<FalResult> {
  const submitResp = await fetch(`https://queue.fal.run/${FAL_MODEL}`, {
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

  const submitResult = (await submitResp.json()) as FalResult;

  // Check for synchronous result
  if (submitResult.images && submitResult.images.length > 0) {
    return submitResult;
  }

  if (!submitResult.request_id) {
    throw new Error('Fal returned no images and no request_id');
  }

  // Poll for async result
  const resultUrl = `https://queue.fal.run/${FAL_MODEL}/requests/${submitResult.request_id}`;
  const maxAttempts = 60; // Up to 60 seconds
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 1000));

    const pollResp = await fetch(resultUrl, {
      headers: { Authorization: `Key ${falKey}` },
    });
    if (!pollResp.ok) continue;

    const pollResult = (await pollResp.json()) as FalResult & { status?: string };
    if (pollResult.images && pollResult.images.length > 0) {
      return pollResult;
    }
    if (pollResult.status === 'FAILED') {
      throw new Error('Fal image generation failed');
    }
  }

  throw new Error('Fal image generation timed out');
}

// ---------------------------------------------------------------------------
// Default prompt (when agent.json has no appearance spec)
// ---------------------------------------------------------------------------

const DEFAULT_NEGATIVE = [
  'lip filler, botox, cosmetic surgery, duck lips, overfilled lips,',
  'fake tan, orange skin, heavy contour, heavy makeup,',
  'cartoon, illustration, anime, 3D render, CGI, AI skin,',
  'plastic skin, poreless, airbrushed, facetune, overly smooth,',
  'uncanny valley, doll-like, wax figure, dead eyes, vacant stare,',
  'harsh lighting, flash, low quality, blurry, oversaturated',
].join(' ');

function buildDefaultPrompt(manifest: AgentManifest): string {
  const name = manifest.display_name || 'companion';
  return (
    `Hyper-realistic close-up selfie photograph of ${name}. ` +
    'POV smartphone camera aesthetic, looking directly at the viewer. ' +
    'Natural lighting, real skin texture with visible pores. ' +
    'Shot on iPhone front camera, portrait mode bokeh, ultra-high detail.'
  );
}

// ---------------------------------------------------------------------------
// generateAmbientLoop
// ---------------------------------------------------------------------------

/**
 * Generate ambient audio loop via ElevenLabs TTS.
 *
 * Creates a soft ambient audio clip that plays behind the avatar idle state.
 * Uses a gentle breathing/ambient prompt to synthesise a short loop.
 * Output saved to avatar/audio/ambient_loop.mp3.
 */
export async function generateAmbientLoop(agentName: string): Promise<string | null> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  if (!config.ELEVENLABS_API_KEY || !config.ELEVENLABS_VOICE_ID) {
    log.info('ElevenLabs not configured - skipping ambient loop');
    return null;
  }

  const outDirPath = audioDir(agentName);
  fs.mkdirSync(outDirPath, { recursive: true });
  const outPath = path.join(outDirPath, 'ambient_loop.mp3');

  // Soft ambient text - designed to produce gentle, near-silent breathing audio
  const ambientText =
    '... ... ... ... ... ... ... ... ' +
    '... ... ... ... ... ... ... ...';

  const url =
    `https://api.elevenlabs.io/v1/text-to-speech` +
    `/${config.ELEVENLABS_VOICE_ID}/stream` +
    `?output_format=mp3_44100_128`;

  log.info('Generating ambient loop via ElevenLabs...');

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'xi-api-key': config.ELEVENLABS_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: ambientText,
        model_id: config.ELEVENLABS_MODEL,
        voice_settings: {
          stability: Math.min(1.0, config.ELEVENLABS_STABILITY + 0.2),
          similarity_boost: config.ELEVENLABS_SIMILARITY,
          style: 0.0, // Minimal expression
        },
      }),
    });

    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`ElevenLabs ${resp.status}: ${body.slice(0, 300)}`);
    }

    const buffer = Buffer.from(await resp.arrayBuffer());
    fs.writeFileSync(outPath, buffer);
    log.info(`Ambient loop saved: ${outPath}`);

    // Trim trailing silence if ffprobe is available
    await trimStaticTails(outPath);

    return outPath;
  } catch (e) {
    log.error(`Ambient loop generation failed: ${e}`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// trimStaticTails
// ---------------------------------------------------------------------------

/**
 * Remove trailing silence from an audio file using ffprobe + ffmpeg.
 *
 * Detects the last non-silent moment via ffprobe's silencedetect filter,
 * then trims the file to that point. Skips gracefully if ffprobe/ffmpeg
 * are not available.
 */
export async function trimStaticTails(audioPath: string): Promise<void> {
  if (!fs.existsSync(audioPath)) return;

  // Check if ffprobe is available
  try {
    execSync('which ffprobe', { stdio: 'pipe' });
  } catch {
    log.warn('ffprobe not found - skipping silence trim');
    return;
  }

  try {
    // Detect silence regions
    const detectResult = spawnSync('ffprobe', [
      '-v', 'error',
      '-f', 'lavfi',
      '-i', `amovie=${audioPath},silencedetect=noise=-40dB:d=0.5`,
      '-show_entries', 'frame_tags=lavfi.silence_start',
      '-of', 'csv=p=0',
    ], { encoding: 'utf-8', timeout: 30000 });

    if (detectResult.status !== 0 || !detectResult.stdout.trim()) {
      // No silence detected or ffprobe failed - leave file as is
      return;
    }

    // Get the last silence_start timestamp
    const lines = detectResult.stdout.trim().split('\n').filter(Boolean);
    if (lines.length === 0) return;

    const lastSilenceStart = parseFloat(lines[lines.length - 1]);
    if (isNaN(lastSilenceStart) || lastSilenceStart <= 0) return;

    // Add a small fade-out buffer
    const trimPoint = lastSilenceStart + 0.3;

    // Trim with ffmpeg
    const trimmedPath = audioPath + '.trimmed.mp3';
    const trimResult = spawnSync('ffmpeg', [
      '-y',
      '-i', audioPath,
      '-t', String(trimPoint),
      '-af', 'afade=t=out:st=' + String(Math.max(0, trimPoint - 0.5)) + ':d=0.5',
      '-q:a', '2',
      trimmedPath,
    ], { stdio: 'pipe', timeout: 30000 });

    if (trimResult.status === 0 && fs.existsSync(trimmedPath)) {
      fs.renameSync(trimmedPath, audioPath);
      log.debug(`Trimmed trailing silence at ${trimPoint.toFixed(1)}s`);
    } else {
      // Clean up failed attempt
      try { fs.unlinkSync(trimmedPath); } catch { /* noop */ }
    }
  } catch (e) {
    log.warn(`Silence trim failed: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// runFullAvatarPipeline
// ---------------------------------------------------------------------------

/**
 * Orchestrate the full avatar generation pipeline:
 *   1. Generate face candidates via Fal AI
 *   2. Generate ambient audio loop via ElevenLabs
 *
 * The user should review candidates in avatar/candidates/ and copy their
 * chosen face to avatar/source/face.png before using it with the idle
 * loop renderer.
 */
export async function runFullAvatarPipeline(agentName: string): Promise<void> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  log.info(`Starting full pipeline for agent: ${agentName}`);
  log.debug(`Avatar dir: ${avatarDir(agentName)}`);

  // Step 1: Generate face candidates
  log.info('Step 1/2: Generating face candidates...');
  let candidates: string[] = [];
  try {
    candidates = await generateFace(agentName);
  } catch (e) {
    log.error(`Face generation failed: ${e}`);
  }

  // Step 2: Generate ambient audio loop
  log.info('Step 2/2: Generating ambient audio loop...');
  let ambientPath: string | null = null;
  try {
    ambientPath = await generateAmbientLoop(agentName);
  } catch (e) {
    log.error(`Ambient loop failed: ${e}`);
  }

  // Summary
  log.info('Pipeline complete.');
  log.info(`Face candidates: ${candidates.length}`);
  log.info(`Ambient loop: ${ambientPath || 'not generated'}`);

  if (candidates.length > 0) {
    log.info(`Review candidates in: ${candidatesDir(agentName)}`);
    log.info(`Copy chosen face to: ${path.join(avatarDir(agentName), 'source', 'face.png')}`);
  }
}

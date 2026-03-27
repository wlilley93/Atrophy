# src/main/jobs/generate-avatar.ts - Avatar Generation

**Dependencies:** `child_process`, `fs`, `path`, `../config`, `../logger`  
**Purpose:** Generate face images via Fal AI and ambient audio via ElevenLabs

## Overview

This module handles avatar generation for agents using:
- **Fal AI** (Flux model with IP-Adapter) for face image generation
- **ElevenLabs** for ambient audio loop generation


## Fal AI Configuration

```typescript
const FAL_MODEL = 'fal-ai/flux-general';
const IP_ADAPTER_PATH = 'XLabs-AI/flux-ip-adapter';
const IP_ADAPTER_WEIGHT = 'ip_adapter.safetensors';
const IMAGE_ENCODER_PATH = 'openai/clip-vit-large-patch14';
const DEFAULT_IP_ADAPTER_SCALE = 0.7;
const DEFAULT_INFERENCE_STEPS = 50;
const DEFAULT_GUIDANCE_SCALE = 3.5;
const DEFAULT_IMAGE_WIDTH = 768;
const DEFAULT_IMAGE_HEIGHT = 1024;
```

**Purpose:** Default Fal AI configuration for image generation.

**Model:** Flux with IP-Adapter for style guidance from reference images.

## Types

### AgentManifest

```typescript
export interface AgentManifest {
  display_name?: string;
  appearance?: AppearanceSpec;
  [key: string]: unknown;
}
```

### AppearanceSpec

```typescript
interface AppearanceSpec {
  prompt?: string;
  negative_prompt?: string;
  ip_adapter_scale?: number;
  inference_steps?: number;
  guidance_scale?: number;
  width?: number;
  height?: number;
}
```

### FalResult

```typescript
export interface FalResult {
  images?: FalImage[];
  request_id?: string;
}
```

## Helper Functions

### loadAgentManifest

```typescript
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
```

**Purpose:** Load agent manifest from user data.

### getFalKey

```typescript
export function getFalKey(): string {
  const key = process.env.FAL_KEY || '';
  if (!key) {
    throw new Error('FAL_KEY environment variable is not set');
  }
  return key;
}
```

**Purpose:** Get Fal API key from environment.

### Directory Helpers

```typescript
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
```

### getReferenceImages

```typescript
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
```

**Purpose:** Get reference images from `avatar/Reference/` directory.

**Supported formats:** PNG, JPG, JPEG, WebP

### uploadToFal

```typescript
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

  const initResult = await initResp.json() as { upload_url: string; file_url: string };

  // Upload the file
  const uploadResp = await fetch(initResult.upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: data,
  });

  return initResult.file_url;
}
```

**Purpose:** Upload local image to Fal's CDN for IP-Adapter use.

**Flow:**
1. Initiate upload via Fal API
2. Get upload URL and file URL
3. PUT file to upload URL
4. Return file URL for use in generation

### downloadImage

```typescript
export async function downloadImage(url: string, destPath: string): Promise<void> {
  const resp = await fetch(url, { signal: AbortSignal.timeout(60_000) });
  if (!resp.ok) {
    throw new Error(`Image download failed: ${resp.status}`);
  }
  const buffer = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(destPath, buffer);
}
```

**Purpose:** Download generated image from Fal CDN.

**Timeout:** 60 seconds

## generateFace

```typescript
export async function generateFace(
  agentName: string,
  perRef = 3,
): Promise<string[]> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const manifest = loadAgentManifest(agentName);
  const appearance = manifest.appearance || {};

  const prompt = appearance.prompt || `A portrait of ${manifest.display_name || agentName}`;
  const negativePrompt = appearance.negative_prompt || 'blurry, low quality';

  const ipAdapterScale = appearance.ip_adapter_scale ?? DEFAULT_IP_ADAPTER_SCALE;
  const inferenceSteps = appearance.inference_steps ?? DEFAULT_INFERENCE_STEPS;
  const guidanceScale = appearance.guidance_scale ?? DEFAULT_GUIDANCE_SCALE;
  const width = appearance.width ?? DEFAULT_IMAGE_WIDTH;
  const height = appearance.height ?? DEFAULT_IMAGE_HEIGHT;

  // Get reference images
  const refImages = getReferenceImages(agentName);
  if (refImages.length === 0) {
    log.warn('No reference images found');
    return [];
  }

  // Upload reference images
  const uploadedUrls: string[] = [];
  for (const refPath of refImages) {
    try {
      const url = await uploadToFal(refPath);
      uploadedUrls.push(url);
    } catch (e) {
      log.warn(`Failed to upload ${refPath}: ${e}`);
    }
  }

  if (uploadedUrls.length === 0) {
    return [];
  }

  // Generate images via Fal API
  const falKey = getFalKey();
  const generatedPaths: string[] = [];
  const candDir = candidatesDir(agentName);
  fs.mkdirSync(candDir, { recursive: true });

  for (const refUrl of uploadedUrls) {
    for (let i = 0; i < perRef; i++) {
      try {
        const resp = await fetch(`https://rest.alpha.fal.ai/fal/${FAL_MODEL}`, {
          method: 'POST',
          headers: {
            Authorization: `Key ${falKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            prompt,
            negative_prompt: negativePrompt,
            image_url: refUrl,
            ip_adapter_scale: ipAdapterScale,
            inference_steps: inferenceSteps,
            guidance_scale: guidanceScale,
            image_width: width,
            image_height: height,
          }),
        });

        if (!resp.ok) {
          throw new Error(`Fal API failed: ${resp.status}`);
        }

        const result = await resp.json() as FalResult;
        if (result.images && result.images.length > 0) {
          const imageUrl = result.images[0].url;
          const destPath = path.join(candDir, `candidate_${Date.now()}_${i}.png`);
          await downloadImage(imageUrl, destPath);
          generatedPaths.push(destPath);
          log.info(`Generated ${destPath}`);
        }
      } catch (e) {
        log.warn(`Generation failed: ${e}`);
      }
    }
  }

  return generatedPaths;
}
```

**Flow:**
1. Load agent manifest and appearance spec
2. Get reference images from `avatar/Reference/`
3. Upload reference images to Fal CDN
4. For each reference, generate `perRef` candidates
5. Download generated images to `avatar/candidates/`

**Parameters from manifest:**
- `prompt`: Generation prompt
- `negative_prompt`: What to avoid
- `ip_adapter_scale`: Reference image influence (default 0.7)
- `inference_steps`: Quality vs speed (default 50)
- `guidance_scale`: Prompt adherence (default 3.5)
- `width`, `height`: Output dimensions (default 768x1024)

## trimStaticTails

```typescript
export function trimStaticTails(audioPath: string): string {
  const outputPath = audioPath.replace(/\.[^.]+$/, '') + '_trimmed.ogg';

  try {
    // Detect silence threshold
    const probeOutput = execFileSync('ffprobe', [
      '-i', audioPath,
      '-af', 'silencedetect=noise=-50dB:d=0.5',
      '-f', 'null',
      '-',
    ], { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] });

    // Parse silence end time from stderr
    const silenceEndMatch = /silence_end: ([\d.]+)/.exec(probeOutput);
    if (silenceEndMatch) {
      const endTime = parseFloat(silenceEndMatch[1]);

      // Trim to silence end
      execFileSync('ffmpeg', [
        '-y', '-i', audioPath,
        '-t', String(endTime),
        '-c:a', 'libopus',
        '-b:a', '64k',
        outputPath,
      ], { stdio: 'pipe', timeout: 30_000 });

      if (fs.existsSync(outputPath) && fs.statSync(outputPath).size > 0) {
        return outputPath;
      }
    }
  } catch (e) {
    log.warn(`Trim failed: ${e}`);
  }

  return audioPath;
}
```

**Purpose:** Remove trailing silence from ambient audio.

**Method:**
1. Use ffprobe to detect silence end time
2. Use ffmpeg to trim to silence end
3. Convert to OGG Opus

## generateAmbientLoop

```typescript
export async function generateAmbientLoop(agentName: string): Promise<string | null> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const manifest = loadAgentManifest(agentName);
  const displayName = manifest.display_name || agentName;

  // Generate ambient audio text
  const ambientText = `This is ${displayName}'s ambient presence. A quiet, steady awareness. Always here, always listening.`;

  // Synthesize via ElevenLabs
  const audioPath = await synthesiseSync(ambientText);
  if (!audioPath) {
    log.warn('TTS synthesis failed');
    return null;
  }

  // Trim static tails
  const trimmedPath = trimStaticTails(audioPath);
  const finalPath = trimmedPath !== audioPath ? trimmedPath : audioPath;

  // Move to audio directory
  const audioDir = audioDir(agentName);
  fs.mkdirSync(audioDir, { recursive: true });
  const destPath = path.join(audioDir, 'ambient_loop.ogg');
  fs.copyFileSync(finalPath, destPath);

  // Cleanup temp files
  cleanupFiles([audioPath, trimmedPath]);

  log.info(`Ambient loop saved to ${destPath}`);
  return destPath;
}
```

**Flow:**
1. Generate ambient presence text
2. Synthesize via ElevenLabs TTS
3. Trim trailing silence
4. Save to `avatar/audio/ambient_loop.ogg`

## runFullAvatarPipeline

```typescript
export async function runFullAvatarPipeline(agentName: string): Promise<{
  facePaths: string[];
  ambientPath: string | null;
}> {
  log.info(`Starting full avatar pipeline for ${agentName}`);

  // Generate face candidates
  const facePaths = await generateFace(agentName, 3);
  log.info(`Generated ${facePaths.length} face candidates`);

  // Generate ambient loop
  const ambientPath = await generateAmbientLoop(agentName);

  return { facePaths, ambientPath };
}
```

**Purpose:** Run complete avatar generation pipeline.

**Returns:**
- `facePaths`: Array of generated face candidate paths
- `ambientPath`: Path to ambient audio loop

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifest with appearance spec |
| `~/.atrophy/agents/<name>/avatar/Reference/` | Reference images for IP-Adapter |
| `~/.atrophy/agents/<name>/avatar/candidates/` | Generated face candidates |
| `~/.atrophy/agents/<name>/avatar/audio/ambient_loop.ogg` | Ambient audio loop |
| `/tmp/atrophy-tts-*.mp3` | Temp TTS audio |
| `/tmp/atrophy-voice-*.ogg` | Temp OGG audio |

## Exported API

| Function | Purpose |
|----------|---------|
| `generateFace(agentName, perRef)` | Generate face candidates via Fal AI |
| `generateAmbientLoop(agentName)` | Generate ambient audio loop |
| `trimStaticTails(audioPath)` | Remove trailing silence |
| `runFullAvatarPipeline(agentName)` | Run complete pipeline |
| `loadAgentManifest(agentName)` | Load agent manifest |
| `getFalKey()` | Get Fal API key |
| `getReferenceImages(agentName)` | Get reference images |
| `uploadToFal(imagePath)` | Upload image to Fal CDN |
| `downloadImage(url, destPath)` | Download image from URL |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/tts.ts` - TTS synthesis
- `src/main/audio-convert.ts` - Audio conversion utilities

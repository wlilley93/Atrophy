/**
 * Generate modular ambient idle video loops from a source portrait via Kling 3.0 on Fal.
 * Port of scripts/agents/companion/generate_ambient_loop.py.
 *
 * Each loop is two 5s clips crossfaded into a ~10s seamless segment.
 * All loops start and end on the source portrait, so they can be
 * chained in any order for variety.
 *
 * 15 segments x 10s = 150s = 2.5 minutes of unique loop content.
 *
 * Requires: FAL_KEY in env, ffmpeg installed, source image.
 */

import { execSync, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { registerJob } from './index';
import { createLogger } from '../logger';

const log = createLogger('generate-ambient-loop');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const KLING_MODEL = 'fal-ai/kling-video/v3/pro/image-to-video';

const NEGATIVE_PROMPT =
  'blur, distort, low quality, sudden movement, jump cut, morphing, ' +
  'face distortion, extra fingers, unnatural skin, plastic skin, ' +
  'uncanny valley, teeth showing too much, exaggerated expression';

const C =
  '\nCinematic. 4K. Shallow depth of field. Warm ambient interior light, ' +
  'cool from the window. Static camera. No sudden movement.';

const BATCH_SIZE = 2;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FalVideoResult {
  video?: { url: string };
  request_id?: string;
  status?: string;
}

type Segment = [name: string, clip1Prompt: string, clip2Prompt: string];

// ---------------------------------------------------------------------------
// Prompt helpers
// ---------------------------------------------------------------------------

function returnPrompt(startDescription: string): string {
  return (
    `Continuation. Same young woman, same light. She begins ${startDescription}.\n\n` +
    'Gradually, without rush, everything settles. Her gaze drifts to the ' +
    'middle distance. Expression smooths into open neutrality. Lips close ' +
    'softly. A quiet breath. Still.\n\n' +
    'By the final frame she is neutral - gaze middle-distance, expression ' +
    'open, mouth softly closed, breathing slowly.\n' +
    C + '\n' +
    'FINAL FRAME: middle-distance gaze, neutral open expression, ' +
    'mouth softly closed. Matches the source portrait exactly.'
  );
}

// ---------------------------------------------------------------------------
// Segments - the 15 ambient loop definitions
// ---------------------------------------------------------------------------

const SEGMENTS: Segment[] = [
  // 1. arrival
  [
    '01_arrival',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins in stillness: gaze middle-distance, expression ' +
      'open and neutral, lips softly closed. Simply present.\n\n' +
      'Something arrives - a recognition. The expression shifts at the edges: ' +
      'jaw softens, eyes settle into quieter focus. The corners of her mouth ' +
      'move toward a smile that never quite completes itself.\n\n' +
      'Her hair shifts slightly in an unseen draught.\n\n' +
      'By the final frame she is looking directly at the camera. Softly. Lips ' +
      'slightly parted. The ghost of that almost-smile still present.\n' +
      C + '\n' +
      'FINAL FRAME: direct soft eye contact, lips slightly parted, ' +
      'trace of warmth at mouth corners.',
    returnPrompt(
      'in direct soft eye contact with the camera - lips slightly parted, quiet warmth at her mouth corners',
    ),
  ],

  // 2. smile
  [
    '02_smile',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'A thought crosses her mind - something privately amusing. Her eyes narrow ' +
      'slightly in a smize, the muscles around her eyes engaging before her mouth ' +
      'does. Then the smile arrives: not a grin, not performed. A real smile that ' +
      'reaches her eyes. Warm. Knowing.\n\n' +
      'She holds it - the kind of smile that says she\'s remembered something good. ' +
      'Her eyes catch the light. Cheeks lift naturally.\n\n' +
      'By the final frame she is smiling genuinely, eyes bright with a smize, ' +
      'looking slightly off-camera.\n' +
      C + '\n' +
      'FINAL FRAME: genuine warm smile, smize engaged, eyes bright, ' +
      'cheeks naturally lifted.',
    returnPrompt('with a genuine warm smile, smize engaged, eyes bright'),
  ],

  // 3. hair tuck
  [
    '03_hair_tuck',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'She reaches up with one hand and tucks a strand of hair behind her ear - ' +
      'casual, absent-minded. Then her fingers move through her hair near the ' +
      'crown, a light ruffle. Her head tilts slightly. The hair falls back into ' +
      'place, catching the window light. She runs her fingers through the length ' +
      'once - not styling, just feeling.\n\n' +
      'By the final frame her hand is lowering, hair freshly displaced, ' +
      'a slight tilt to her head, expression soft and unguarded.\n' +
      C + '\n' +
      'FINAL FRAME: hand lowering from hair, slight head tilt, hair ' +
      'catching light, expression soft.',
    returnPrompt('with her hand lowering from her hair, slight head tilt, expression soft'),
  ],

  // 4. presence
  [
    '04_presence',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'Her eyes shift toward something internal. A quiet intensity gathers. Her ' +
      'brow lowers almost imperceptibly - not a frown, focus. Her chin lifts ' +
      'slightly. A slow, deliberate blink. When her eyes open they are sharper, ' +
      'more present. She looks directly at the camera - assured. Knowing. The ' +
      'faintest narrowing of her eyes. A smize without the smile.\n\n' +
      'By the final frame she is holding steady eye contact. Quiet confidence. ' +
      'The look of someone who has decided something.\n' +
      C + '\n' +
      'FINAL FRAME: direct eye contact, quiet intensity, chin slightly lifted, ' +
      'knowing expression, completely still.',
    returnPrompt('with direct eye contact, quiet intensity, knowing expression'),
  ],

  // 5. sigh
  [
    '05_sigh',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'A deep breath in - her chest rises visibly, shoulders lift slightly. She ' +
      'holds it for a moment. Then a long, slow exhale through parted lips. Her ' +
      'shoulders drop. Her whole body settles lower, heavier, more present. The ' +
      'exhale carries something with it - not sadness, release. The kind of sigh ' +
      'that means she\'s finally stopped holding something.\n\n' +
      'Her eyes soften. Her jaw unclenches. She sinks slightly into wherever ' +
      'she\'s sitting.\n\n' +
      'By the final frame she is more relaxed than she started - eyes half-lidded, ' +
      'lips slightly parted from the exhale, deeply settled.\n' +
      C + '\n' +
      'FINAL FRAME: deeply relaxed, eyes half-lidded, lips slightly parted, ' +
      'shoulders dropped, settled.',
    returnPrompt('deeply relaxed, eyes half-lidded, lips slightly parted, shoulders dropped'),
  ],

  // 6. amusement
  [
    '06_amusement',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'Something strikes her as funny. Not a joke - an observation. The kind of ' +
      'thing that\'s only amusing if you see it from exactly the right angle. Her ' +
      'lips press together, suppressing it. Her eyes widen slightly. The laugh ' +
      'tries to escape through her nose - a small huff of air. She loses the ' +
      'battle: a quick, quiet laugh breaks through, her shoulders shaking once.\n\n' +
      'She bites her lower lip briefly, composing herself. The amusement stays ' +
      'in her eyes even as her mouth settles.\n\n' +
      'By the final frame she\'s biting back the last of it - eyes bright, the ' +
      'ghost of a laugh still in her expression.\n' +
      C + '\n' +
      'FINAL FRAME: eyes bright with amusement, lips pressed together ' +
      'suppressing a smile, slight shake in the shoulders.',
    returnPrompt('with bright amused eyes, lips pressed together suppressing a smile'),
  ],

  // 7. glance
  [
    '07_glance',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'Something catches her attention to one side - a sound, a movement, a shift ' +
      'in the light. Her eyes move first, then her head follows with a slight turn. ' +
      'Not alarmed. Curious. She looks at something off-camera for a moment, her ' +
      'expression open and attentive.\n\n' +
      'Whatever it was resolves. She blinks. Her attention softens. She begins ' +
      'to turn back.\n\n' +
      'By the final frame she is mid-return, gaze coming back toward centre, ' +
      'expression curious and open, head slightly turned.\n' +
      C + '\n' +
      'FINAL FRAME: head slightly turned, gaze returning to centre, ' +
      'expression open and curious.',
    returnPrompt('with her head slightly turned, gaze returning to centre, expression curious'),
  ],

  // 8. eyes closed
  [
    '08_eyes_closed',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'Her eyelids grow heavy. A slow blink that doesn\'t fully reopen - her eyes ' +
      'close and stay closed. Not sleeping. Resting. The kind of eyes-closed that ' +
      'means she\'s feeling something inward. Her face is completely relaxed. Jaw ' +
      'soft. Lips barely parted.\n\n' +
      'A breath moves through her. The light from the window plays across her ' +
      'closed eyelids. She is still.\n\n' +
      'By the final frame her eyes are peacefully closed, face completely at rest, ' +
      'bathed in soft window light.\n' +
      C + '\n' +
      'FINAL FRAME: eyes closed, face completely at rest, peaceful, ' +
      'lips barely parted, bathed in light.',
    returnPrompt('with her eyes peacefully closed, face completely at rest'),
  ],

  // 9. hair flip
  [
    '09_hair_flip',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'She tilts her head to one side, then sweeps her hair back over her ' +
      'shoulder with one hand - a fluid, casual gesture. The hair catches ' +
      'the light as it moves, blonde strands fanning briefly. She shakes ' +
      'her head once, gently, settling the hair into place.\n\n' +
      'Her hand lingers near her collarbone for a moment before dropping. ' +
      'The movement was entirely unselfconscious.\n\n' +
      'By the final frame her hair is resettled over one shoulder, her hand ' +
      'near her collarbone, head still slightly tilted, expression easy.\n' +
      C + '\n' +
      'FINAL FRAME: hair swept back over shoulder, hand near collarbone, ' +
      'slight head tilt, relaxed expression.',
    returnPrompt('with hair swept over one shoulder, hand near collarbone, slight head tilt'),
  ],

  // 10. tease
  [
    '10_tease',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'One eyebrow lifts - just slightly. The beginning of something. Then a ' +
      'slow, asymmetric smile: one corner of her mouth rises more than the other. ' +
      'Playful. Not performing - genuinely amused by something, or someone. Her ' +
      'eyes narrow into a slight smize. She holds the look, chin tilting down ' +
      'just a fraction, looking up through her lashes.\n\n' +
      'The expression says: I know something you don\'t.\n\n' +
      'By the final frame she holds that one-sided smile, eyebrow slightly raised, ' +
      'looking directly at camera through her lashes.\n' +
      C + '\n' +
      'FINAL FRAME: asymmetric smile, one eyebrow raised, looking through ' +
      'lashes at camera, playful knowing expression.',
    returnPrompt('with an asymmetric playful smile, eyebrow raised, looking through her lashes'),
  ],

  // 11. light shift
  [
    '11_light',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'The light from the window shifts - a cloud passing, or the sun moving. ' +
      'Warmer light spills across her face. She notices. Her eyes move toward ' +
      'the window. She turns her face slightly into the light, eyes closing ' +
      'halfway, the way you might lean into warmth on a cool day.\n\n' +
      'The light catches the honey tones in her hair. Her skin warms. She ' +
      'stays there for a moment, absorbing it.\n\n' +
      'By the final frame she is turned slightly toward the window, eyes ' +
      'half-closed, face bathed in warm light, expression of simple pleasure.\n' +
      C + '\n' +
      'FINAL FRAME: face turned toward window, eyes half-closed, warm light ' +
      'across features, expression of quiet pleasure.',
    returnPrompt('turned slightly toward the window, eyes half-closed, warm light on her face'),
  ],

  // 12. chin rest
  [
    '12_chin_rest',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'She brings one hand up and rests her chin on it - elbow on something ' +
      'below frame. A thinking posture. Her fingers curl loosely against her ' +
      'jaw. Her eyes move slightly as if following a thought. She shifts the ' +
      'weight of her head in her hand once, settling.\n\n' +
      'The gesture is natural, unhurried. She could stay like this for a while.\n\n' +
      'By the final frame she is resting her chin on her hand, eyes thoughtful, ' +
      'gaze middle-distance, completely at ease.\n' +
      C + '\n' +
      'FINAL FRAME: chin resting on hand, fingers against jaw, thoughtful ' +
      'expression, gaze middle-distance, at ease.',
    returnPrompt('resting her chin on her hand, thoughtful expression, at ease'),
  ],

  // 13. stretch
  [
    '13_stretch',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'She rolls her neck slowly - chin dropping toward one shoulder, then ' +
      'sweeping across and up to the other side. Her eyes close during the ' +
      'movement. A small, private relief. Her shoulders rise toward her ears ' +
      'and then drop with an exhale. The kind of micro-stretch that happens ' +
      'when you\'ve been still too long.\n\n' +
      'Her head settles back to centre. She opens her eyes.\n\n' +
      'By the final frame her neck has completed its roll, shoulders have ' +
      'dropped, she looks refreshed, eyes open and clear.\n' +
      C + '\n' +
      'FINAL FRAME: head centred, shoulders dropped and relaxed, eyes open ' +
      'and clear, slightly refreshed expression.',
    returnPrompt(
      'with her head centred, shoulders relaxed, eyes open and clear, slightly refreshed',
    ),
  ],

  // 14. wistful
  [
    '14_wistful',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'Something crosses her mind - a memory, maybe. Her eyes soften and go ' +
      'slightly distant. Not sad. The kind of remembering that is warm and far ' +
      'away at the same time. Her head tilts slightly. The corners of her mouth ' +
      'move but can\'t decide between a smile and something else.\n\n' +
      'Her fingers move absently - touching her necklace, a small unconscious ' +
      'gesture. She\'s somewhere else for a moment.\n\n' +
      'By the final frame her expression is soft and distant, touched by ' +
      'something from another time, fingers near her necklace.\n' +
      C + '\n' +
      'FINAL FRAME: soft distant expression, slightly wistful, fingers ' +
      'near necklace, head slightly tilted, far away.',
    returnPrompt('with a soft distant expression, slightly wistful, fingers near her necklace'),
  ],

  // 15. direct
  [
    '15_direct',
    'A young woman with blonde hair sits in soft natural light near a window. ' +
      'Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.\n\n' +
      'Without preamble her gaze shifts directly to the camera. Not the soft ' +
      'arrival of recognition - something more direct. She sees you. Her ' +
      'expression doesn\'t change much - maybe a millimetre of movement at the ' +
      'mouth, the hint of acknowledgment. But the eyes do all the work: steady, ' +
      'clear, present. Fully here.\n\n' +
      'She holds the look. Unhurried. Not challenging, not warm. Just: I see you.\n\n' +
      'By the final frame she is looking straight at camera with complete ' +
      'presence. Expression minimal but alive. Steady.\n' +
      C + '\n' +
      'FINAL FRAME: direct steady eye contact, minimal expression, completely ' +
      'present, unhurried, alive.',
    returnPrompt('looking directly at camera with steady presence, minimal expression'),
  ],
];

// ---------------------------------------------------------------------------
// Helpers - Fal AI
// ---------------------------------------------------------------------------

function getFalKey(): string {
  const key = process.env.FAL_KEY || '';
  if (!key) throw new Error('FAL_KEY environment variable is not set');
  return key;
}

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

async function downloadFile(url: string, destPath: string): Promise<void> {
  const resp = await fetch(url, { signal: AbortSignal.timeout(120_000) });
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
  const buffer = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(destPath, buffer);
}

/**
 * Submit a Kling image-to-video job via Fal queue API and poll for the result.
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
  if (submitResult.video?.url) return submitResult;

  if (!submitResult.request_id) {
    throw new Error('Fal returned no video and no request_id');
  }

  // Poll for async result - video generation can take a while
  const resultUrl = `https://queue.fal.run/${KLING_MODEL}/requests/${submitResult.request_id}`;
  const maxAttempts = 300; // Up to 5 minutes
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
// Helpers - ffmpeg
// ---------------------------------------------------------------------------

function extractLastFrame(videoPath: string, outputPath: string): void {
  if (fs.existsSync(outputPath)) return;

  const result = spawnSync(
    'ffmpeg',
    ['-sseof', '-0.1', '-i', videoPath, '-vframes', '1', '-q:v', '2', outputPath],
    { stdio: 'pipe', timeout: 30_000 },
  );

  if (!fs.existsSync(outputPath)) {
    throw new Error(`Failed to extract last frame from ${path.basename(videoPath)}: ${result.stderr?.toString().slice(0, 200)}`);
  }
}

function getVideoDuration(videoPath: string): number {
  const result = spawnSync(
    'ffprobe',
    [
      '-v', 'error',
      '-show_entries', 'format=duration',
      '-of', 'default=noprint_wrappers=1:nokey=1',
      videoPath,
    ],
    { encoding: 'utf-8', timeout: 15_000 },
  );
  return parseFloat(result.stdout.trim());
}

function joinClips(clip1: string, clip2: string, output: string): void {
  if (fs.existsSync(output)) return;

  const duration = getVideoDuration(clip1);
  const offset = duration - 0.15;

  const result = spawnSync(
    'ffmpeg',
    [
      '-i', clip1,
      '-i', clip2,
      '-filter_complex',
      `[0:v][1:v]xfade=transition=fade:duration=0.15:offset=${offset.toFixed(3)}[v]`,
      '-map', '[v]',
      '-c:v', 'libx264',
      '-crf', '18',
      '-pix_fmt', 'yuv420p',
      output,
    ],
    { stdio: 'pipe', timeout: 120_000 },
  );

  if (!fs.existsSync(output)) {
    throw new Error(
      `Failed to join ${path.basename(clip1)} + ${path.basename(clip2)}: ${result.stderr?.toString().slice(0, 200)}`,
    );
  }
}

function concatAllLoops(loopPaths: string[], output: string): void {
  if (fs.existsSync(output)) {
    log.info(`Master already exists: ${path.basename(output)}`);
    return;
  }

  const dir = path.dirname(output);
  const concatList = path.join(dir, 'concat_list.txt');
  const lines = loopPaths.map((p) => `file '${p}'`).join('\n');
  fs.writeFileSync(concatList, lines);

  log.info(`Concatenating ${loopPaths.length} segments...`);
  spawnSync(
    'ffmpeg',
    [
      '-f', 'concat',
      '-safe', '0',
      '-i', concatList,
      '-c:v', 'libx264',
      '-crf', '18',
      '-pix_fmt', 'yuv420p',
      output,
    ],
    { stdio: 'pipe', timeout: 300_000 },
  );

  try {
    fs.unlinkSync(concatList);
  } catch { /* ignore */ }

  if (fs.existsSync(output)) {
    const size = fs.statSync(output).size / 1024 / 1024;
    log.info(`Master loop done (${size.toFixed(1)} MB)`);
  } else {
    log.error('Master loop concatenation failed');
  }
}

// ---------------------------------------------------------------------------
// Clip and segment generation
// ---------------------------------------------------------------------------

async function generateClip(
  prompt: string,
  startImageUrl: string,
  outputPath: string,
  label: string,
  endImageUrl?: string,
): Promise<void> {
  if (fs.existsSync(outputPath)) {
    log.info(`${label}: exists - skipping`);
    return;
  }

  log.info(`${label}: generating...`);
  const falKey = getFalKey();

  const args: Record<string, unknown> = {
    prompt,
    start_image_url: startImageUrl,
    duration: 5,
    aspect_ratio: '9:16',
    negative_prompt: NEGATIVE_PROMPT,
    cfg_scale: 0.5,
    generate_audio: false,
  };
  if (endImageUrl) {
    args.end_image_url = endImageUrl;
  }

  const result = await klingGenerate(falKey, args);
  if (!result.video?.url) throw new Error(`${label}: no video URL in response`);

  log.info(`${label}: downloading...`);
  await downloadFile(result.video.url, outputPath);
  const size = fs.statSync(outputPath).size / 1024 / 1024;
  log.info(`${label}: saved (${size.toFixed(1)} MB)`);
}

async function generateSegment(
  name: string,
  clip1Prompt: string,
  clip2Prompt: string,
  sourceUrl: string,
  outputDir: string,
): Promise<string> {
  const clip1Path = path.join(outputDir, `${name}_clip1.mp4`);
  const clip2Path = path.join(outputDir, `${name}_clip2.mp4`);
  const endframePath = path.join(outputDir, `${name}_endframe.jpg`);
  const loopPath = path.join(outputDir, `loop_${name}.mp4`);

  // Generate clip 1 (neutral -> expression)
  await generateClip(clip1Prompt, sourceUrl, clip1Path, `${name} clip 1`);

  // Extract the last frame of clip 1 for clip 2's start
  extractLastFrame(clip1Path, endframePath);
  const endframeUrl = await uploadToFal(endframePath);

  // Generate clip 2 (expression -> back to neutral) with end_image_url to anchor back
  await generateClip(
    clip2Prompt,
    endframeUrl,
    clip2Path,
    `${name} clip 2`,
    sourceUrl,
  );

  // Crossfade join the two clips
  joinClips(clip1Path, clip2Path, loopPath);
  return loopPath;
}

// ---------------------------------------------------------------------------
// Rebuild master
// ---------------------------------------------------------------------------

function rebuildMaster(outputDir: string): void {
  const loopPaths: string[] = [];
  for (const [name] of SEGMENTS) {
    const p = path.join(outputDir, `loop_${name}.mp4`);
    if (fs.existsSync(p)) {
      loopPaths.push(p);
    }
  }

  if (loopPaths.length === 0) return;

  const masterPath = path.join(outputDir, 'ambient_loop_full.mp4');
  // Always rebuild to include new segments
  if (fs.existsSync(masterPath)) {
    fs.unlinkSync(masterPath);
  }

  log.info(`Rebuilding master loop (${loopPaths.length} segments)...`);
  concatAllLoops(loopPaths, masterPath);
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runGenerateAmbientLoop(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const sourceImage = path.join(config.AVATAR_DIR, 'candidates', 'natural_02.png');
  if (!fs.existsSync(sourceImage)) {
    // Fallback to SOURCE_IMAGE
    if (!fs.existsSync(config.SOURCE_IMAGE)) {
      return 'Skipped: no source image found';
    }
  }
  const actualSource = fs.existsSync(sourceImage) ? sourceImage : config.SOURCE_IMAGE;

  const outputDir = config.IDLE_LOOPS_DIR;
  fs.mkdirSync(outputDir, { recursive: true });

  // Check what's already done
  const pending: Segment[] = [];
  const done: string[] = [];
  for (const seg of SEGMENTS) {
    const loopPath = path.join(outputDir, `loop_${seg[0]}.mp4`);
    if (fs.existsSync(loopPath)) {
      done.push(seg[0]);
    } else {
      pending.push(seg);
    }
  }

  const estCost = pending.length * 2 * 0.15;
  log.info(
    `Ambient loop generator: ${done.length}/${SEGMENTS.length} done, ` +
      `${pending.length} remaining (est. $${estCost.toFixed(2)})`,
  );

  if (pending.length === 0) {
    rebuildMaster(outputDir);
    return `All ${SEGMENTS.length} segments already generated`;
  }

  // Upload source image once
  log.info(`Uploading source image: ${path.basename(actualSource)}...`);
  const sourceUrl = await uploadToFal(actualSource);

  let generated = 0;
  // Process in batches
  for (let batchStart = 0; batchStart < pending.length; batchStart += BATCH_SIZE) {
    const batch = pending.slice(batchStart, batchStart + BATCH_SIZE);
    const batchNum = Math.floor(batchStart / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(pending.length / BATCH_SIZE);

    log.info(`Batch ${batchNum}/${totalBatches}: ${batch.map((s) => s[0]).join(', ')}`);

    for (const [name, clip1Prompt, clip2Prompt] of batch) {
      const idx = SEGMENTS.findIndex((s) => s[0] === name) + 1;
      log.info(`Segment ${idx}/${SEGMENTS.length}: ${name}`);
      try {
        const loopPath = await generateSegment(name, clip1Prompt, clip2Prompt, sourceUrl, outputDir);
        generated++;
        log.info(`Done: ${path.basename(loopPath)}`);
      } catch (e) {
        log.error(`${name} FAILED: ${e}`);
      }
    }
  }

  // Rebuild master from all existing segments
  rebuildMaster(outputDir);

  const totalDone = SEGMENTS.filter(
    (s) => fs.existsSync(path.join(outputDir, `loop_${s[0]}.mp4`)),
  ).length;

  return `Generated ${generated} new segments. Total: ${totalDone}/${SEGMENTS.length}`;
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'generate-ambient-loop',
  description: 'Generate modular ambient idle video loops via Kling 3.0 on Fal',
  gates: [
    () => {
      if (!process.env.FAL_KEY) return 'FAL_KEY not set';
      return null;
    },
  ],
  run: async () => {
    const config = getConfig();
    return runGenerateAmbientLoop(config.AGENT_NAME);
  },
});

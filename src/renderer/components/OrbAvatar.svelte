<script lang="ts">
  import { onMount } from 'svelte';
  import { session } from '../stores/session.svelte';
  import { emotionalState } from '../stores/emotional-state.svelte';
  import { activeEmotion, EMOTIONS, getColourDirName } from '../stores/emotion-colours.svelte';
  import type { EmotionType } from '../stores/emotion-colours.svelte';
  import { agents } from '../stores/agents.svelte';

  interface Props {
    pip?: boolean;
    /** When true, play the agent's ambient video and skip emotion clips. */
    ambientMode?: boolean;
  }

  import { api } from '../api';

  let { pip = false, ambientMode = false }: Props = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);
  let videoSrc = $state('');
  let videoReady = $state(false);
  let videoError = $state(false);

  // All available loops for the current agent (for cycling)
  let allLoops = $state<string[]>([]);
  let currentLoopIndex = 0;

  // Track which agent + emotion the video is showing
  let loadedAgent = '';
  let loadedEmotion: string | null = null;

  // Whether we're currently showing the ambient video
  let showingAmbient = $state(false);

  // Monotonic counter to discard stale async results
  let loadGeneration = 0;

  // Avatar download state
  let downloading = $state(false);
  let downloadPercent = $state(0);

  // Fallback canvas
  let canvas = $state<HTMLCanvasElement | null>(null);
  let ctx: CanvasRenderingContext2D | null = null;
  let time = 0;
  let animFrame = 0;
  let canvasRunning = false;

  // Blend factor for smooth transition to/from emotion colours
  let blendFactor = 0;
  const BLEND_SPEED = 0.04;

  // ---------------------------------------------------------------------------
  // Video loading
  // ---------------------------------------------------------------------------

  /** Load the agent's ambient video (e.g. xan_ambient.mp4). */
  async function loadAmbient(generation: number) {
    if (!api?.getAvatarAmbientPath) return false;
    try {
      const filePath = await api.getAvatarAmbientPath();
      if (generation !== loadGeneration) return false;
      if (filePath) {
        const newSrc = `file://${filePath}`;
        if (newSrc !== videoSrc) {
          videoSrc = newSrc;
          videoReady = false;
        }
        videoError = false;
        showingAmbient = true;
        return true;
      }
    } catch {
      if (generation !== loadGeneration) return false;
    }
    return false;
  }

  async function loadVideo(generation: number, colour = 'blue', clip = 'idle_hover') {
    if (!api) return;
    try {
      const filePath = await api.getAvatarVideoPath(colour, clip);
      if (generation !== loadGeneration) return; // stale - agent switched during await
      if (filePath) {
        const newSrc = `file://${filePath}`;
        if (newSrc !== videoSrc) {
          videoSrc = newSrc;
          videoReady = false;
        }
        videoError = false;
        showingAmbient = false;
      } else {
        videoError = true;
      }
    } catch {
      if (generation !== loadGeneration) return;
      videoError = true;
    }
  }

  /** Fetch all available loops and load the first one. */
  async function loadAllLoops(generation: number) {
    if (!api?.listAvatarLoops) return;
    try {
      const loops: string[] = await api.listAvatarLoops();
      if (generation !== loadGeneration) return; // stale
      allLoops = loops;
      currentLoopIndex = 0;
      if (loops.length > 0) {
        const newSrc = `file://${loops[0]}`;
        if (newSrc !== videoSrc) {
          videoSrc = newSrc;
          videoReady = false;
        }
        videoError = false;
        showingAmbient = false;
      }
    } catch {
      // API unavailable or errored - loadAllLoops returns with allLoops empty,
      // caller will fall back to single-clip loadVideo
    }
  }

  /** When the current video ends, loop it. Emotion changes handle clip switching. */
  function onVideoEnded() {
    videoEl?.play().catch(() => {});
  }

  function onVideoCanPlay() {
    console.log('[OrbAvatar] video canplay', videoSrc.split('/').slice(-2).join('/'));
    videoReady = true;
    downloading = false;
    stopCanvas();
    videoEl?.play().catch((e) => console.warn('[OrbAvatar] play() rejected:', e));
  }

  function onVideoError() {
    const el = videoEl;
    const code = el?.error?.code;
    const msg = el?.error?.message;
    console.error('[OrbAvatar] video error', { src: videoSrc.split('/').slice(-2).join('/'), code, msg });
    videoError = true;
    startCanvas();
  }

  // ---------------------------------------------------------------------------
  // Canvas fallback (procedural orb)
  // ---------------------------------------------------------------------------

  function startCanvas() {
    if (canvasRunning || !canvas) return;
    const rect = canvas.getBoundingClientRect();
    // Defer if layout hasn't happened yet (zero-size on first mount)
    if (rect.width === 0 || rect.height === 0) {
      requestAnimationFrame(() => startCanvas());
      return;
    }
    ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx?.scale(dpr, dpr);
    canvasRunning = true;
    draw();
  }

  function stopCanvas() {
    canvasRunning = false;
    cancelAnimationFrame(animFrame);
    animFrame = 0;
  }

  function orbColor(): { h: number; s: number; l: number } {
    const conn = emotionalState.connection;
    const warm = emotionalState.warmth;
    const play = emotionalState.playfulness;
    const frust = emotionalState.frustration;

    let h = 220 + (warm - 0.5) * -40 + (play - 0.3) * 20;
    let s = 55 + conn * 25;
    let l = 25 + warm * 15;

    if (frust > 0.3) {
      h = h + (frust - 0.3) * 100;
      s = s + frust * 20;
    }

    // Blend toward active emotion colour when one is set
    const target = activeEmotion.type !== null ? 1 : 0;
    blendFactor += (target - blendFactor) * BLEND_SPEED;

    if (blendFactor > 0.01) {
      const ec = activeEmotion.colour;
      h = h + (ec.h - h) * blendFactor;
      s = s + (ec.s - s) * blendFactor;
      l = l + (ec.l - l) * blendFactor;
    }

    return { h, s, l };
  }

  function draw() {
    if (!canvasRunning || !ctx || !canvas) return;
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;

    ctx.clearRect(0, 0, w, h);

    const color = orbColor();
    const isThinking = session.inferenceState !== 'idle';

    const breathRate = isThinking ? 4.0 : 1.2;
    const breathAmp = isThinking ? 0.06 : 0.03;
    const breath = 1 + Math.sin(time * breathRate) * breathAmp;

    const baseR = Math.min(w, h) * 0.22;
    const r = baseR * breath;

    // Outer glow layers
    for (let i = 3; i >= 0; i--) {
      const glowR = r * (1 + i * 0.5);
      const alpha = 0.12 - i * 0.02;
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      grad.addColorStop(0, `hsla(${color.h}, ${color.s + 10}%, ${color.l + 15}%, ${alpha})`);
      grad.addColorStop(1, 'transparent');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();
    }

    // Core orb
    const coreGrad = ctx.createRadialGradient(cx - r * 0.2, cy - r * 0.2, 0, cx, cy, r);
    coreGrad.addColorStop(0, `hsla(${color.h}, ${color.s + 20}%, ${color.l + 30}%, 0.85)`);
    coreGrad.addColorStop(0.4, `hsla(${color.h}, ${color.s + 10}%, ${color.l + 10}%, 0.5)`);
    coreGrad.addColorStop(1, `hsla(${color.h}, ${color.s}%, ${color.l}%, 0.08)`);
    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();

    // Specular highlight
    const hlR = r * 0.45;
    const hlGrad = ctx.createRadialGradient(cx - r * 0.15, cy - r * 0.2, 0, cx - r * 0.15, cy - r * 0.2, hlR);
    hlGrad.addColorStop(0, `hsla(${color.h}, ${color.s}%, 95%, 0.25)`);
    hlGrad.addColorStop(1, 'transparent');
    ctx.fillStyle = hlGrad;
    ctx.beginPath();
    ctx.arc(cx - r * 0.15, cy - r * 0.2, hlR, 0, Math.PI * 2);
    ctx.fill();

    // Orbiting particles
    const particleCount = isThinking ? 12 : 6;
    for (let i = 0; i < particleCount; i++) {
      const angle = (time * 0.3 + i * (Math.PI * 2 / particleCount));
      const dist = r * (1.2 + Math.sin(time * 0.5 + i) * 0.4);
      const px = cx + Math.cos(angle) * dist;
      const py = cy + Math.sin(angle) * dist;
      const pAlpha = 0.18 + Math.sin(time + i * 2) * 0.08;
      const pR = 1.5 + Math.sin(time * 2 + i) * 0.8;

      ctx.fillStyle = `hsla(${color.h}, ${color.s + 10}%, ${color.l + 35}%, ${pAlpha})`;
      ctx.beginPath();
      ctx.arc(px, py, pR, 0, Math.PI * 2);
      ctx.fill();
    }

    time += 0.016;
    if (canvasRunning) animFrame = requestAnimationFrame(draw);
  }

  // ---------------------------------------------------------------------------
  // Reactivity: reload video on agent switch or ambient mode change
  // ---------------------------------------------------------------------------

  $effect(() => {
    const agent = agents.current;
    const wantAmbient = ambientMode;
    // Re-run when agent changes OR ambientMode toggles
    if (!agent) return;

    const agentChanged = agent !== loadedAgent;
    const modeChanged = wantAmbient !== showingAmbient;
    if (!agentChanged && !modeChanged) return;

    if (agentChanged) {
      loadedAgent = agent;
      loadedEmotion = null;
    }

    // Bump generation so in-flight loads from previous state are discarded
    const gen = ++loadGeneration;

    // Only reset video state when agent actually changes - mode changes
    // should transition smoothly without killing the current video
    if (agentChanged) {
      videoSrc = '';
      videoReady = false;
      videoError = false;
      allLoops = [];
      showingAmbient = false;
    }

    console.log('[OrbAvatar] effect: agent=%s ambient=%s agentChanged=%s modeChanged=%s', agent, wantAmbient, agentChanged, modeChanged);

    if (wantAmbient) {
      // Ambient mode: try to load the agent's ambient video
      loadAmbient(gen).then((loaded) => {
        if (gen !== loadGeneration) return;
        console.log('[OrbAvatar] ambient loaded=%s', loaded);
        if (!loaded) {
          // No ambient video - fall through to loops/canvas
          loadAllLoops(gen).then(() => {
            if (gen !== loadGeneration) return;
            console.log('[OrbAvatar] fallback loops=%d', allLoops.length);
            if (allLoops.length === 0) loadVideo(gen);
          });
        }
      });
    } else {
      // Emotion-driven mode: start with calm blue idle clip.
      // The emotion $effect handles switching to other colours/clips.
      loadVideo(gen, 'blue', 'idle_hover');
    }
  });

  // ---------------------------------------------------------------------------
  // Reactivity: switch video clip on emotion change (only in non-ambient mode)
  // ---------------------------------------------------------------------------

  $effect(() => {
    const emotion = activeEmotion.type;
    if (ambientMode) return; // Don't switch clips in ambient mode
    if (emotion === loadedEmotion) return;
    loadedEmotion = emotion;

    // Don't switch clips for mirror-style agents (flat ambient loops)
    if (allLoops.length > 0 && allLoops.some((l) => l.includes('ambient_loop'))) return;

    if (emotion) {
      const spec = EMOTIONS[emotion];
      if (spec) {
        const colourName = getColourDirName(emotion as EmotionType);
        loadVideo(loadGeneration, colourName, spec.clip);
      }
    } else {
      // Revert to default
      loadVideo(loadGeneration);
    }
  });

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMount(() => {
    const cleanups: (() => void)[] = [];

    // Listen for avatar download events - retry video load when complete
    if (api) {
      const c1 = api.onAvatarDownloadStart?.(() => {
        downloading = true;
        downloadPercent = 0;
      });
      if (c1) cleanups.push(c1);
      const c2 = api.onAvatarDownloadProgress?.((data: { percent: number }) => {
        downloadPercent = data.percent;
      });
      if (c2) cleanups.push(c2);
      const c3 = api.onAvatarDownloadComplete?.(() => {
        downloading = false;
        downloadPercent = 100;
        // Retry loading the video now that files are available
        videoError = false;
        const gen = loadGeneration;
        if (ambientMode) {
          loadAmbient(gen).then((loaded) => {
            if (gen !== loadGeneration) return;
            if (!loaded) {
              loadAllLoops(gen).then(() => {
                if (gen !== loadGeneration) return;
                if (allLoops.length === 0) loadVideo(gen);
              });
            }
          });
        } else {
          loadAllLoops(gen).then(() => {
            if (gen !== loadGeneration) return;
            if (allLoops.length === 0) loadVideo(gen);
          });
        }
      });
      if (c3) cleanups.push(c3);
      const c4 = api.onAvatarDownloadError?.(() => {
        downloading = false;
      });
      if (c4) cleanups.push(c4);
    }

    // Start canvas fallback immediately (hidden if video loads)
    if (!videoReady) {
      startCanvas();
    }

    return () => {
      stopCanvas();
      cleanups.forEach((fn) => fn());
    };
  });
</script>

<div class="orb-root" class:pip>
  <!-- Video layer (full-bleed, hidden until ready) -->
  {#if videoSrc && !videoError}
    <div class="video-drift" class:drifting={videoReady && !showingAmbient}>
      <video
        bind:this={videoEl}
        class="avatar-video"
        class:visible={videoReady}
        src={videoSrc}
        oncanplay={onVideoCanPlay}
        onerror={onVideoError}
        onended={onVideoEnded}
        loop={showingAmbient || allLoops.length <= 1}
        muted
        playsinline
        preload="auto"
      ></video>
    </div>
  {/if}

  <!-- Canvas fallback (shown when video not available) -->
  {#if !videoReady}
    <canvas
      bind:this={canvas}
      class="orb-canvas"
    ></canvas>
  {/if}

  <!-- Download progress overlay -->
  {#if downloading}
    <div class="download-overlay">
      <div class="download-label">downloading avatar</div>
      <div class="download-bar">
        <div class="download-fill" style="width: {downloadPercent}%"></div>
      </div>
      <div class="download-percent">{downloadPercent}%</div>
    </div>
  {/if}
</div>

<style>
  /* -- Root container - handles PIP transition -- */

  .orb-root {
    position: absolute;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    overflow: hidden;
    transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .orb-root.pip {
    position: fixed;
    inset: auto 16px 16px auto;
    width: 120px;
    height: 120px;
    border-radius: 16px;
    overflow: hidden;
    z-index: 50;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  /* -- Ken Burns drift wrapper (disabled for ambient video) -- */

  .video-drift {
    position: absolute;
    inset: -5%;
    width: 110%;
    height: 110%;
    z-index: 0;
  }

  .video-drift.drifting {
    animation: kenBurnsDrift 45s ease-in-out infinite alternate;
  }

  @keyframes kenBurnsDrift {
    0% {
      transform: scale(1.05) translate(0%, 0%);
    }
    25% {
      transform: scale(1.10) translate(-1.5%, 1%);
    }
    50% {
      transform: scale(1.15) translate(1%, -1.5%);
    }
    75% {
      transform: scale(1.08) translate(1.5%, 1.5%);
    }
    100% {
      transform: scale(1.12) translate(-1%, -0.5%);
    }
  }

  .avatar-video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    object-fit: contain;
    opacity: 0;
    transition: opacity 0.8s ease;
    mask-image: radial-gradient(ellipse 70% 65% at 50% 45%, black 40%, transparent 72%);
    -webkit-mask-image: radial-gradient(ellipse 70% 65% at 50% 45%, black 40%, transparent 72%);
  }

  .avatar-video.visible {
    opacity: 1;
  }

  .orb-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
  }

  .download-overlay {
    position: absolute;
    bottom: 120px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    pointer-events: none;
  }

  .download-label {
    font-family: var(--font-sans);
    font-size: 11px;
    letter-spacing: 1.5px;
    color: var(--text-dim);
    text-transform: lowercase;
  }

  .download-bar {
    width: 160px;
    height: 2px;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 1px;
    overflow: hidden;
  }

  .download-fill {
    height: 100%;
    background: rgba(100, 140, 255, 0.5);
    transition: width 0.4s ease;
  }

  .download-percent {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-dim);
  }
</style>

<script lang="ts">
  import { onMount } from 'svelte';
  import { session } from '../stores/session.svelte';
  import { emotionalState } from '../stores/emotional-state.svelte';
  import { activeEmotion } from '../stores/emotion-colours.svelte';

  const api = (window as any).atrophy;

  let videoEl = $state<HTMLVideoElement>(null!);
  let videoSrc = $state('');
  let videoReady = $state(false);
  let videoError = $state(false);

  // Avatar download state
  let downloading = $state(false);
  let downloadPercent = $state(0);

  // Fallback canvas
  let canvas = $state<HTMLCanvasElement>(null!);
  let ctx: CanvasRenderingContext2D | null = null;
  let time = 0;
  let animFrame = 0;

  // Blend factor for smooth transition to/from emotion colours
  let blendFactor = 0;
  const BLEND_SPEED = 0.04;

  // ---------------------------------------------------------------------------
  // Video loading
  // ---------------------------------------------------------------------------

  async function loadVideo(colour = 'blue', clip = 'bounce_playful') {
    if (!api) return;
    try {
      const filePath = await api.getAvatarVideoPath(colour, clip);
      if (filePath) {
        videoSrc = `file://${filePath}`;
        videoError = false;
      }
    } catch {
      videoError = true;
    }
  }

  function onVideoCanPlay() {
    videoReady = true;
    downloading = false;
    videoEl?.play().catch(() => {});
  }

  function onVideoError() {
    videoError = true;
  }

  // ---------------------------------------------------------------------------
  // Canvas fallback (procedural orb)
  // ---------------------------------------------------------------------------

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
    if (!ctx || !canvas) return;
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
    animFrame = requestAnimationFrame(draw);
  }

  function initCanvas() {
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx?.scale(dpr, dpr);
    draw();
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  onMount(() => {
    loadVideo();

    // Listen for avatar download events - retry video load when complete
    if (api) {
      api.onAvatarDownloadStart?.(() => {
        downloading = true;
        downloadPercent = 0;
      });
      api.onAvatarDownloadProgress?.((data: { percent: number }) => {
        downloadPercent = data.percent;
      });
      api.onAvatarDownloadComplete?.(() => {
        downloading = false;
        downloadPercent = 100;
        // Retry loading the video now that files are available
        videoError = false;
        loadVideo();
      });
      api.onAvatarDownloadError?.(() => {
        downloading = false;
      });
    }

    // Start canvas fallback immediately (hidden if video loads)
    if (!videoReady) {
      initCanvas();
    }

    return () => {
      cancelAnimationFrame(animFrame);
    };
  });
</script>

<!-- Video layer (full-bleed, hidden until ready) -->
{#if videoSrc && !videoError}
  <video
    bind:this={videoEl}
    class="avatar-video"
    class:visible={videoReady}
    src={videoSrc}
    oncanplay={onVideoCanPlay}
    onerror={onVideoError}
    loop
    muted
    playsinline
    preload="auto"
  ></video>
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

<style>
  .avatar-video {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
    object-fit: cover;
    opacity: 0;
    transition: opacity 0.8s ease;
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

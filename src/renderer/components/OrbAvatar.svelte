<script lang="ts">
  import { onMount } from 'svelte';
  import { session } from '../stores/session.svelte';
  import { emotionalState } from '../stores/emotional-state.svelte';
  import { activeEmotion } from '../stores/emotion-colours.svelte';

  const api = (window as any).atrophy;

  let videoEl: HTMLVideoElement;
  let videoSrc = $state('');
  let videoReady = $state(false);
  let videoError = $state(false);

  // Fallback canvas
  let canvas: HTMLCanvasElement;
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
      }
    } catch {
      videoError = true;
    }
  }

  function onVideoCanPlay() {
    videoReady = true;
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
    let s = 40 + conn * 30;
    let l = 15 + warm * 10;

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

    const baseR = Math.min(w, h) * 0.18;
    const r = baseR * breath;

    for (let i = 3; i >= 0; i--) {
      const glowR = r * (1 + i * 0.5);
      const alpha = 0.04 - i * 0.008;
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      grad.addColorStop(0, `hsla(${color.h}, ${color.s}%, ${color.l + 10}%, ${alpha})`);
      grad.addColorStop(1, 'transparent');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();
    }

    const coreGrad = ctx.createRadialGradient(cx - r * 0.2, cy - r * 0.2, 0, cx, cy, r);
    coreGrad.addColorStop(0, `hsla(${color.h}, ${color.s + 15}%, ${color.l + 20}%, 0.6)`);
    coreGrad.addColorStop(0.5, `hsla(${color.h}, ${color.s}%, ${color.l}%, 0.3)`);
    coreGrad.addColorStop(1, `hsla(${color.h}, ${color.s}%, ${color.l - 5}%, 0.05)`);
    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();

    const hlR = r * 0.4;
    const hlGrad = ctx.createRadialGradient(cx - r * 0.15, cy - r * 0.2, 0, cx - r * 0.15, cy - r * 0.2, hlR);
    hlGrad.addColorStop(0, `hsla(${color.h}, ${color.s}%, 90%, 0.12)`);
    hlGrad.addColorStop(1, 'transparent');
    ctx.fillStyle = hlGrad;
    ctx.beginPath();
    ctx.arc(cx - r * 0.15, cy - r * 0.2, hlR, 0, Math.PI * 2);
    ctx.fill();

    const particleCount = isThinking ? 12 : 5;
    for (let i = 0; i < particleCount; i++) {
      const angle = (time * 0.3 + i * (Math.PI * 2 / particleCount));
      const dist = r * (1.2 + Math.sin(time * 0.5 + i) * 0.4);
      const px = cx + Math.cos(angle) * dist;
      const py = cy + Math.sin(angle) * dist;
      const pAlpha = 0.08 + Math.sin(time + i * 2) * 0.04;
      const pR = 1 + Math.sin(time * 2 + i) * 0.5;

      ctx.fillStyle = `hsla(${color.h}, ${color.s}%, ${color.l + 30}%, ${pAlpha})`;
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
</style>

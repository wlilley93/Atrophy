<script lang="ts">
  import { session } from '../stores/session.svelte';
  import { emotionalState } from '../stores/emotional-state.svelte';
  import { onMount } from 'svelte';

  let canvas: HTMLCanvasElement;
  let ctx: CanvasRenderingContext2D | null = null;
  let time = 0;
  let animFrame = 0;

  // Orb colors driven by emotional state
  function orbColor(): { h: number; s: number; l: number } {
    const conn = emotionalState.connection;
    const warm = emotionalState.warmth;
    const play = emotionalState.playfulness;
    const frust = emotionalState.frustration;

    // Base hue: blue (220) shifting toward warm (200) or cool (240)
    let h = 220 + (warm - 0.5) * -40 + (play - 0.3) * 20;
    let s = 40 + conn * 30;
    let l = 15 + warm * 10;

    // Frustration shifts toward red
    if (frust > 0.3) {
      h = h + (frust - 0.3) * 100;
      s = s + frust * 20;
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

    // Breathing scale
    const breathRate = isThinking ? 4.0 : 1.2;
    const breathAmp = isThinking ? 0.06 : 0.03;
    const breath = 1 + Math.sin(time * breathRate) * breathAmp;

    // Base radius
    const baseR = Math.min(w, h) * 0.18;
    const r = baseR * breath;

    // Outer glow layers
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

    // Core orb with gradient
    const coreGrad = ctx.createRadialGradient(
      cx - r * 0.2, cy - r * 0.2, 0,
      cx, cy, r,
    );
    coreGrad.addColorStop(0, `hsla(${color.h}, ${color.s + 15}%, ${color.l + 20}%, 0.6)`);
    coreGrad.addColorStop(0.5, `hsla(${color.h}, ${color.s}%, ${color.l}%, 0.3)`);
    coreGrad.addColorStop(1, `hsla(${color.h}, ${color.s}%, ${color.l - 5}%, 0.05)`);
    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();

    // Inner highlight
    const hlR = r * 0.4;
    const hlGrad = ctx.createRadialGradient(
      cx - r * 0.15, cy - r * 0.2, 0,
      cx - r * 0.15, cy - r * 0.2, hlR,
    );
    hlGrad.addColorStop(0, `hsla(${color.h}, ${color.s}%, 90%, 0.12)`);
    hlGrad.addColorStop(1, 'transparent');
    ctx.fillStyle = hlGrad;
    ctx.beginPath();
    ctx.arc(cx - r * 0.15, cy - r * 0.2, hlR, 0, Math.PI * 2);
    ctx.fill();

    // Drift particles (subtle)
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

  onMount(() => {
    ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx?.scale(dpr, dpr);
    draw();

    return () => cancelAnimationFrame(animFrame);
  });
</script>

<canvas
  bind:this={canvas}
  class="orb-canvas"
></canvas>

<style>
  .orb-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
  }
</style>

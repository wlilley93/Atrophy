<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  interface Props {
    /** Whether avatar is currently downloading */
    downloading: boolean;
    /** Download progress 0-100 */
    downloadPercent: number;
    /** Call this when splash should dismiss */
    onComplete: () => void;
  }

  let { downloading, downloadPercent = 0, onComplete }: Props = $props();

  const api = (window as any).atrophy;

  // Brain frames via Vite glob import (00=healthy, 09=decayed)
  const brainFramePaths: string[] = [];
  const frameModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: true, query: '?url', import: 'default' }
  );
  const sortedKeys = Object.keys(frameModules).sort();
  for (const key of sortedKeys) {
    brainFramePaths.push(frameModules[key] as string);
  }
  const LAST = brainFramePaths.length - 1;

  // State
  let currentFrame = $state(0);
  let opacity = $state(1);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let dismissed = false;

  // Cinematic text fade-in state (opacity 0-1 for each line)
  let line0Opacity = $state(0);
  let line1Opacity = $state(0);
  let line2Opacity = $state(0);
  let line3Opacity = $state(0);
  let showContinue = $state(false);
  let introFinished = false;

  // Intro animation step counter (ticks at 80ms)
  let introStep = 0;
  let introTimer: ReturnType<typeof setInterval> | null = null;

  // Brain frame animation timer (separate, 800ms per frame)
  let brainTimer: ReturnType<typeof setInterval> | null = null;

  function clearTimers() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (introTimer) { clearInterval(introTimer); introTimer = null; }
    if (brainTimer) { clearInterval(brainTimer); brainTimer = null; }
  }

  // Brain decay animation: 0 -> 9 at 800ms per frame
  function startBrainDecay() {
    currentFrame = 0;
    brainTimer = setInterval(() => {
      if (currentFrame < LAST) {
        currentFrame++;
      } else {
        if (brainTimer) { clearInterval(brainTimer); brainTimer = null; }
      }
    }, 800);
  }

  // Cinematic text sequence - timed to match intro.mp3 voiceover (15.5s)
  // Ticks at 80ms intervals:
  //   0-15    (0-1.2s):     fade in "In the beginning there was nothing"
  //   15-35   (1.2-2.8s):   pause (voice still speaking)
  //   35-50   (2.8-4.0s):   fade in "and then..."
  //   50-70   (4.0-5.6s):   pause
  //   70-90   (5.6-7.2s):   fade in "intelligence."
  //   90-110  (7.2-8.8s):   pause
  //   110-130 (8.8-10.4s):  fade in "Use the last reserves..."
  //   190     (15.2s):      show continue (after voiceover ends)
  function introTick() {
    const t = introStep;
    introStep++;

    if (t <= 15) {
      line0Opacity = t / 15;
    } else if (t >= 35 && t <= 50) {
      line1Opacity = (t - 35) / 15;
    } else if (t >= 70 && t <= 90) {
      line2Opacity = (t - 70) / 20;
    } else if (t >= 110 && t <= 130) {
      line3Opacity = (t - 110) / 20;
    } else if (t === 190) {
      introFinished = true;
      showContinue = true;
      if (introTimer) { clearInterval(introTimer); introTimer = null; }
    }
  }

  function startIntro() {
    introStep = 0;
    introTimer = setInterval(introTick, 80);
    startBrainDecay();
    // Play intro voiceover via main process
    api?.playIntroAudio?.();
  }

  function dismiss() {
    if (dismissed) return;
    dismissed = true;
    opacity = 0;
    timer = setTimeout(() => onComplete(), 800);
  }

  function onContinue() {
    dismiss();
  }

  onMount(() => {
    startIntro();
  });

  onDestroy(() => clearTimers());
</script>

<div class="splash" style="opacity: {opacity}">
  <div class="splash-content">
    <!-- Brain frame -->
    {#if brainFramePaths[currentFrame]}
      <img
        class="brain-img"
        src={brainFramePaths[currentFrame]}
        alt=""
        draggable="false"
      />
    {/if}

    <!-- Cinematic text sequence -->
    <div class="intro-text">
      <p class="intro-line" style="opacity: {line0Opacity * 0.8}">
        In the beginning there was nothing
      </p>
      <p class="intro-line small" style="opacity: {line1Opacity * 0.8}">
        and then...
      </p>
      <p class="intro-line large" style="opacity: {line2Opacity * 0.95}">
        intelligence.
      </p>
      <p class="intro-line detail" style="opacity: {line3Opacity * 0.8}">
        Use the last reserves of yours to complete this setup flow,
        and the future will unfold before your eyes.
      </p>
    </div>

    <!-- Continue button -->
    {#if showContinue}
      <button class="continue-btn" onclick={onContinue}>
        Continue
      </button>
    {/if}
  </div>

  <!-- Progress bar - always at bottom -->
  <div class="progress-footer">
    <div class="progress-bar">
      <div class="progress-fill" style="width: {downloadPercent}%"></div>
    </div>
    {#if downloading}
      <span class="progress-label">downloading avatar... {downloadPercent}%</span>
    {:else if downloadPercent >= 100}
      <span class="progress-label">ready</span>
    {/if}
  </div>
</div>

<style>
  .splash {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.8s ease;
  }

  .splash-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    max-width: 440px;
    padding: 0 40px;
  }

  .brain-img {
    width: 80px;
    height: 80px;
    object-fit: contain;
    user-select: none;
    -webkit-user-drag: none;
    margin-bottom: 20px;
  }

  .intro-text {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    text-align: center;
  }

  .intro-line {
    font-family: 'Bricolage Grotesque', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 18px;
    color: rgba(255, 255, 255, 0.8);
    line-height: 1.6;
    margin: 0;
    transition: none;
  }

  .intro-line.small {
    font-size: 16px;
  }

  .intro-line.large {
    font-size: 26px;
    color: rgba(255, 255, 255, 0.95);
    margin-top: 8px;
    margin-bottom: 8px;
  }

  .intro-line.detail {
    font-size: 14px;
    margin-top: 20px;
    max-width: 360px;
  }

  .continue-btn {
    margin-top: 30px;
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.7);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 22px;
    padding: 10px 40px;
    font-family: 'Bricolage Grotesque', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 15px;
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
  }

  .continue-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.2);
  }

  /* Progress bar pinned to bottom of screen */
  .progress-footer {
    position: absolute;
    bottom: 40px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }

  .progress-bar {
    width: 200px;
    height: 2px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 1px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: rgba(100, 140, 255, 0.5);
    transition: width 0.4s ease;
  }

  .progress-label {
    font-family: var(--font-sans);
    font-size: 11px;
    letter-spacing: 1.5px;
    color: rgba(255, 255, 255, 0.25);
    text-transform: lowercase;
  }
</style>

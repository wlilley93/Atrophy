<script lang="ts">
  import OrbAvatar from './OrbAvatar.svelte';
  import AgentName from './AgentName.svelte';
  import ThinkingIndicator from './ThinkingIndicator.svelte';
  import Transcript from './Transcript.svelte';
  import InputBar from './InputBar.svelte';
  import Timer from './Timer.svelte';
  import Canvas from './Canvas.svelte';
  import Artefact from './Artefact.svelte';
  import Settings from './Settings.svelte';
  import SetupWizard from './SetupWizard.svelte';
  import { session } from '../stores/session.svelte';
  import { audio } from '../stores/audio.svelte';
  import { agents } from '../stores/agents.svelte';
  import { settings } from '../stores/settings.svelte';
  import { addMessage, completeLast } from '../stores/transcript.svelte';

  const api = (window as any).atrophy;

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let showSettings = $state(false);
  let showTimer = $state(false);
  let showCanvas = $state(false);
  let showArtefact = $state(false);
  let needsSetup = $state(false);

  // Boot sequence
  let bootPhase = $state<'boot' | 'ready'>('boot');
  let bootOpacity = $state(1.0);
  let bootLabel = $state('connecting...');

  // Mode toggles
  let avatarVisible = $state(true);
  let isMuted = $state(false);
  let wakeListening = $state(false);
  let callActive = $state(false);
  let hasNewArtefacts = $state(false);

  // ---------------------------------------------------------------------------
  // Boot sequence
  // ---------------------------------------------------------------------------

  async function runBootSequence() {
    if (!api) { bootPhase = 'ready'; return; }

    // Check if setup needed
    try {
      needsSetup = await api.needsSetup();
    } catch { needsSetup = false; }

    if (needsSetup) {
      bootPhase = 'ready';
      return;
    }

    // Fetch opening line
    bootLabel = 'loading opening...';
    try {
      const opening = await api.getOpeningLine();
      if (opening) {
        addMessage('agent', opening);
        completeLast();
      }
    } catch { /* use default */ }

    // Fade out boot overlay
    bootLabel = '';
    bootOpacity = 0;
    await new Promise(r => setTimeout(r, 600));
    bootPhase = 'ready';
  }

  $effect(() => {
    if (settings.loaded) {
      runBootSequence();
    }
  });

  // ---------------------------------------------------------------------------
  // Agent cycling
  // ---------------------------------------------------------------------------

  async function cycleAgent(direction: number) {
    const list = agents.list;
    if (list.length < 2) return;
    const idx = list.indexOf(agents.current);
    const next = list[(idx + direction + list.length) % list.length];
    agents.switchDirection = direction;
    if (api) {
      const result = await api.switchAgent(next);
      agents.current = result.agentName;
      agents.displayName = result.agentDisplayName;
    }
  }

  // ---------------------------------------------------------------------------
  // Window controls
  // ---------------------------------------------------------------------------

  function minimizeWindow() { api?.minimizeWindow(); }
  function closeWindow() { api?.closeWindow(); }

  // ---------------------------------------------------------------------------
  // Mode button actions
  // ---------------------------------------------------------------------------

  function toggleAvatar() { avatarVisible = !avatarVisible; }

  function toggleMute() {
    isMuted = !isMuted;
    // TODO: wire to TTS mute in main process
  }

  function toggleWake() {
    wakeListening = !wakeListening;
    // TODO: wire to wake word start/stop
  }

  function toggleCall() {
    callActive = !callActive;
    // TODO: wire to voice call mode
  }

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------

  function onKeydown(e: KeyboardEvent) {
    // Cmd+Up/Down: cycle agents
    if (e.metaKey && e.key === 'ArrowUp') {
      e.preventDefault();
      cycleAgent(-1);
    } else if (e.metaKey && e.key === 'ArrowDown') {
      e.preventDefault();
      cycleAgent(1);
    }
    // Cmd+, : settings
    else if (e.metaKey && e.key === ',') {
      e.preventDefault();
      showSettings = !showSettings;
    }
    // Cmd+K : canvas
    else if (e.metaKey && e.key === 'k') {
      e.preventDefault();
      showCanvas = !showCanvas;
    }
    // Cmd+Shift+W : wake word
    else if (e.metaKey && e.shiftKey && e.key === 'W') {
      e.preventDefault();
      toggleWake();
    }
    // Escape: close overlays in priority order
    else if (e.key === 'Escape') {
      if (showSettings) showSettings = false;
      else if (showArtefact) showArtefact = false;
      else if (showCanvas) showCanvas = false;
      else if (showTimer) showTimer = false;
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="window">
  <!-- Background orb / avatar layer -->
  {#if avatarVisible}
    <OrbAvatar />
  {/if}

  <!-- Warm vignette overlay (shows during audio playback) -->
  <div
    class="vignette"
    style="opacity: {audio.vignetteOpacity}"
  ></div>

  <!-- Boot overlay (fades out after startup) -->
  {#if bootPhase === 'boot'}
    <div class="boot-overlay" style="opacity: {bootOpacity}">
      {#if bootLabel}
        <span class="boot-label">{bootLabel}</span>
      {/if}
    </div>
  {/if}

  <!-- Traffic light buttons (top-left) -->
  <div class="traffic-lights" data-no-drag>
    <button
      class="traffic-btn close"
      onclick={closeWindow}
      title="Close"
      aria-label="Close window"
    ></button>
    <button
      class="traffic-btn minimize"
      onclick={minimizeWindow}
      title="Minimize"
      aria-label="Minimize window"
    ></button>
    <button
      class="traffic-btn fullscreen"
      onclick={() => api?.toggleFullscreen()}
      title="Fullscreen"
      aria-label="Toggle fullscreen"
    ></button>
  </div>

  <!-- Top bar: agent name + thinking indicator -->
  <div class="top-bar">
    <AgentName
      name={agents.displayName}
      direction={agents.switchDirection}
      onCycleUp={() => cycleAgent(-1)}
      onCycleDown={() => cycleAgent(1)}
    />
    {#if session.inferenceState !== 'idle'}
      <ThinkingIndicator />
    {/if}
  </div>

  <!-- Mode buttons (top-right) -->
  <div class="mode-buttons" data-no-drag>
    <!-- Eye: toggle avatar -->
    <button
      class="mode-btn"
      class:active={!avatarVisible}
      onclick={toggleAvatar}
      title="Toggle avatar"
      aria-label="Toggle avatar"
    >
      {#if avatarVisible}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
          <line x1="1" y1="1" x2="23" y2="23"/>
        </svg>
      {/if}
    </button>

    <!-- Mute: toggle TTS -->
    <button
      class="mode-btn"
      class:active={isMuted}
      onclick={toggleMute}
      title="Mute / unmute voice"
      aria-label="Toggle mute"
    >
      {#if isMuted}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <line x1="23" y1="9" x2="17" y2="15"/>
          <line x1="17" y1="9" x2="23" y2="15"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
      {/if}
    </button>

    <!-- Minimize to tray -->
    <button class="mode-btn" onclick={minimizeWindow} title="Minimize" aria-label="Minimize">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
    </button>

    <!-- Wake word -->
    <button
      class="mode-btn"
      class:wake-active={wakeListening}
      onclick={toggleWake}
      title="Wake word listening"
      aria-label="Toggle wake word"
    >
      {#if wakeListening}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <line x1="1" y1="1" x2="23" y2="23"/>
          <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/>
          <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2c0 .76-.13 1.49-.36 2.18"/>
          <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      {/if}
    </button>

    <!-- Call (voice) -->
    <button
      class="mode-btn"
      class:active={callActive}
      onclick={toggleCall}
      title="Voice call"
      aria-label="Voice call"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
      </svg>
    </button>

    <!-- Artefact -->
    <button
      class="mode-btn artefact-btn"
      onclick={() => showArtefact = !showArtefact}
      title="Artefacts"
      aria-label="Artefacts"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
      {#if hasNewArtefacts}
        <span class="artefact-badge"></span>
      {/if}
    </button>

    <!-- Timer -->
    <button class="mode-btn" onclick={() => showTimer = !showTimer} title="Timer" aria-label="Timer">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    </button>

    <!-- Settings -->
    <button
      class="mode-btn"
      class:active={showSettings}
      onclick={() => showSettings = !showSettings}
      title="Settings"
      aria-label="Settings"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </button>
  </div>

  <!-- Chat area -->
  <Transcript />

  <!-- Input bar -->
  <InputBar />

  <!-- Overlays (conditionally rendered) -->
  {#if showTimer}
    <Timer onClose={() => showTimer = false} />
  {/if}

  {#if showCanvas}
    <Canvas onClose={() => showCanvas = false} />
  {/if}

  {#if showArtefact}
    <Artefact onClose={() => showArtefact = false} />
  {/if}

  {#if showSettings}
    <Settings onClose={() => showSettings = false} />
  {/if}

  <!-- Setup wizard (shown on first launch) -->
  {#if needsSetup}
    <SetupWizard />
  {/if}
</div>

<style>
  .window {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: var(--bg);
    display: flex;
    flex-direction: column;
  }

  .vignette {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    background: radial-gradient(
      ellipse at center,
      transparent 30%,
      rgba(40, 25, 10, 0.47) 100%
    );
    transition: opacity 0.8s ease;
  }

  /* ── Boot overlay ── */

  .boot-overlay {
    position: absolute;
    inset: 0;
    z-index: 80;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.6s ease;
    pointer-events: none;
  }

  .boot-label {
    font-family: var(--font-sans);
    font-size: 13px;
    letter-spacing: 2px;
    color: var(--text-dim);
    text-transform: lowercase;
  }

  /* ── Traffic lights ── */

  .traffic-lights {
    position: absolute;
    top: 14px;
    left: 14px;
    z-index: 15;
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .traffic-btn {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    transition: opacity 0.15s;
    opacity: 0.7;
  }

  .traffic-btn:hover {
    opacity: 1;
  }

  .traffic-btn.close {
    background: #ff5f57;
  }

  .traffic-btn.minimize {
    background: #febc2e;
  }

  .traffic-btn.fullscreen {
    background: #28c840;
  }

  /* Dim when window not focused (pure CSS via :not(:focus-within) on parent) */
  .window:not(:hover) .traffic-btn {
    opacity: 0.4;
  }

  /* ── Top bar ── */

  .top-bar {
    position: relative;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: var(--pad);
    padding-top: 36px;
    padding-bottom: 0;
  }

  /* ── Mode buttons ── */

  .mode-buttons {
    position: absolute;
    top: 36px;
    right: var(--pad);
    z-index: 10;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .mode-btn {
    width: var(--button-size);
    height: var(--button-size);
    border: none;
    background: transparent;
    color: var(--text-dim);
    border-radius: 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.2s, background 0.2s;
    position: relative;
  }

  .mode-btn:hover {
    color: var(--text-secondary);
    background: rgba(255, 255, 255, 0.04);
  }

  .mode-btn.active {
    color: var(--text-primary);
    background: rgba(40, 40, 50, 0.82);
  }

  .mode-btn.wake-active {
    color: rgba(120, 255, 140, 0.9);
    background: rgba(30, 80, 40, 0.82);
  }

  /* Artefact badge */
  .artefact-badge {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(100, 180, 255, 0.88);
  }
</style>

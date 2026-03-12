<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
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

  // Eye mode - hides transcript when active
  let eyeMode = $state(false);

  // Agent switch clip-path animation
  let agentSwitchActive = $state(false);
  let agentSwitchClip = $state('circle(0% at 50% 50%)');

  // Agent deferral (codec-style handoff)
  let deferralActive = $state(false);
  let deferralTarget = $state('');
  let deferralProgress = $state(0);

  // Silence timer - prompts after 5 minutes idle
  let lastInputTime = $state(Date.now());
  let silencePromptVisible = $state(false);
  let silenceTimerId: ReturnType<typeof setTimeout> | null = null;
  const SILENCE_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

  // ---------------------------------------------------------------------------
  // Boot sequence
  // ---------------------------------------------------------------------------

  let bootRan = false;

  async function runBootSequence() {
    if (bootRan) return;
    bootRan = true;

    if (!api) {
      bootPhase = 'ready';
      return;
    }

    // Load config and agent list
    try {
      const [cfg, agentList] = await Promise.all([
        api.getConfig(),
        api.getAgents(),
      ]);
      agents.current = cfg.agentName || '';
      agents.displayName = cfg.agentDisplayName || cfg.agentName || '';
      agents.list = agentList || [];
    } catch {
      // continue with defaults
    }

    // Check if setup needed
    try {
      needsSetup = await api.needsSetup();
    } catch {
      needsSetup = false;
    }

    if (needsSetup) {
      // Fade out boot overlay to reveal setup wizard
      bootOpacity = 0;
      await new Promise(r => setTimeout(r, 500));
      bootPhase = 'ready';
      return;
    }

    // Fetch opening line
    bootLabel = '';
    try {
      const opening = await api.getOpeningLine();
      if (opening) {
        addMessage('agent', opening);
        completeLast();
      }
    } catch {
      // use default
    }

    // Fade out boot overlay
    bootLabel = '';
    bootOpacity = 0;
    await new Promise(r => setTimeout(r, 1500));
    bootPhase = 'ready';
  }

  // ---------------------------------------------------------------------------
  // Silence timer
  // ---------------------------------------------------------------------------

  function resetSilenceTimer() {
    lastInputTime = Date.now();
    silencePromptVisible = false;

    if (silenceTimerId) clearTimeout(silenceTimerId);
    silenceTimerId = setTimeout(() => {
      silencePromptVisible = true;
    }, SILENCE_TIMEOUT_MS);
  }

  function dismissSilencePrompt() {
    silencePromptVisible = false;
    resetSilenceTimer();
  }

  // ---------------------------------------------------------------------------
  // Agent switch animation
  // ---------------------------------------------------------------------------

  function playAgentSwitchAnimation() {
    // No-op - clip-path eye blink removed per user preference
  }

  // ---------------------------------------------------------------------------
  // Agent deferral (codec-style handoff)
  // ---------------------------------------------------------------------------

  async function handleDeferralRequest(data: { target: string; context: string; user_question: string }) {
    if (deferralActive || !api) return;

    deferralActive = true;
    deferralTarget = data.target;

    // Stop any ongoing inference
    if (api.stopInference) {
      api.stopInference();
    }

    // Kill audio
    if (api.clearAudioQueue) {
      api.clearAudioQueue();
    }

    // Iris wipe animation (fast, codec-style)
    deferralProgress = 0;
    requestAnimationFrame(() => {
      deferralProgress = 1;
    });

    // At peak black - switch agent
    setTimeout(async () => {
      try {
        const result = await api.completeDeferral(data);
        agents.current = result.agentName;
        agents.displayName = result.agentDisplayName;
        deferralTarget = '';
        
        // Iris open animation
        deferralProgress = 2;
        setTimeout(() => {
          deferralActive = false;
          deferralProgress = 0;
        }, 300);
      } catch (err) {
        console.error('[deferral] failed:', err);
        deferralActive = false;
        deferralProgress = 0;
      }
    }, 250);
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  let agentSwitchCleanup: (() => void) | null = null;

  onMount(() => {
    runBootSequence();
    resetSilenceTimer();

    // Listen for deferral requests from main process
    if (api && typeof api.on === 'function') {
      api.on('deferral:request', handleDeferralRequest);

      // Auto-show canvas when content is written (even if Canvas not mounted yet)
      api.on('canvas:updated', () => {
        showCanvas = true;
      });
    }
  });

  onDestroy(() => {
    if (silenceTimerId) clearTimeout(silenceTimerId);
    if (agentSwitchCleanup) agentSwitchCleanup();
    // Clean up wake word audio
    if (wakeProcessor) { wakeProcessor.disconnect(); wakeProcessor = null; }
    if (wakeAudioCtx) { wakeAudioCtx.close(); wakeAudioCtx = null; }
    if (wakeStream) { wakeStream.getTracks().forEach((t) => t.stop()); wakeStream = null; }
    // Clean up call audio
    if (callProcessor) { callProcessor.disconnect(); callProcessor = null; }
    if (callAudioCtx) { callAudioCtx.close(); callAudioCtx = null; }
    if (callStream) { callStream.getTracks().forEach((t) => t.stop()); callStream = null; }
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
      playAgentSwitchAnimation();
    }
  }

  // ---------------------------------------------------------------------------
  // Mode button actions
  // ---------------------------------------------------------------------------

  function toggleAvatar() { avatarVisible = !avatarVisible; }

  function toggleMute() {
    isMuted = !isMuted;
    // TODO: wire to TTS mute in main process
  }

  // Wake word audio capture state
  let wakeStream: MediaStream | null = null;
  let wakeAudioCtx: AudioContext | null = null;
  let wakeProcessor: ScriptProcessorNode | null = null;

  async function toggleWake() {
    wakeListening = !wakeListening;

    if (wakeListening && api) {
      try {
        wakeStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
        wakeAudioCtx = new AudioContext({ sampleRate: 16000 });
        const source = wakeAudioCtx.createMediaStreamSource(wakeStream);
        wakeProcessor = wakeAudioCtx.createScriptProcessor(4096, 1, 1);
        wakeProcessor.onaudioprocess = (e: AudioProcessingEvent) => {
          if (!wakeListening) return;
          const data = e.inputBuffer.getChannelData(0);
          api.sendWakeWordChunk(data.buffer.slice(0));
        };
        source.connect(wakeProcessor);
        wakeProcessor.connect(wakeAudioCtx.destination);
      } catch (err) {
        console.error('[wake word] failed to start audio capture:', err);
        wakeListening = false;
      }
    } else {
      // Tear down ambient audio capture
      if (wakeProcessor) { wakeProcessor.disconnect(); wakeProcessor = null; }
      if (wakeAudioCtx) { wakeAudioCtx.close(); wakeAudioCtx = null; }
      if (wakeStream) { wakeStream.getTracks().forEach((t) => t.stop()); wakeStream = null; }
    }
  }

  // Voice call mode - continuous record/transcribe/send/TTS loop
  let callStream: MediaStream | null = null;
  let callAudioCtx: AudioContext | null = null;
  let callProcessor: ScriptProcessorNode | null = null;
  let callChunks: Float32Array[] = [];
  let callSilentFrames = 0;
  let callSpeechStarted = false;
  const CALL_ENERGY_THRESHOLD = 0.015;
  const CALL_SILENCE_FRAMES = 15; // ~15 * 4096/16000 = ~3.8s of silence
  const CALL_MIN_CHUNKS = 4; // minimum chunks before processing

  async function toggleCall() {
    callActive = !callActive;

    if (callActive && api) {
      try {
        callStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
        callAudioCtx = new AudioContext({ sampleRate: 16000 });
        const source = callAudioCtx.createMediaStreamSource(callStream);
        callProcessor = callAudioCtx.createScriptProcessor(4096, 1, 1);
        callChunks = [];
        callSilentFrames = 0;
        callSpeechStarted = false;

        callProcessor.onaudioprocess = (e: AudioProcessingEvent) => {
          if (!callActive) return;
          const data = e.inputBuffer.getChannelData(0);
          const chunk = new Float32Array(data);

          // Calculate RMS energy
          let sum = 0;
          for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
          const energy = Math.sqrt(sum / chunk.length);

          if (energy > CALL_ENERGY_THRESHOLD) {
            callSpeechStarted = true;
            callSilentFrames = 0;
            callChunks.push(chunk);
          } else if (callSpeechStarted) {
            callSilentFrames++;
            callChunks.push(chunk);
            if (callSilentFrames >= CALL_SILENCE_FRAMES && callChunks.length >= CALL_MIN_CHUNKS) {
              // Utterance complete - send accumulated audio for transcription
              const allChunks = callChunks;
              callChunks = [];
              callSpeechStarted = false;
              callSilentFrames = 0;
              processCallUtterance(allChunks);
            }
          }
        };
        source.connect(callProcessor);
        callProcessor.connect(callAudioCtx.destination);
      } catch (err) {
        console.error('[call] failed to start:', err);
        callActive = false;
      }
    } else {
      // Tear down call audio
      if (callProcessor) { callProcessor.disconnect(); callProcessor = null; }
      if (callAudioCtx) { callAudioCtx.close(); callAudioCtx = null; }
      if (callStream) { callStream.getTracks().forEach((t) => t.stop()); callStream = null; }
      callChunks = [];
    }
  }

  async function processCallUtterance(chunks: Float32Array[]) {
    if (!api) return;
    // Concatenate chunks into a single buffer and send for STT
    const totalLen = chunks.reduce((acc, c) => acc + c.length, 0);
    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    // Use the existing audio:chunk -> audio:stop flow for transcription
    api.sendAudioChunk(merged.buffer.slice(0));
    try {
      const transcript = await api.stopRecording();
      if (transcript && transcript.trim().length > 1) {
        addMessage('will', transcript.trim());
        completeLast();
        await api.sendMessage(transcript.trim());
      }
    } catch {
      // Transcription failed - continue listening
    }
  }

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------

  function onKeydown(e: KeyboardEvent) {
    // Reset silence timer on any keypress
    resetSilenceTimer();

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
    // Cmd+E : toggle eye mode (hide transcript)
    else if (e.metaKey && e.key === 'e') {
      e.preventDefault();
      eyeMode = !eyeMode;
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
      else if (silencePromptVisible) dismissSilencePrompt();
    }
  }

  // Also reset silence timer on mouse movement
  function onMouseMove() {
    resetSilenceTimer();
  }
</script>

<svelte:window onkeydown={onKeydown} onmousemove={onMouseMove} />

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

  <!-- Boot overlay - black div that fades from opacity 1 to 0 over 1.5s -->
  {#if bootPhase === 'boot'}
    <div class="boot-overlay" style="opacity: {bootOpacity}">
      {#if bootLabel}
        <span class="boot-label">{bootLabel}</span>
      {/if}
    </div>
  {/if}

  <!-- Agent switch clip-path reveal animation -->
  {#if agentSwitchActive}
    <div
      class="agent-switch-overlay"
      style="clip-path: {agentSwitchClip}"
    ></div>
  {/if}

  <!-- Agent deferral iris wipe (codec-style handoff) -->
  {#if deferralActive}
    <div
      class="deferral-overlay"
      style="
        clip-path: circle(
          {deferralProgress === 0 ? '150%' : deferralProgress === 1 ? '0%' : '150%'}
          at 50% 50%
        )
      "
    >
      {#if deferralProgress === 1}
        <span class="deferral-label">Handing off to {deferralTarget}...</span>
      {/if}
    </div>
  {/if}

  <!-- Top bar: agent name + thinking indicator -->
  <div class="top-bar">
    <AgentName
      name={agents.displayName}
      direction={agents.switchDirection}
      canCycle={agents.list.length > 1}
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

    <!-- Minimize -->
    <button
      class="mode-btn"
      onclick={() => api?.minimizeWindow()}
      title="Minimize"
      aria-label="Minimize"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <line x1="5" y1="12" x2="19" y2="12"/>
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

  <!-- Chat area - hidden in eye mode -->
  {#if !eyeMode}
    <Transcript />
  {/if}

  <!-- Input bar -->
  <InputBar />

  <!-- Silence prompt - subtle nudge after 5 minutes idle -->
  {#if silencePromptVisible}
    <button class="silence-prompt" onclick={dismissSilencePrompt}>
      <span class="silence-text">Still here?</span>
    </button>
  {/if}

  <!-- Overlays (conditionally rendered) -->
  {#if showTimer}
    <Timer onClose={() => showTimer = false} />
  {/if}

  {#if showCanvas}
    <Canvas onClose={() => showCanvas = false} onRequestShow={() => showCanvas = true} />
  {/if}

  {#if showArtefact}
    <Artefact onClose={() => showArtefact = false} />
  {/if}

  {#if showSettings}
    <Settings onClose={() => showSettings = false} />
  {/if}

  <!-- Setup wizard (shown on first launch) -->
  {#if needsSetup}
    <SetupWizard onComplete={async () => {
      needsSetup = false;
      // Reload config and agent list after setup (agent may have been created/switched)
      if (api) {
        try {
          const [cfg, agentList] = await Promise.all([
            api.getConfig(),
            api.getAgents(),
          ]);
          agents.current = cfg.agentName || '';
          agents.displayName = cfg.agentDisplayName || cfg.agentName || '';
          agents.list = agentList || [];
          // Fetch opening line for the new agent
          const opening = await api.getOpeningLine();
          if (opening) {
            addMessage('agent', opening);
            completeLast();
          }
        } catch { /* continue with defaults */ }
      }
    }} />
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

  /* -- Boot overlay -- */

  .boot-overlay {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: #000000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 1.5s ease;
    pointer-events: none;
  }

  .boot-label {
    font-family: var(--font-sans);
    font-size: 13px;
    letter-spacing: 2px;
    color: var(--text-dim);
    text-transform: lowercase;
  }

  /* -- Agent switch clip-path overlay -- */

  .agent-switch-overlay {
    position: absolute;
    inset: 0;
    z-index: 75;
    background: var(--bg);
    pointer-events: none;
    transition: clip-path 0.65s cubic-bezier(0.4, 0, 0.2, 1);
  }

  /* -- Agent deferral iris wipe (codec-style handoff) -- */

  .deferral-overlay {
    position: absolute;
    inset: 0;
    z-index: 80;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: clip-path 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .deferral-label {
    font-family: var(--font-sans);
    font-size: 14px;
    color: var(--text-secondary);
    letter-spacing: 0.5px;
    opacity: 0.7;
  }

  /* -- Silence prompt -- */

  .silence-prompt {
    position: absolute;
    bottom: 90px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 12;
    cursor: pointer;
    animation: silenceFadeIn 1.5s ease forwards;
  }

  .silence-text {
    font-family: var(--font-sans);
    font-size: 13px;
    color: var(--text-dim);
    letter-spacing: 1px;
    opacity: 0.6;
    transition: opacity 0.3s;
  }

  .silence-prompt:hover .silence-text {
    opacity: 1;
  }

  @keyframes silenceFadeIn {
    from { opacity: 0; transform: translateX(-50%) translateY(6px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  /* -- Top bar -- */

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

  /* -- Mode buttons -- */

  .mode-buttons {
    position: absolute;
    top: 14px;
    right: var(--pad);
    z-index: 15;
    display: flex;
    flex-direction: row;
    gap: 2px;
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

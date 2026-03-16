<script lang="ts">
  import { session } from '../stores/session.svelte';
  import { addMessage, appendToLast, completeLast, transcript } from '../stores/transcript.svelte';
  import { audio } from '../stores/audio.svelte';
  import { storeArtifact } from '../stores/artifacts.svelte';
  import { setEmotion, setEmotionFromText, revertToDefault } from '../stores/emotion-colours.svelte';
  import { api } from '../api';

  let {
    onSubmit: customSubmit,
    disabled: externalDisabled = false,
    placeholder: customPlaceholder,
    enterAnimation: enterAnim = false,
  }: {
    onSubmit?: (text: string) => Promise<void>;
    disabled?: boolean;
    placeholder?: string;
    enterAnimation?: boolean;
  } = $props();

  let inputText = $state('');
  let inputEl: HTMLInputElement;
  let isRecording = $state(false);
  let mediaStream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let workletNode: AudioWorkletNode | ScriptProcessorNode | null = null;

  // -- Voice call mode (continuous hands-free conversation) --
  let callActive = $state(false);
  let callStatus = $state<string>('idle'); // idle, listening, thinking, speaking
  let callStream: MediaStream | null = null;
  let callAudioCtx: AudioContext | null = null;
  let callProcessor: ScriptProcessorNode | null = null;

  // Keystroke sound (macOS Tink)
  let lastSound = 0;
  function playKeystroke() {
    const now = Date.now();
    if (now - lastSound < 60) return;
    lastSound = now;
    try {
      const audio = new Audio('/System/Library/Sounds/Tink.aiff');
      audio.volume = 0.02;
      audio.play().catch(() => {});
    } catch { /* silent */ }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
    if (e.key.length === 1 && !e.metaKey && !e.ctrlKey) {
      playKeystroke();
    }
  }

  async function submit() {
    const text = inputText.trim();
    if (!text) return;
    inputText = '';

    // Custom submit handler (used by setup wizard flow)
    if (customSubmit) {
      await customSubmit(text);
      return;
    }

    addMessage('user', text);
    addMessage('agent', '');
    session.inferenceState = 'thinking';
    setEmotion('thinking');

    if (api) {
      try {
        await api.sendMessage(text);
      } catch (err) {
        completeLast();
        session.inferenceState = 'idle';
      }
    }
  }

  function stop() {
    if (api) api.stopInference();
  }

  // -- Push-to-talk audio capture --

  let recordingStarting = false;
  async function startRecording() {
    if (!api || isRecording || recordingStarting) return;
    recordingStarting = true;

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          // All three MUST be false - otherwise Chromium switches macOS
          // to "voice processing" audio mode which downsamples all system
          // audio to 16kHz (makes music sound grainy/compressed).
          // Python used sounddevice (Core Audio) so it never hit this.
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });

      audioContext = new AudioContext({ sampleRate: 16000 });
      const source = audioContext.createMediaStreamSource(mediaStream);

      // Use ScriptProcessorNode (wider support than AudioWorklet for simple capture)
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (e) => {
        if (!isRecording) return;
        const input = e.inputBuffer.getChannelData(0);
        const buffer = new Float32Array(input);
        api.sendAudioChunk(buffer.buffer.slice(0));
      };

      source.connect(processor);
      processor.connect(audioContext.destination);
      workletNode = processor;

      await api.startRecording();
      isRecording = true;
    } catch (err) {
      console.error('[audio] mic access failed:', err);
    } finally {
      recordingStarting = false;
    }
  }

  async function stopRecording() {
    if (!api || !isRecording) return;

    isRecording = false;

    // Clean up audio nodes
    if (workletNode) {
      workletNode.disconnect();
      workletNode = null;
    }
    if (audioContext) {
      audioContext.close().catch(() => {});
      audioContext = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }

    // Get transcription from main process
    const text = await api.stopRecording();
    if (text && text.trim()) {
      inputText = text.trim();
      submit();
    }
  }

  // -- Voice call mode: start/stop --

  async function toggleCall() {
    if (!api) return;

    if (callActive) {
      await stopCallMode();
    } else {
      await startCallMode();
    }
  }

  async function startCallMode() {
    if (!api || callActive) return;

    try {
      // Open mic stream for continuous capture
      callStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });

      callAudioCtx = new AudioContext({ sampleRate: 16000 });
      const source = callAudioCtx.createMediaStreamSource(callStream);

      // Send PCM chunks to main process via call:chunk IPC
      callProcessor = callAudioCtx.createScriptProcessor(1600, 1, 1);
      callProcessor.onaudioprocess = (e) => {
        if (!callActive) return;
        const input = e.inputBuffer.getChannelData(0);
        const buffer = new Float32Array(input);
        api.sendCallChunk(buffer.buffer.slice(0));
      };

      source.connect(callProcessor);
      callProcessor.connect(callAudioCtx.destination);

      // Tell main process to start the call loop
      await api.startCall();
      callActive = true;
      callStatus = 'listening';
    } catch (err) {
      console.error('[call] failed to start:', err);
      await stopCallMode();
    }
  }

  async function stopCallMode() {
    callActive = false;
    callStatus = 'idle';

    // Clean up audio pipeline
    if (callProcessor) {
      callProcessor.disconnect();
      callProcessor = null;
    }
    if (callAudioCtx) {
      callAudioCtx.close().catch(() => {});
      callAudioCtx = null;
    }
    if (callStream) {
      callStream.getTracks().forEach((t) => t.stop());
      callStream = null;
    }

    // Tell main process to stop the call loop
    if (api) {
      await api.stopCall().catch(() => {});
    }
  }

  // Push-to-talk: Ctrl key detection
  function onGlobalKeydown(e: KeyboardEvent) {
    if (e.key === 'Alt' && !isRecording && !callActive && session.inferenceState === 'idle') {
      startRecording();
    }
  }

  function onGlobalKeyup(e: KeyboardEvent) {
    if (e.key === 'Alt' && isRecording) {
      stopRecording();
    }
  }

  // Wire up streaming listeners and keyboard events
  $effect(() => {
    if (!api) return;

    // ── Text-audio sync ──
    // When TTS is active, buffer text and only reveal each sentence
    // when its audio starts playing. This keeps text and voice in sync.
    // When TTS is off/muted, text appears immediately.

    // Buffer for detecting partial <artifact> tags during streaming.
    let streamBuffer = '';
    // Accumulated raw text (for sync mode - holds text until audio plays)
    let rawTextBuffer = '';
    // How many characters have been revealed to the transcript
    let revealedChars = 0;
    // Sentence boundaries: index -> char offset where that sentence ends in rawTextBuffer
    let sentenceBoundaries: { index: number; endChar: number; ttsActive: boolean }[] = [];
    // Which sentence index has started playing
    let lastPlayedIndex = -1;
    // Whether we're in sync mode for this response
    let syncMode = false;
    // Track if streaming is done (need to reveal remaining text)
    let streamDone = false;

    function resetSyncState() {
      rawTextBuffer = '';
      revealedChars = 0;
      sentenceBoundaries = [];
      lastPlayedIndex = -1;
      syncMode = false;
      streamDone = false;
    }

    function stripArtifacts(text: string): string {
      // Remove <artifact>...</artifact> blocks
      return text.replace(/<artifact[\s\S]*?<\/artifact>/g, '');
    }

    // Reveal text up to a character position
    function revealUpTo(targetChars: number) {
      if (targetChars <= revealedChars) return;
      const cleaned = stripArtifacts(rawTextBuffer);
      const toReveal = cleaned.slice(revealedChars, targetChars);
      if (toReveal) {
        appendToLast(toReveal);
      }
      revealedChars = targetChars;
    }

    // Reveal all remaining text (when stream ends or TTS finishes)
    function revealAll() {
      const cleaned = stripArtifacts(rawTextBuffer);
      if (revealedChars < cleaned.length) {
        appendToLast(cleaned.slice(revealedChars));
        revealedChars = cleaned.length;
      }
    }

    function flushBuffer() {
      if (streamBuffer) {
        if (syncMode) {
          // In sync mode, accumulate but don't reveal yet
          rawTextBuffer += streamBuffer;
        } else {
          appendToLast(streamBuffer);
        }
        streamBuffer = '';
      }
    }

    const unsubs = [
      api.onTextDelta((text: string) => {
        session.inferenceState = 'streaming';
        streamBuffer += text;

        // Check if buffer might contain a partial <artifact tag
        const lastOpen = streamBuffer.lastIndexOf('<artifact');
        if (lastOpen !== -1) {
          if (lastOpen > 0) {
            const before = streamBuffer.slice(0, lastOpen);
            if (syncMode) {
              rawTextBuffer += before;
            } else {
              appendToLast(before);
            }
            streamBuffer = streamBuffer.slice(lastOpen);
          }
          const closeIdx = streamBuffer.indexOf('</artifact>');
          if (closeIdx !== -1) {
            const afterClose = streamBuffer.slice(closeIdx + '</artifact>'.length);
            if (syncMode) {
              rawTextBuffer += streamBuffer; // Keep artifact in raw buffer for stripping
            }
            streamBuffer = afterClose;
            if (streamBuffer) flushBuffer();
          }
        } else if (streamBuffer.endsWith('<')) {
          const before = streamBuffer.slice(0, -1);
          if (syncMode) {
            rawTextBuffer += before;
          } else {
            appendToLast(before);
          }
          streamBuffer = '<';
        } else {
          flushBuffer();
        }
      }),
      // Sentence boundary - controls when text is revealed in sync mode
      api.onSentenceReady((sentence: string, index: number, ttsActive: boolean) => {
        if (index === 0) {
          // First sentence - decide sync mode for this response
          syncMode = ttsActive;
        }

        // Record where this sentence ends in the raw buffer
        const endChar = stripArtifacts(rawTextBuffer).length;
        sentenceBoundaries.push({ index, endChar, ttsActive });

        if (!ttsActive) {
          // No TTS - reveal immediately
          revealAll();
        }
      }),
      api.onDone((fullText: string) => {
        flushBuffer();
        streamDone = true;

        if (!syncMode) {
          // Not in sync mode - reveal everything
          revealAll();
        } else {
          // In sync mode - reveal up to last played sentence,
          // any remaining text after last sentence plays via tts:done/queueEmpty
        }

        completeLast();
        session.inferenceState = 'idle';
        setEmotionFromText(fullText);
      }),
      api.onError((msg: string) => {
        flushBuffer();
        revealAll();
        resetSyncState();
        completeLast();
        session.inferenceState = 'idle';
        revertToDefault();
        if (msg) {
          addMessage('system', `Error: ${msg}`);
        }
      }),
      api.onCompacting(() => {
        session.inferenceState = 'compacting';
      }),
      api.onArtifact((artifact: { id: string; type: string; title: string; language: string; content: string }) => {
        storeArtifact(artifact as any);
      }),
      // TTS events - drive text reveal in sync mode
      api.onTtsStarted((index: number) => {
        audio.isPlaying = true;
        audio.vignetteOpacity = 0.15;

        if (syncMode) {
          lastPlayedIndex = index;
          // Reveal text up to this sentence's boundary
          const boundary = sentenceBoundaries.find((b) => b.index === index);
          if (boundary) {
            revealUpTo(boundary.endChar);
          }
        }
      }),
      api.onTtsDone((_index: number) => {
        // Keep playing until queue empty
      }),
      api.onTtsQueueEmpty(() => {
        audio.isPlaying = false;
        audio.vignetteOpacity = 0;

        // Reveal any remaining text after all audio has played
        if (syncMode) {
          revealAll();
          resetSyncState();
        }
      }),
      // Voice call status updates from main process
      api.onCallStatusChanged((status: string) => {
        callStatus = status;
        if (status === 'idle') {
          // Call ended from main process side - clean up renderer
          if (callActive) {
            callActive = false;
            if (callProcessor) { callProcessor.disconnect(); callProcessor = null; }
            if (callAudioCtx) { callAudioCtx.close().catch(() => {}); callAudioCtx = null; }
            if (callStream) { callStream.getTracks().forEach((t: MediaStreamTrack) => t.stop()); callStream = null; }
          }
        }
      }),
    ];

    // Push-to-talk keyboard events
    window.addEventListener('keydown', onGlobalKeydown);
    window.addEventListener('keyup', onGlobalKeyup);

    return () => {
      unsubs.forEach((fn: () => void) => fn());
      window.removeEventListener('keydown', onGlobalKeydown);
      window.removeEventListener('keyup', onGlobalKeyup);
      if (isRecording) stopRecording();
      if (callActive) stopCallMode();
    };
  });

  let isActive = $derived(session.inferenceState !== 'idle');

  // Derive a placeholder that reflects call state
  let callPlaceholder = $derived(
    callActive
      ? callStatus === 'listening' ? 'Listening...'
        : callStatus === 'thinking' ? 'Thinking...'
        : callStatus === 'speaking' ? 'Speaking...'
        : 'In call...'
      : ''
  );
</script>

<div class="bar-container" class:enter-anim={enterAnim} data-no-drag>
  <div class="input-bar" class:recording={isRecording} class:in-call={callActive}>
    <input
      bind:this={inputEl}
      bind:value={inputText}
      onkeydown={onKeydown}
      placeholder={callActive ? callPlaceholder : isRecording ? 'Listening...' : (customPlaceholder || 'Message...')}
      type="text"
      class="input-field"
      disabled={isActive || isRecording || callActive || externalDisabled}
    />

    <!-- Call button (phone icon) - toggle voice call mode -->
    <button
      class="call-btn"
      class:active={callActive}
      class:listening={callActive && callStatus === 'listening'}
      class:thinking={callActive && callStatus === 'thinking'}
      class:speaking={callActive && callStatus === 'speaking'}
      onclick={toggleCall}
      disabled={isRecording || (isActive && !callActive)}
      aria-label={callActive ? 'End call' : 'Start voice call'}
      title={callActive ? 'End call' : 'Voice call'}
    >
      {#if callActive}
        <!-- Phone off / hang up icon -->
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <path d="M23.71 16.67C20.66 13.78 16.54 12 12 12S3.34 13.78.29 16.67a1 1 0 0 0 0 1.41l2.12 2.12a1 1 0 0 0 1.41 0 12.6 12.6 0 0 1 3.51-2.37 1 1 0 0 0 .58-.91V14a13.94 13.94 0 0 1 8.18 0v2.92a1 1 0 0 0 .58.91 12.6 12.6 0 0 1 3.51 2.37 1 1 0 0 0 1.41 0l2.12-2.12a1 1 0 0 0 0-1.41z"/>
        </svg>
      {:else}
        <!-- Phone icon -->
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
        </svg>
      {/if}
    </button>

    <!-- Mic button (push-to-talk) -->
    <button
      class="mic-btn"
      class:recording={isRecording}
      onmousedown={isRecording ? undefined : startRecording}
      onmouseup={isRecording ? stopRecording : undefined}
      disabled={callActive}
      aria-label={isRecording ? 'Stop recording' : 'Record'}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill={isRecording ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
        <line x1="12" y1="19" x2="12" y2="23"/>
        <line x1="8" y1="23" x2="16" y2="23"/>
      </svg>
    </button>

    <!-- Send / Stop button -->
    <button
      class="action-btn"
      class:poof={enterAnim}
      onclick={isActive ? stop : submit}
      class:active={isActive}
      disabled={callActive}
      aria-label={isActive ? 'Stop' : 'Send'}
    >
      {#if isActive}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="1"/>
        </svg>
      {:else}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
        </svg>
      {/if}
    </button>
  </div>
</div>

<style>
  .bar-container {
    position: relative;
    z-index: 10;
    padding: 12px var(--pad) var(--pad);
  }

  .input-bar {
    display: flex;
    align-items: center;
    height: var(--bar-height);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--bar-radius);
    transition: border-color 0.2s;
  }

  .input-bar:focus-within {
    border-color: var(--border-hover);
  }

  .input-bar.recording {
    border-color: rgba(255, 80, 80, 0.5);
  }

  .input-bar.in-call {
    border-color: rgba(80, 200, 120, 0.5);
  }

  .input-field {
    flex: 1;
    height: 100%;
    background: transparent;
    border: none;
    outline: none;
    color: rgba(255, 255, 255, 0.9);
    font-family: var(--font-sans);
    font-size: 14px;
    padding: 0 20px;
    padding-right: 128px;
  }

  .input-field::placeholder {
    color: var(--text-dim);
  }

  .input-field::selection {
    background: rgba(255, 255, 255, 0.2);
  }

  .input-field:disabled {
    opacity: 0.5;
  }

  .call-btn {
    position: absolute;
    right: calc(var(--pad) + 82px);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s, background 0.15s;
  }

  .call-btn:hover {
    color: rgba(255, 255, 255, 0.7);
  }

  .call-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .call-btn.active {
    color: rgba(80, 200, 120, 0.9);
    background: rgba(80, 200, 120, 0.15);
  }

  .call-btn.active:hover {
    color: rgba(255, 80, 80, 0.9);
    background: rgba(255, 80, 80, 0.15);
  }

  .call-btn.listening {
    animation: pulse-call 2s ease-in-out infinite;
  }

  .call-btn.thinking {
    animation: pulse-call-think 1s ease-in-out infinite;
  }

  .call-btn.speaking {
    animation: pulse-call-speak 0.8s ease-in-out infinite;
  }

  @keyframes pulse-call {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  @keyframes pulse-call-think {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  @keyframes pulse-call-speak {
    0%, 100% { box-shadow: 0 0 0 0 rgba(80, 200, 120, 0.3); }
    50% { box-shadow: 0 0 8px 2px rgba(80, 200, 120, 0.15); }
  }

  .mic-btn {
    position: absolute;
    right: calc(var(--pad) + 44px);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s, background 0.15s;
  }

  .mic-btn:hover {
    color: rgba(255, 255, 255, 0.7);
  }

  .mic-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .mic-btn.recording {
    color: rgba(255, 80, 80, 0.9);
    background: rgba(255, 80, 80, 0.15);
    animation: pulse-mic 1s ease-in-out infinite;
  }

  @keyframes pulse-mic {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  .action-btn {
    position: absolute;
    right: calc(var(--pad) + 6px);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: rgba(255, 255, 255, 0.16);
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s;
  }

  .action-btn:hover {
    background: rgba(255, 255, 255, 0.24);
    color: rgba(255, 255, 255, 0.9);
  }

  .action-btn.active {
    background: rgba(255, 255, 255, 0.78);
    color: rgba(0, 0, 0, 0.8);
  }

  .action-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .action-btn.active:hover {
    background: rgba(255, 255, 255, 0.9);
  }

  /* Enter animation - bar slides up from below and widens */
  .bar-container.enter-anim {
    animation: bar-enter 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }

  @keyframes bar-enter {
    from {
      opacity: 0;
      transform: translateY(20px) scaleX(0.6);
    }
    to {
      opacity: 1;
      transform: translateY(0) scaleX(1);
    }
  }

  /* Send button poof into place */
  .action-btn.poof {
    animation: poof-in 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) 0.3s both;
  }

  @keyframes poof-in {
    from {
      opacity: 0;
      transform: scale(0);
    }
    to {
      opacity: 1;
      transform: scale(1);
    }
  }
</style>

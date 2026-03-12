<script lang="ts">
  import { session } from '../stores/session.svelte';
  import { addMessage, appendToLast, completeLast, transcript } from '../stores/transcript.svelte';
  import { audio } from '../stores/audio.svelte';
  import { storeArtifact } from '../stores/artifacts.svelte';

  let {
    onSubmit: customSubmit,
    disabled: externalDisabled = false,
    placeholder: customPlaceholder,
  }: {
    onSubmit?: (text: string) => Promise<void>;
    disabled?: boolean;
    placeholder?: string;
  } = $props();

  let inputText = $state('');
  let inputEl: HTMLInputElement;
  let isRecording = $state(false);
  let mediaStream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let workletNode: AudioWorkletNode | ScriptProcessorNode | null = null;

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

    const api = (window as any).atrophy;
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
    const api = (window as any).atrophy;
    if (api) api.stopInference();
  }

  // -- Push-to-talk audio capture --

  async function startRecording() {
    const api = (window as any).atrophy;
    if (!api || isRecording) return;

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
    }
  }

  async function stopRecording() {
    const api = (window as any).atrophy;
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

  // Push-to-talk: Ctrl key detection
  function onGlobalKeydown(e: KeyboardEvent) {
    if (e.key === 'Control' && !isRecording && session.inferenceState === 'idle') {
      startRecording();
    }
  }

  function onGlobalKeyup(e: KeyboardEvent) {
    if (e.key === 'Control' && isRecording) {
      stopRecording();
    }
  }

  // Wire up streaming listeners and keyboard events
  $effect(() => {
    const api = (window as any).atrophy;
    if (!api) return;

    // Buffer for detecting partial <artifact> tags during streaming.
    // When we see a '<' that could be the start of an artifact tag,
    // we hold text until we can confirm it's not an artifact block.
    let streamBuffer = '';

    function flushBuffer() {
      if (streamBuffer) {
        appendToLast(streamBuffer);
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
          // Flush everything before the potential tag
          if (lastOpen > 0) {
            appendToLast(streamBuffer.slice(0, lastOpen));
            streamBuffer = streamBuffer.slice(lastOpen);
          }
          // Check if we have a complete closing tag - if so, don't show it
          // (the main process will strip it and send cleaned text on done)
          const closeIdx = streamBuffer.indexOf('</artifact>');
          if (closeIdx !== -1) {
            // Full artifact block in buffer - discard it, main process handles extraction
            const afterClose = streamBuffer.slice(closeIdx + '</artifact>'.length);
            streamBuffer = afterClose;
            if (streamBuffer) flushBuffer();
          }
          // Otherwise keep buffering until tag completes or turns out to not be an artifact
        } else if (streamBuffer.endsWith('<')) {
          // Might be start of <artifact - hold it
          appendToLast(streamBuffer.slice(0, -1));
          streamBuffer = '<';
        } else {
          flushBuffer();
        }
      }),
      api.onDone((_fullText: string) => {
        // Flush any remaining buffer (partial tags that never completed)
        flushBuffer();
        completeLast();
        session.inferenceState = 'idle';
      }),
      api.onError((_msg: string) => {
        flushBuffer();
        completeLast();
        session.inferenceState = 'idle';
      }),
      api.onCompacting(() => {
        session.inferenceState = 'compacting';
      }),
      // Inline artifacts from agent response
      api.onArtifact((artifact: { id: string; type: string; title: string; language: string; content: string }) => {
        storeArtifact(artifact as any);
      }),
      // TTS events
      api.onTtsStarted((_index: number) => {
        audio.isPlaying = true;
        audio.vignetteOpacity = 0.15;
      }),
      api.onTtsDone((_index: number) => {
        // Keep playing until queue empty
      }),
      api.onTtsQueueEmpty(() => {
        audio.isPlaying = false;
        audio.vignetteOpacity = 0;
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
    };
  });

  let isActive = $derived(session.inferenceState !== 'idle');
</script>

<div class="bar-container" data-no-drag>
  <div class="input-bar" class:recording={isRecording}>
    <input
      bind:this={inputEl}
      bind:value={inputText}
      onkeydown={onKeydown}
      placeholder={isRecording ? 'Listening...' : (customPlaceholder || 'Message...')}
      type="text"
      class="input-field"
      disabled={isActive || isRecording || externalDisabled}
    />

    <!-- Mic button -->
    <button
      class="mic-btn"
      class:recording={isRecording}
      onmousedown={isRecording ? undefined : startRecording}
      onmouseup={isRecording ? stopRecording : undefined}
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
      onclick={isActive ? stop : submit}
      class:active={isActive}
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
    padding-right: 90px;
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

  .action-btn.active:hover {
    background: rgba(255, 255, 255, 0.9);
  }
</style>

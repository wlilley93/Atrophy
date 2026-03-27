# src/renderer/components/InputBar.svelte - Text/Voice Input Bar

**Dependencies:** `../stores/session.svelte`, `../stores/transcript.svelte`, `../stores/audio.svelte`, `../stores/artifacts.svelte`, `../stores/emotion-colours.svelte`, `../stores/agents.svelte`, `../api`  
**Purpose:** Text and voice input with push-to-talk and voice call mode

## Overview

This component provides the main input interface for user messages. It supports text input with Enter-to-send, push-to-talk voice capture, and continuous voice call mode for hands-free conversation.

## Props

```typescript
{
  onSubmit?: (text: string) => Promise<void>;  // Custom submit handler (setup wizard)
  disabled?: boolean;                          // External disable control
  placeholder?: string;                        // Custom placeholder text
  enterAnimation?: boolean;                    // Enter animation trigger
}
```

## State Variables

```typescript
let inputText = $state('');
let inputEl: HTMLInputElement;
let isRecording = $state(false);
let mediaStream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | ScriptProcessorNode | null = null;

// Voice call mode
let callActive = $state(false);
let callStatus = $state<string>('idle');  // idle, listening, thinking, speaking
let callStream: MediaStream | null = null;
let callAudioCtx: AudioContext | null = null;
let callProcessor: ScriptProcessorNode | null = null;
```

## Text Input

### submit

```typescript
let _submitting = $state(false);

async function submit() {
  if (_submitting) return;  // Guard against rapid double-submit
  const text = inputText.trim();
  if (!text) return;
  _submitting = true;
  inputText = '';

  // Custom submit handler (setup wizard)
  if (customSubmit) {
    try { await customSubmit(text); } finally { _submitting = false; }
    return;
  }

  // Normal inference flow
  addMessage('user', text);
  addMessage('agent', '');  // Empty placeholder for streaming
  session.inferenceState = 'thinking';
  setEmotion('thinking');

  try {
    await api.sendMessage(text);
  } catch (err) {
    // Remove empty agent bubble on error
    const msgs = transcript.messages;
    const last = msgs[msgs.length - 1];
    if (last?.role === 'agent' && !last.content) {
      msgs.pop();
    } else {
      completeLast();
    }
    session.inferenceState = 'idle';
  } finally {
    _submitting = false;
  }
}
```

**Flow:**
1. Guard against double-submit
2. Add user message to transcript
3. Add empty agent placeholder for streaming
4. Set inference state to 'thinking'
5. Set emotion to 'thinking'
6. Send message via IPC
7. Handle errors (remove empty bubble or complete it)

### onKeydown

```typescript
function playKeystroke() {
  const now = Date.now();
  if (now - lastSound < 60) return;  // Debounce
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
```

**Features:**
- Enter to send (Shift+Enter for newline)
- macOS Tink sound on keystroke (debounced to 60ms)

## Push-to-Talk Voice Capture

### startRecording

```typescript
let recordingStarting = $state(false);
let recordingCancelled = $state(false);

async function startRecording() {
  if (!api || isRecording || recordingStarting) return;
  recordingStarting = true;
  recordingCancelled = false;

  try {
    // Request mic access
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        // CRITICAL: All three MUST be false
        // Otherwise Chromium switches macOS to "voice processing" mode
        // which downsamples all system audio to 16kHz (makes music grainy)
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });

    // If key was released while waiting for mic grant, clean up
    if (recordingCancelled) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
      return;
    }

    // Set up audio processing
    audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(mediaStream);

    // ScriptProcessorNode for audio capture (wider support than AudioWorklet)
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

    // Start recording
    await api.startRecording();
    isRecording = true;
    session.isRecording = true;
  } catch (err) {
    console.error('[InputBar] Recording failed:', err);
  } finally {
    recordingStarting = false;
  }
}
```

**Critical audio settings:**
- `echoCancellation: false` - Prevents system audio downsampling
- `noiseSuppression: false` - Preserves audio quality
- `autoGainControl: false` - Prevents automatic volume changes

### stopRecording

```typescript
async function stopRecording() {
  if (!api || !isRecording) return;
  
  isRecording = false;
  session.isRecording = false;
  recordingStarting = false;

  try {
    const transcription = await api.stopRecording();
    
    if (transcription) {
      // Auto-submit transcription
      inputText = transcription;
      submit();
    }
  } catch (err) {
    console.error('[InputBar] Stop recording failed:', err);
  }

  // Clean up audio resources
  if (workletNode) {
    workletNode.disconnect();
    workletNode = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
}
```

**Flow:**
1. Stop recording in main process
2. Get transcription
3. Auto-submit transcription
4. Clean up audio resources

### Global Key Handlers

```svelte
<!-- In template -->
<svelte:window
  on:keydown={onGlobalKeydown}
  on:keyup={onGlobalKeyup}
/>

<script>
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
</script>
```

**Purpose:** Ctrl key push-to-talk anywhere in app.

## Voice Call Mode

### startCall

```typescript
async function startCall() {
  callActive = true;
  callStatus = 'listening';
  
  try {
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
    
    callProcessor = callAudioCtx.createScriptProcessor(4096, 1, 1);
    callProcessor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      const buffer = new Float32Array(input);
      api.sendVoiceCallChunk(buffer.buffer);
    };
    
    source.connect(callProcessor);
    callProcessor.connect(callAudioCtx.destination);
    
    await api.startVoiceCall();
  } catch (err) {
    console.error('[InputBar] Voice call start failed:', err);
    callActive = false;
  }
}
```

**Purpose:** Start continuous hands-free voice conversation.

### stopCall

```typescript
async function stopCall() {
  callActive = false;
  callStatus = 'idle';
  
  await api.stopVoiceCall();
  
  if (callProcessor) {
    callProcessor.disconnect();
    callProcessor = null;
  }
  if (callAudioCtx) {
    callAudioCtx.close();
    callAudioCtx = null;
  }
  if (callStream) {
    callStream.getTracks().forEach((t) => t.stop());
    callStream = null;
  }
}
```

## Inference Event Handlers

```svelte
onMount(() => {
  // Text delta - append to last agent message
  const unsubDelta = api.onTextDelta((text) => {
    appendToLast(text);
  });
  
  // Sentence ready - trigger TTS
  const unsubSentence = api.onSentenceReady((sentence, index, ttsActive) => {
    if (ttsActive) {
      // TTS will be synthesized and queued
    }
  });
  
  // Done - complete last message
  const unsubDone = api.onDone((fullText) => {
    completeLast();
    session.inferenceState = 'idle';
    revertToDefault();  // Reset emotion colour
  });
  
  // Error - handle error
  const unsubError = api.onError((message) => {
    completeLast();
    session.inferenceState = 'idle';
  });
  
  // Artifact - store for display
  const unsubArtifact = api.onArtifact((artifact) => {
    storeArtifact(artifact);
  });
  
  return () => {
    unsubDelta();
    unsubSentence();
    unsubDone();
    unsubError();
    unsubArtifact();
  };
});
```

## Template Structure

```svelte
<div class="input-bar" class:recording={isRecording} class:call-active={callActive}>
  <div class="input-wrapper">
    <textarea
      bind:this={inputEl}
      bind:value={inputText}
      on:keydown={onKeydown}
      placeholder={customPlaceholder || 'Type a message...'}
      disabled={externalDisabled || _submitting || callActive}
      rows={1}
    />
    
    <div class="buttons">
      {#if callActive}
        <button class="call-stop" on:click={stopCall}>
          End Call
        </button>
      {:else}
        <button
          class="mic"
          class:recording={isRecording}
          on:mousedown={startRecording}
          on:mouseup={stopRecording}
          on:mouseleave={stopRecording}
        >
          🎤
        </button>
        
        <button
          class="call-start"
          on:click={startCall}
          disabled={session.inferenceState !== 'idle'}
        >
          📞
        </button>
      {/if}
      
      <button
        class="send"
        on:click={submit}
        disabled={!inputText.trim() || _submitting || externalDisabled}
      >
        Send
      </button>
    </div>
  </div>
  
  {#if isRecording}
    <div class="recording-indicator">
      <span class="dot" />
      Recording... (release Ctrl to send)
    </div>
  {/if}
</div>
```

## Styling

```svelte
<style>
  .input-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 20px;
    background: linear-gradient(to top, rgba(0, 0, 0, 0.8), transparent);
  }
  
  .input-wrapper {
    display: flex;
    gap: 10px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 10px;
    backdrop-filter: blur(10px);
  }
  
  textarea {
    flex: 1;
    background: transparent;
    border: none;
    color: white;
    font-size: 16px;
    resize: none;
    outline: none;
  }
  
  .buttons {
    display: flex;
    gap: 8px;
  }
  
  button {
    padding: 10px 16px;
    border: none;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.2);
    color: white;
    cursor: pointer;
    transition: background 0.2s;
  }
  
  button:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.3);
  }
  
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .recording-indicator {
    position: absolute;
    top: -40px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(255, 0, 0, 0.8);
    color: white;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 14px;
  }
  
  .dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: white;
    border-radius: 50%;
    margin-right: 8px;
    animation: pulse 1s infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
</style>
```

## Exported API

None - component is self-contained.

## See Also

- [`transcript.svelte.ts`](../stores/transcript.svelte.md) - Message history
- [`session.svelte.ts`](../stores/session.svelte.md) - Inference state
- `src/main/audio.ts` - Push-to-talk audio bridge

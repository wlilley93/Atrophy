# src/renderer/components/InputBar.svelte - Text/Voice Input Bar

**Line count:** ~742 lines  
**Dependencies:** `svelte`, store imports, `../api`  
**Purpose:** Text and voice input with push-to-talk, voice call mode, and keystroke sounds

## Overview

This component provides the main input interface for user messages. It supports text input with Enter-to-send, push-to-talk voice capture, and continuous voice call mode for hands-free conversation.

## Props

```typescript
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
```

**Purpose:**
- `onSubmit`: Custom submit handler (used by setup wizard)
- `disabled`: External disable control
- `placeholder`: Custom placeholder text
- `enterAnimation`: Enter animation trigger flag

## State Variables

### Input State

```typescript
let inputText = $state('');
let inputEl: HTMLInputElement;
let isRecording = $state(false);
let mediaStream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | ScriptProcessorNode | null = null;
```

### Voice Call Mode

```typescript
let callActive = $state(false);
let callStatus = $state<string>('idle');  // idle, listening, thinking, speaking
let callStream: MediaStream | null = null;
let callAudioCtx: AudioContext | null = null;
let callProcessor: ScriptProcessorNode | null = null;
```

### Keystroke Sound

```typescript
let lastSound = 0;
```

## Keystroke Sound

### playKeystroke

```typescript
function playKeystroke() {
  const now = Date.now();
  if (now - lastSound < 60) return;  // 60ms debounce
  lastSound = now;
  try {
    const audio = new Audio('/System/Library/Sounds/Tink.aiff');
    audio.volume = 0.02;
    audio.play().catch(() => {});
  } catch { /* silent */ }
}
```

**Purpose:** Play macOS Tink sound on keystroke.

**Debounce:** 60ms between sounds to prevent audio overload.

### onKeydown

```typescript
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

**Behavior:**
- Enter (without Shift): Submit message
- Single character: Play keystroke sound

## Text Submission

### submit

```typescript
let _submitting = false;

async function submit() {
  if (_submitting) return;  // Guard against rapid double-submit
  const text = inputText.trim();
  if (!text) return;
  _submitting = true;
  inputText = '';

  // Custom submit handler (used by setup wizard flow)
  if (customSubmit) {
    try { await customSubmit(text); } finally { _submitting = false; }
    return;
  }

  addMessage('user', text);
  addMessage('agent', '');  // Empty placeholder for streaming
  session.inferenceState = 'thinking';
  setEmotion('thinking');

  if (api) {
    try {
      await api.sendMessage(text);
    } catch (err) {
      // Remove empty agent bubble or show error
      const msgs = transcript.messages;
      const last = msgs.length > 0 ? msgs[msgs.length - 1] : null;
      if (last && last.role === 'agent' && !last.content) {
        msgs.pop();
      } else {
        completeLast();
      }
      session.inferenceState = 'idle';
    } finally {
      _submitting = false;
    }
  } else {
    _submitting = false;
  }
}
```

**Flow:**
1. Guard against double-submit
2. Clear input
3. Add user message to transcript
4. Add empty agent placeholder
5. Set inference state to 'thinking'
6. Set emotion to 'thinking'
7. Send message via API
8. Handle errors (remove empty bubble or complete it)

### stop

```typescript
function stop() {
  if (api) api.stopInference();
}
```

**Purpose:** Stop current inference.

## Push-to-Talk Audio Capture

### startRecording

```typescript
let recordingStarting = false;
let recordingCancelled = false;

async function startRecording() {
  if (!api || isRecording || recordingStarting) return;
  recordingStarting = true;
  recordingCancelled = false;

  try {
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

    // If key was released while waiting for mic grant, clean up immediately
    if (recordingCancelled) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
      return;
    }

    audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(mediaStream);

    // Use ScriptProcessorNode (wider support than AudioWorklet)
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
```

**Critical audio settings:**
- `echoCancellation: false` - Prevents system audio downsampling
- `noiseSuppression: false` - Preserves audio quality
- `autoGainControl: false` - Prevents automatic volume changes

**Why ScriptProcessorNode:** Wider browser support than AudioWorklet for simple capture.

### stopRecording

```typescript
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
```

**Flow:**
1. Stop recording state
2. Disconnect audio nodes
3. Close audio context
4. Stop media stream tracks
5. Get transcription
6. Auto-submit transcription

## Voice Call Mode

### toggleCall

```typescript
async function toggleCall() {
  if (!api) return;
  if (callActive) {
    await stopCallMode();
  } else {
    await startCallMode();
  }
}
```

### startCallMode

```typescript
async function startCallMode() {
  if (!api || callActive) return;

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
    callActive = true;
    callStatus = 'listening';
  } catch (err) {
    console.error('[call] failed:', err);
  }
}
```

**Purpose:** Start continuous hands-free voice conversation.

### stopCallMode

```typescript
async function stopCallMode() {
  if (!callActive) return;

  callActive = false;
  callStatus = 'idle';

  await api.stopVoiceCall();

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
}
```

**Purpose:** Stop voice call mode and clean up resources.

## Template Structure

```svelte
<div class="input-bar" class:disabled={externalDisabled || _submitting}>
  <div class="input-wrapper">
    <!-- Text input -->
    <input
      bind:this={inputEl}
      bind:value={inputText}
      on:keydown={onKeydown}
      type="text"
      placeholder={customPlaceholder || 'Type a message...'}
      disabled={externalDisabled || _submitting || callActive}
      class="text-input"
    />

    <!-- Voice call button -->
    {#if !callActive}
      <button 
        class="call-btn" 
        onclick={toggleCall}
        title="Start voice call"
      >
        📞
      </button>
    {:else}
      <div class="call-status" class:status={callStatus}>
        {callStatus}
      </div>
    {/if}

    <!-- Push-to-talk button -->
    <button
      class="mic-btn"
      class:recording={isRecording}
      on:mousedown={startRecording}
      on:mouseup={stopRecording}
      on:mouseleave={stopRecording}
      title="Hold to speak"
    >
      🎤
    </button>

    <!-- Send button -->
    {#if inputText.trim() || _submitting}
      <button
        class="send-btn"
        onclick={submit}
        disabled={!inputText.trim() || _submitting}
      >
        {#if _submitting}
          <span class="spinner"></span>
        {:else}
          <svg>...</svg>
        {/if}
      </button>
    {/if}
  </div>

  <!-- Recording indicator -->
  {#if isRecording}
    <div class="recording-indicator">
      <span class="dot"></span>
      Recording... (release to send)
    </div>
  {/if}
</div>
```

## Styling

```css
.input-bar {
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  width: 90%;
  max-width: 800px;
}

.input-bar.disabled {
  opacity: 0.5;
  pointer-events: none;
}

.input-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  backdrop-filter: blur(20px);
}

.text-input {
  flex: 1;
  background: transparent;
  border: none;
  color: white;
  font-size: 16px;
  outline: none;
}

.call-btn, .mic-btn, .send-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: color 0.15s, background 0.15s;
}

.call-btn:hover, .mic-btn:hover, .send-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.1);
}

.mic-btn.recording {
  color: #ff4444;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.recording-indicator {
  position: absolute;
  top: -40px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 68, 68, 0.9);
  color: white;
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 14px;
  white-space: nowrap;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  background: white;
  border-radius: 50%;
  margin-right: 8px;
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/renderer/stores/transcript.svelte.ts` - Message store
- `src/main/audio.ts` - Push-to-talk audio bridge

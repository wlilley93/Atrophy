# src/renderer/components/MirrorSetup.svelte - Mirror Agent Setup

**Line count:** ~647 lines  
**Dependencies:** `svelte`, `../api`  
**Purpose:** Custom setup flow for The Mirror agent - photo upload, avatar generation, voice ID

## Overview

This component provides the custom setup flow for The Mirror agent. It appears when switching to The Mirror for the first time and guides the user through downloading assets, uploading a reference photo, generating avatar loops, and setting a voice ID.

**Flow:** intro → downloading → photo → generating → voice → done

## Props

```typescript
let { onComplete, onSkip }: { 
  onComplete?: () => void; 
  onSkip?: () => void; 
} = $props();
```

## Phase Types

```typescript
type Phase = 'intro' | 'downloading' | 'photo' | 'generating' | 'voice' | 'done';
```

**Phases:**
1. **intro**: Welcome and explanation
2. **downloading**: Downloading avatar assets
3. **photo**: Upload reference photo
4. **generating**: Generating avatar loops
5. **voice**: Set voice ID
6. **done**: Completion

## State Variables

```typescript
let phase = $state<Phase>('intro');
let photoPreview = $state<string | null>(null);
let photoFile = $state<File | null>(null);
let generating = $state(false);
let progressMessage = $state('');
let progressClip = $state(0);
let progressTotal = $state(0);
let downloadPercent = $state(0);
let voiceId = $state('');
let errorMessage = $state('');
let fileInput: HTMLInputElement;
```

## Progress Listeners

### clearDownloadListeners

```typescript
function clearDownloadListeners() {
  downloadCleanups.forEach((fn) => fn());
  downloadCleanups = [];
}
```

### startProgressListener

```typescript
function startProgressListener() {
  if (!api?.onMirrorAvatarProgress) return;
  progressCleanup = api.onMirrorAvatarProgress((p) => {
    progressMessage = p.message || '';
    progressClip = p.clipIndex || 0;
    progressTotal = p.totalClips || 0;
  });
}
```

### onDestroy

```typescript
onDestroy(() => {
  clearDownloadListeners();
  if (progressCleanup) { progressCleanup(); progressCleanup = null; }
});
```

## Phase: Intro

### beginSetup

```typescript
async function beginSetup() {
  phase = 'downloading';
  downloadPercent = 0;

  // Listen for download progress
  if (api?.onAvatarDownloadProgress) {
    downloadCleanups.push(api.onAvatarDownloadProgress((data) => {
      downloadPercent = data.percent;
    }));
  }
  if (api?.onAvatarDownloadComplete) {
    downloadCleanups.push(api.onAvatarDownloadComplete(() => {
      clearDownloadListeners();
      phase = 'photo';
    }));
  }
  if (api?.onAvatarDownloadError) {
    downloadCleanups.push(api.onAvatarDownloadError(() => {
      clearDownloadListeners();
      phase = 'photo';
    }));
  }

  try {
    await api?.mirrorDownloadAssets?.();
  } catch { /* non-critical */ }

  // If no assets to download, continue immediately
  if (phase === 'downloading') {
    clearDownloadListeners();
    phase = 'photo';
  }
}
```

### skipSetup

```typescript
function skipSetup() {
  (onSkip || onComplete)?.();
}
```

## Phase: Photo

### triggerFileSelect

```typescript
function triggerFileSelect() {
  fileInput?.click();
}
```

### onFileSelected

```typescript
function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  // Validate file type
  const validTypes = ['image/png', 'image/jpeg', 'image/webp'];
  if (!validTypes.includes(file.type)) {
    errorMessage = 'Use a PNG, JPG, or WebP image.';
    return;
  }

  // Validate size (max 10MB)
  if (file.size > 10 * 1024 * 1024) {
    errorMessage = 'Image must be under 10MB.';
    return;
  }

  errorMessage = '';
  photoFile = file;

  // Create preview
  const reader = new FileReader();
  reader.onload = () => {
    photoPreview = reader.result as string;
  };
  reader.readAsDataURL(file);
}
```

**Validation:**
- File type: PNG, JPEG, WebP only
- File size: Max 10MB

### clearPhoto

```typescript
function clearPhoto() {
  photoFile = null;
  photoPreview = null;
  errorMessage = '';
}
```

### uploadAndGenerate

```typescript
async function uploadAndGenerate() {
  if (!photoFile || !api) return;

  generating = true;
  errorMessage = '';
  phase = 'generating';
  startProgressListener();

  try {
    // Upload photo
    const buffer = await photoFile.arrayBuffer();
    await api.mirrorUploadPhoto(buffer, photoFile.name);

    // Generate avatar loops
    await api.mirrorGenerateAvatar();

    // Move to voice phase
    phase = 'voice';
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : 'Generation failed';
    phase = 'photo';
  } finally {
    generating = false;
    if (progressCleanup) { progressCleanup(); progressCleanup = null; }
  }
}
```

**Flow:**
1. Upload photo to main process
2. Generate avatar loops via Fal AI
3. Progress updates via listener
4. Move to voice phase on success

## Phase: Voice

### saveVoiceId

```typescript
async function saveVoiceId() {
  if (!voiceId.trim() || !api) return;

  try {
    await api.mirrorSaveVoiceId(voiceId.trim());
    phase = 'done';
    setTimeout(() => {
      onComplete?.();
    }, 2000);
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : 'Failed to save voice ID';
  }
}
```

**Purpose:** Save ElevenLabs voice ID and complete setup.

## Template Structure

```svelte
<div class="mirror-setup" data-no-drag>
  {#if phase === 'intro'}
    <div class="setup-content">
      <h2>Meet The Mirror</h2>
      <p class="setup-description">
        The Mirror reflects your digital presence. Upload a reference photo 
        to generate avatar loops, then set a voice ID for speech synthesis.
      </p>
      <div class="setup-actions">
        <button onclick={beginSetup}>Begin Setup</button>
        <button onclick={skipSetup} class="secondary">Skip for Now</button>
      </div>
    </div>

  {:else if phase === 'downloading'}
    <div class="setup-content">
      <div class="progress-spinner"></div>
      <h3>Downloading Assets</h3>
      <p>{downloadPercent}% complete</p>
      <div class="progress-bar">
        <div class="progress-fill" style="width: {downloadPercent}%"></div>
      </div>
    </div>

  {:else if phase === 'photo'}
    <div class="setup-content">
      <h3>Upload Reference Photo</h3>
      <p class="setup-description">
        Choose a clear, front-facing photo for avatar generation.
      </p>
      
      {#if photoPreview}
        <div class="photo-preview">
          <img src={photoPreview} alt="Preview" />
          <button onclick={clearPhoto}>Remove</button>
        </div>
      {:else}
        <div class="photo-upload" onclick={triggerFileSelect}>
          <p>Click to upload or drag and drop</p>
          <p class="hint">PNG, JPG, or WebP (max 10MB)</p>
        </div>
      {/if}
      
      <input 
        type="file" 
        bind:this={fileInput} 
        onchange={onFileSelected} 
        accept="image/png,image/jpeg,image/webp"
        class="file-input"
      />
      
      {#if errorMessage}
        <p class="error">{errorMessage}</p>
      {/if}
      
      <button onclick={uploadAndGenerate} disabled={!photoFile || generating}>
        {generating ? 'Generating...' : 'Generate Avatar'}
      </button>
    </div>

  {:else if phase === 'generating'}
    <div class="setup-content">
      <div class="progress-spinner"></div>
      <h3>Generating Avatar</h3>
      <p>{progressMessage}</p>
      {#if progressTotal > 0}
        <p>Clip {progressClip} of {progressTotal}</p>
      {/if}
    </div>

  {:else if phase === 'voice'}
    <div class="setup-content">
      <h3>Set Voice ID</h3>
      <p class="setup-description">
        Enter your ElevenLabs voice ID from elevenlabs.io/voices
      </p>
      <input 
        type="text" 
        bind:value={voiceId} 
        placeholder="Voice ID"
        class="voice-input"
      />
      {#if errorMessage}
        <p class="error">{errorMessage}</p>
      {/if}
      <button onclick={saveVoiceId} disabled={!voiceId.trim()}>
        Continue
      </button>
    </div>

  {:else if phase === 'done'}
    <div class="setup-content">
      <h3>Setup Complete</h3>
      <p>Starting The Mirror...</p>
    </div>
  {/if}
</div>
```

## Styling

```css
.mirror-setup {
  position: absolute;
  inset: 0;
  z-index: 70;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.9);
}

.setup-content {
  max-width: 500px;
  padding: 40px;
  text-align: center;
}

.setup-content h2, .setup-content h3 {
  font-size: 28px;
  margin: 0 0 16px 0;
  color: white;
}

.setup-description {
  color: var(--text-dim);
  margin: 0 0 24px 0;
  line-height: 1.6;
}

.setup-actions {
  display: flex;
  gap: 16px;
  justify-content: center;
}

.setup-actions button {
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
}

.setup-actions button.secondary {
  background: rgba(255, 255, 255, 0.1);
  border: none;
  color: var(--text-dim);
}

.progress-spinner {
  width: 48px;
  height: 48px;
  border: 4px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 24px;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  overflow: hidden;
  margin: 16px 0;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s ease;
}

.photo-preview {
  position: relative;
  margin: 24px auto;
  max-width: 300px;
}

.photo-preview img {
  width: 100%;
  border-radius: 12px;
}

.photo-preview button {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.7);
  border: none;
  color: white;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
}

.photo-upload {
  border: 2px dashed var(--border);
  border-radius: 12px;
  padding: 40px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.photo-upload:hover {
  border-color: var(--accent);
}

.file-input {
  display: none;
}

.voice-input {
  width: 100%;
  padding: 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: white;
  font-size: 16px;
  margin: 16px 0;
}

.error {
  color: #ff6b6b;
  margin: 16px 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/main/ipc/agents.ts` - Mirror setup IPC handlers
- `src/main/jobs/generate-avatar.ts` - Avatar generation

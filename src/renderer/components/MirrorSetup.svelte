<script lang="ts">
  /**
   * Mirror agent custom setup flow.
   *
   * Triggered when the user switches to The Mirror for the first time.
   * Flow: intro -> downloading -> photo upload -> generating -> voice -> done
   *
   * Unlike the standard wizard (which runs on first launch), this only
   * appears when switching to the Mirror agent.
   */
  import { onDestroy } from 'svelte';

  type Phase = 'intro' | 'downloading' | 'photo' | 'generating' | 'voice' | 'done';

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
  import { api } from '../api';

  let fileInput: HTMLInputElement;

  let { onComplete, onSkip }: { onComplete?: () => void; onSkip?: () => void } = $props();

  // Listen for generation progress
  let progressCleanup: (() => void) | null = null;
  let downloadCleanups: (() => void)[] = [];

  function clearDownloadListeners() {
    downloadCleanups.forEach((fn) => fn());
    downloadCleanups = [];
  }

  onDestroy(() => {
    clearDownloadListeners();
    if (progressCleanup) { progressCleanup(); progressCleanup = null; }
  });

  function startProgressListener() {
    if (!api?.onMirrorAvatarProgress) return;
    progressCleanup = api.onMirrorAvatarProgress((p: { phase: string; clipIndex?: number; totalClips?: number; message?: string }) => {
      progressMessage = p.message || '';
      progressClip = p.clipIndex || 0;
      progressTotal = p.totalClips || 0;
    });
  }

  // ---------------------------------------------------------------------------
  // Phase: intro
  // ---------------------------------------------------------------------------

  async function beginSetup() {
    // Start asset download (if agent has a release asset configured)
    phase = 'downloading';
    downloadPercent = 0;

    // Listen for download progress events
    if (api?.onAvatarDownloadProgress) {
      downloadCleanups.push(api.onAvatarDownloadProgress((data: { percent: number }) => {
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
        // Download failed or no assets to download - continue to photo
        clearDownloadListeners();
        phase = 'photo';
      }));
    }

    try {
      await api?.mirrorDownloadAssets?.();
    } catch { /* non-critical */ }

    // If download completed synchronously (no assets to download), move on
    if (phase === 'downloading') {
      clearDownloadListeners();
      phase = 'photo';
    }
  }

  function skipSetup() {
    (onSkip || onComplete)?.();
  }

  // ---------------------------------------------------------------------------
  // Phase: photo
  // ---------------------------------------------------------------------------

  function triggerFileSelect() {
    fileInput?.click();
  }

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

  function clearPhoto() {
    photoFile = null;
    photoPreview = null;
    errorMessage = '';
  }

  async function uploadAndGenerate() {
    if (!photoFile || !api) return;

    generating = true;
    errorMessage = '';
    phase = 'generating';

    try {
      // Upload photo
      const buffer = await photoFile.arrayBuffer();
      await api.mirrorUploadPhoto(buffer, photoFile.name);

      // Start generation
      startProgressListener();
      await api.mirrorGenerateAvatar();

      // Done - move to voice
      phase = 'voice';
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      errorMessage = msg;
      phase = 'photo'; // Go back to photo phase
    } finally {
      generating = false;
      if (progressCleanup) { progressCleanup(); progressCleanup = null; }
    }
  }

  // ---------------------------------------------------------------------------
  // Phase: voice
  // ---------------------------------------------------------------------------

  function openVoiceCloning() {
    api?.mirrorOpenExternal?.('https://elevenlabs.io/voice-lab');
  }

  async function saveVoice() {
    if (voiceId.trim() && api) {
      await api.mirrorSaveVoiceId(voiceId.trim());
    }
    phase = 'done';
    setTimeout(() => onComplete?.(), 2000);
  }

  function skipVoice() {
    phase = 'done';
    setTimeout(() => onComplete?.(), 2000);
  }
</script>

<div class="mirror-overlay" data-no-drag>
  <div class="mirror-content">
    {#if phase === 'intro'}
      <div class="mirror-center fade-in">
        <div class="mirror-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" opacity="0.4">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 8v8M8 12h8"/>
          </svg>
        </div>

        <h1 class="mirror-title">The Mirror</h1>
        <p class="mirror-desc">
          This agent reflects you back to yourself.
          It uses your face and your voice - not a generated persona.
        </p>

        <div class="mirror-steps">
          <div class="step-item">
            <span class="step-num">1</span>
            <span>Upload a photo of yourself</span>
          </div>
          <div class="step-item">
            <span class="step-num">2</span>
            <span>We animate it into ambient video loops</span>
          </div>
          <div class="step-item">
            <span class="step-num">3</span>
            <span>Clone your voice on ElevenLabs</span>
          </div>
        </div>

        <div class="mirror-actions">
          <button class="mirror-btn primary" onclick={beginSetup}>Begin</button>
          <button class="mirror-btn ghost" onclick={skipSetup}>Skip for now</button>
        </div>
      </div>

    {:else if phase === 'downloading'}
      <div class="mirror-center fade-in">
        <div class="generating-ring"></div>
        <h2 class="mirror-title">Preparing</h2>
        <p class="mirror-desc">Downloading avatar assets...</p>
        {#if downloadPercent > 0}
          <div class="progress-bar">
            <div class="progress-fill" style="width: {downloadPercent}%"></div>
          </div>
          <p class="progress-label">{downloadPercent}%</p>
        {/if}
      </div>

    {:else if phase === 'photo'}
      <div class="mirror-center fade-in">
        <h2 class="mirror-title">Your face</h2>
        <p class="mirror-desc">
          Upload a clear photo. Front-facing, good lighting.
          This becomes the avatar you see when talking to the Mirror.
        </p>

        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          class="hidden-input"
          bind:this={fileInput}
          onchange={onFileSelected}
        />

        {#if photoPreview}
          <div class="photo-preview-container">
            <img class="photo-preview" src={photoPreview} alt="Your photo" />
            <button class="photo-clear" onclick={clearPhoto} aria-label="Remove photo">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        {:else}
          <button class="drop-zone" onclick={triggerFileSelect}>
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <path d="m21 15-5-5L5 21"/>
            </svg>
            <span>Click to choose a photo</span>
          </button>
        {/if}

        {#if errorMessage}
          <p class="mirror-error">{errorMessage}</p>
        {/if}

        <div class="mirror-actions">
          <button
            class="mirror-btn primary"
            disabled={!photoFile}
            onclick={uploadAndGenerate}
          >Generate avatar</button>
          <button class="mirror-btn ghost" onclick={skipSetup}>Skip</button>
        </div>
      </div>

    {:else if phase === 'generating'}
      <div class="mirror-center fade-in">
        <div class="generating-ring"></div>
        <h2 class="mirror-title">Animating</h2>
        <p class="mirror-desc">{progressMessage || 'Starting...'}</p>
        {#if progressTotal > 0}
          <div class="progress-bar">
            <div class="progress-fill" style="width: {(progressClip / progressTotal) * 100}%"></div>
          </div>
          <p class="progress-label">{progressClip} / {progressTotal} clips</p>
        {/if}

        {#if errorMessage}
          <p class="mirror-error">{errorMessage}</p>
          <button class="mirror-btn ghost" onclick={() => { phase = 'photo'; errorMessage = ''; }}>
            Try again
          </button>
        {/if}
      </div>

    {:else if phase === 'voice'}
      <div class="mirror-center fade-in">
        <h2 class="mirror-title">Your voice</h2>
        <p class="mirror-desc">
          Clone your voice on ElevenLabs so the Mirror speaks as you.
          Record a sample, get a voice ID, paste it below.
        </p>

        <button class="mirror-btn voice-link" onclick={openVoiceCloning}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
            <polyline points="15 3 21 3 21 9"/>
            <line x1="10" y1="14" x2="21" y2="3"/>
          </svg>
          Open ElevenLabs Voice Lab
        </button>

        <input
          type="text"
          bind:value={voiceId}
          class="mirror-input"
          placeholder="Paste voice ID here"
        />

        <div class="mirror-actions">
          <button class="mirror-btn primary" onclick={saveVoice}>
            {voiceId.trim() ? 'Save voice' : 'Continue without voice'}
          </button>
          <button class="mirror-btn ghost" onclick={skipVoice}>Skip</button>
        </div>
      </div>

    {:else if phase === 'done'}
      <div class="mirror-center fade-in">
        <div class="done-check">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.6">
            <path d="M20 6L9 17l-5-5"/>
          </svg>
        </div>
        <h2 class="mirror-title">Ready</h2>
        <p class="mirror-desc">What is present?</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .mirror-overlay {
    position: absolute;
    inset: 0;
    z-index: 70;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg);
    overflow: hidden;
  }

  .mirror-content {
    position: relative;
    width: 100%;
    max-width: 440px;
    padding: 24px;
  }

  .mirror-center {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .fade-in {
    animation: mirrorFadeIn 0.5s ease forwards;
  }

  @keyframes mirrorFadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .mirror-icon {
    margin-bottom: 20px;
    opacity: 0.5;
  }

  .mirror-title {
    font-family: var(--font-sans);
    font-size: 22px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0 0 10px;
    letter-spacing: -0.3px;
  }

  .mirror-desc {
    font-size: 14px;
    color: var(--text-secondary);
    line-height: 1.6;
    margin: 0 0 24px;
    max-width: 360px;
  }

  /* Steps */

  .mirror-steps {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 32px;
    width: 100%;
    max-width: 300px;
  }

  .step-item {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 14px;
    color: var(--text-secondary);
    text-align: left;
  }

  .step-num {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.15);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: var(--text-dim);
    flex-shrink: 0;
  }

  /* Actions */

  .mirror-actions {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
  }

  .mirror-btn {
    padding: 10px 32px;
    border-radius: 10px;
    font-family: var(--font-sans);
    font-size: 14px;
    cursor: pointer;
    transition: background 0.15s, opacity 0.15s;
    border: none;
  }

  .mirror-btn.primary {
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-primary);
    border: 1px solid rgba(255, 255, 255, 0.12);
  }

  .mirror-btn.primary:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.12);
  }

  .mirror-btn.primary:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .mirror-btn.ghost {
    background: transparent;
    color: var(--text-dim);
    font-size: 12px;
    padding: 6px 16px;
  }

  .mirror-btn.ghost:hover {
    color: var(--text-secondary);
  }

  .mirror-btn.voice-link {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
    font-size: 13px;
  }

  .mirror-btn.voice-link:hover {
    background: rgba(255, 255, 255, 0.08);
    color: var(--text-primary);
  }

  /* Photo upload */

  .hidden-input {
    display: none;
  }

  .drop-zone {
    width: 200px;
    height: 200px;
    border: 1px dashed rgba(255, 255, 255, 0.15);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.02);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    margin-bottom: 20px;
    transition: border-color 0.2s, background 0.2s;
    color: var(--text-dim);
    font-size: 13px;
  }

  .drop-zone:hover {
    border-color: rgba(255, 255, 255, 0.25);
    background: rgba(255, 255, 255, 0.04);
  }

  .photo-preview-container {
    position: relative;
    margin-bottom: 20px;
  }

  .photo-preview {
    width: 200px;
    height: 200px;
    border-radius: 16px;
    object-fit: cover;
    border: 1px solid rgba(255, 255, 255, 0.1);
  }

  .photo-clear {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.7);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .photo-clear:hover {
    background: rgba(200, 60, 40, 0.5);
  }

  /* Input */

  .mirror-input {
    width: 100%;
    max-width: 320px;
    height: 44px;
    padding: 0 16px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 13px;
    outline: none;
    text-align: center;
    margin-bottom: 20px;
  }

  .mirror-input:focus {
    border-color: rgba(255, 255, 255, 0.2);
  }

  /* Error */

  .mirror-error {
    font-size: 13px;
    color: rgba(255, 120, 100, 0.9);
    margin: 0 0 12px;
  }

  /* Generating */

  .generating-ring {
    width: 56px;
    height: 56px;
    border: 1.5px solid rgba(255, 255, 255, 0.06);
    border-top-color: rgba(255, 255, 255, 0.3);
    border-radius: 50%;
    animation: mirrorSpin 1.2s linear infinite;
    margin-bottom: 24px;
  }

  @keyframes mirrorSpin {
    to { transform: rotate(360deg); }
  }

  .progress-bar {
    width: 200px;
    height: 3px;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 2px;
    margin-top: 16px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: rgba(255, 255, 255, 0.25);
    border-radius: 2px;
    transition: width 0.3s ease;
  }

  .progress-label {
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 8px;
  }

  /* Done */

  .done-check {
    margin-bottom: 16px;
    opacity: 0.5;
  }
</style>

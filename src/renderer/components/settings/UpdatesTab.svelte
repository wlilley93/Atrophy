<script lang="ts">
  import { api } from '../../api';

  interface Props {
    version: string;
  }

  let { version }: Props = $props();

  let bundleVersion = $state<string | null>(null);
  let hotBundleActive = $state(false);
  let updateCheckStatus = $state<'idle' | 'checking' | 'downloading' | 'ready' | 'up-to-date' | 'error'>('idle');
  let updateDownloadPercent = $state(0);
  let updateReadyVersion = $state<string | null>(null);
  let updateStatusText = $state('');
  let progressCleanup: (() => void) | null = null;
  let readyCleanup: (() => void) | null = null;

  export async function load() {
    if (!api) return;
    try {
      const status = await api.getBundleStatus();
      bundleVersion = status.hotBundleVersion;
      hotBundleActive = status.hotBundleActive;
      if (status.pending?.pendingRestart && status.pending.version) {
        updateReadyVersion = status.pending.version;
        updateCheckStatus = 'ready';
        updateStatusText = `v${status.pending.version} downloaded - restart to apply`;
      }
    } catch { /* ignore */ }

    // Listen for progress and ready events (clean up previous listeners first)
    progressCleanup?.();
    readyCleanup?.();
    progressCleanup = api.onBundleProgress?.((percent: number) => {
      updateDownloadPercent = percent;
      updateCheckStatus = 'downloading';
      updateStatusText = `Downloading... ${Math.round(percent)}%`;
    }) ?? null;
    readyCleanup = api.onBundleReady?.((info: { version: string }) => {
      updateReadyVersion = info.version;
      updateCheckStatus = 'ready';
      updateStatusText = `v${info.version} downloaded - restart to apply`;
    }) ?? null;
  }

  async function checkForUpdates() {
    if (!api) return;
    updateCheckStatus = 'checking';
    updateStatusText = 'Checking for updates...';
    updateDownloadPercent = 0;
    try {
      const newVersion = await api.checkBundleUpdate();
      if (newVersion) {
        updateReadyVersion = newVersion;
        updateCheckStatus = 'ready';
        updateStatusText = `v${newVersion} downloaded - restart to apply`;
      } else {
        updateCheckStatus = 'up-to-date';
        updateStatusText = 'Already up to date';
      }
    } catch {
      updateCheckStatus = 'error';
      updateStatusText = 'Update check failed';
    }
  }

  async function restartToApply() {
    if (!api) return;
    await api.restartForUpdate();
  }
</script>

<div class="section">
  <div class="section-header">Version</div>
  <div class="section-line"></div>

  <div class="field-row">
    <label class="field-label">App version</label>
    <span class="field-info">{version}</span>
  </div>
  {#if hotBundleActive && bundleVersion}
    <div class="field-row">
      <label class="field-label">Bundle version</label>
      <span class="field-info">{bundleVersion} (hot)</span>
    </div>
  {/if}
</div>

<div class="section">
  <div class="section-header">Bundle Updates</div>
  <div class="section-line"></div>

  {#if updateCheckStatus === 'downloading'}
    <div class="update-progress-row">
      <div class="update-progress-bar">
        <div class="update-progress-fill" style="width: {updateDownloadPercent}%"></div>
      </div>
      <span class="field-info">{Math.round(updateDownloadPercent)}%</span>
    </div>
  {/if}

  {#if updateCheckStatus === 'ready' && updateReadyVersion}
    <div class="field-row">
      <span class="update-ready-text">v{updateReadyVersion} ready to install</span>
      <button class="save-btn" onclick={restartToApply}>Restart to apply</button>
    </div>
  {:else}
    <div class="field-row">
      <button
        class="save-btn"
        disabled={updateCheckStatus === 'checking' || updateCheckStatus === 'downloading'}
        onclick={checkForUpdates}
      >
        {updateCheckStatus === 'checking' ? 'Checking...' : 'Check for updates'}
      </button>
    </div>
  {/if}

  {#if updateStatusText}
    <p class="section-hint">{updateStatusText}</p>
  {/if}
</div>

<style>
  .section {
    margin-bottom: 20px;
  }

  .section-header {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding-bottom: 4px;
  }

  .section-line {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin-bottom: 10px;
  }

  .section-hint {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.3);
    margin-top: 2px;
  }

  .field-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .field-label {
    min-width: 140px;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
  }

  .field-info {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.5);
    user-select: text;
  }

  .save-btn {
    padding: 4px 14px;
    font-size: 11px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    transition: background 0.15s;
  }

  .save-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.14);
  }

  .save-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .update-progress-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
  }

  .update-progress-bar {
    flex: 1;
    height: 6px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
    overflow: hidden;
  }

  .update-progress-fill {
    height: 100%;
    background: rgba(100, 140, 255, 0.6);
    border-radius: 3px;
    transition: width 0.3s ease;
  }

  .update-ready-text {
    color: rgba(100, 140, 255, 0.9);
    font-size: 13px;
    font-family: var(--font-sans);
  }
</style>

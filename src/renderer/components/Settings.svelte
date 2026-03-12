<script lang="ts">
  import { settings } from '../stores/settings.svelte';
  import { agents } from '../stores/agents.svelte';

  interface Props {
    onClose: () => void;
  }

  let { onClose }: Props = $props();

  type Tab = 'settings' | 'usage' | 'activity';
  let activeTab = $state<Tab>('settings');

  // Form state (populated from config)
  let userName = $state(settings.userName);
  let ttsBackend = $state(settings.ttsBackend);
  let elevenLabsKey = $state('');
  let voiceId = $state('');
  let stability = $state(0.5);
  let similarity = $state(0.75);
  let style = $state(0.35);
  let playbackRate = $state(1.12);
  let telegramToken = $state('');
  let telegramChatId = $state('');

  function apply() {
    const api = (window as any).atrophy;
    if (!api) return;
    api.updateConfig({
      USER_NAME: userName,
      TTS_BACKEND: ttsBackend,
      TTS_PLAYBACK_RATE: playbackRate,
    });
    settings.userName = userName;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }
</script>

<svelte:window on:keydown={onKeydown} />

<div class="settings-overlay" data-no-drag>
  <div class="settings-panel">
    <!-- Header -->
    <div class="settings-header">
      <div class="tabs">
        <button
          class="tab" class:active={activeTab === 'settings'}
          onclick={() => activeTab = 'settings'}
        >Settings</button>
        <button
          class="tab" class:active={activeTab === 'usage'}
          onclick={() => activeTab = 'usage'}
        >Usage</button>
        <button
          class="tab" class:active={activeTab === 'activity'}
          onclick={() => activeTab = 'activity'}
        >Activity</button>
      </div>
      <button class="close-btn" onclick={onClose}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <!-- Content -->
    <div class="settings-content">
      {#if activeTab === 'settings'}
        <!-- Agents section -->
        <div class="section">
          <div class="section-header">Agents</div>
          <div class="agent-list">
            {#each agents.list as agent}
              <div class="agent-row" class:current={agent === agents.current}>
                <span class="agent-name-label">{agent}</span>
                {#if agent !== agents.current}
                  <button class="small-btn" onclick={async () => {
                    const api = (window as any).atrophy;
                    if (api) {
                      const result = await api.switchAgent(agent);
                      agents.current = result.agentName;
                      agents.displayName = result.agentDisplayName;
                    }
                  }}>Switch</button>
                {/if}
              </div>
            {/each}
          </div>
        </div>

        <!-- Identity section -->
        <div class="section">
          <div class="section-header">Identity</div>
          <label class="field">
            <span class="field-label">Your name</span>
            <input type="text" bind:value={userName} class="field-input" />
          </label>
        </div>

        <!-- Voice section -->
        <div class="section">
          <div class="section-header">Voice</div>
          <label class="field">
            <span class="field-label">Backend</span>
            <select bind:value={ttsBackend} class="field-select">
              <option value="elevenlabs">ElevenLabs</option>
              <option value="fal">Fal</option>
              <option value="off">Off</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">ElevenLabs API Key</span>
            <input type="password" bind:value={elevenLabsKey} class="field-input" />
          </label>
          <label class="field">
            <span class="field-label">Voice ID</span>
            <input type="text" bind:value={voiceId} class="field-input" />
          </label>
          <label class="field">
            <span class="field-label">Stability</span>
            <input type="range" min="0" max="1" step="0.05" bind:value={stability} class="field-slider" />
            <span class="field-value">{stability.toFixed(2)}</span>
          </label>
          <label class="field">
            <span class="field-label">Similarity</span>
            <input type="range" min="0" max="1" step="0.05" bind:value={similarity} class="field-slider" />
            <span class="field-value">{similarity.toFixed(2)}</span>
          </label>
          <label class="field">
            <span class="field-label">Style</span>
            <input type="range" min="0" max="1" step="0.05" bind:value={style} class="field-slider" />
            <span class="field-value">{style.toFixed(2)}</span>
          </label>
          <label class="field">
            <span class="field-label">Playback rate</span>
            <input type="range" min="0.5" max="2.0" step="0.01" bind:value={playbackRate} class="field-slider" />
            <span class="field-value">{playbackRate.toFixed(2)}x</span>
          </label>
        </div>

        <!-- Telegram section -->
        <div class="section">
          <div class="section-header">Telegram</div>
          <label class="field">
            <span class="field-label">Bot Token</span>
            <input type="password" bind:value={telegramToken} class="field-input" />
          </label>
          <label class="field">
            <span class="field-label">Chat ID</span>
            <input type="text" bind:value={telegramChatId} class="field-input" />
          </label>
        </div>

        <!-- Actions -->
        <div class="actions">
          <button class="action-btn primary" onclick={apply}>Apply</button>
        </div>

      {:else if activeTab === 'usage'}
        <div class="section">
          <div class="section-header">Token Usage</div>
          <p class="placeholder">Usage tracking will be shown here</p>
        </div>

      {:else if activeTab === 'activity'}
        <div class="section">
          <div class="section-header">Activity Log</div>
          <p class="placeholder">Tool calls, heartbeats, and events will be shown here</p>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .settings-overlay {
    position: absolute;
    inset: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(8px);
  }

  .settings-panel {
    width: 90%;
    max-width: 520px;
    max-height: 80%;
    background: rgba(20, 20, 24, 0.98);
    border: 1px solid var(--border);
    border-radius: 16px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .settings-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }

  .tabs {
    display: flex;
    gap: 0;
  }

  .tab {
    padding: 6px 16px;
    border: none;
    background: transparent;
    color: var(--text-dim);
    font-family: var(--font-sans);
    font-size: 13px;
    cursor: pointer;
    border-radius: 6px;
    transition: color 0.15s, background 0.15s;
  }

  .tab:hover {
    color: var(--text-secondary);
  }

  .tab.active {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.06);
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px;
  }

  .close-btn:hover {
    color: var(--text-secondary);
  }

  .settings-content {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
  }

  .section {
    margin-bottom: 28px;
  }

  .agent-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .agent-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.02);
  }

  .agent-row.current {
    background: rgba(100, 140, 255, 0.08);
  }

  .agent-name-label {
    font-size: 13px;
    text-transform: capitalize;
  }

  .small-btn {
    padding: 4px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--text-secondary);
    font-size: 11px;
    cursor: pointer;
    transition: border-color 0.15s;
  }

  .small-btn:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
  }

  .field {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }

  .field-label {
    min-width: 120px;
    font-size: 12px;
    color: var(--text-secondary);
  }

  .field-input, .field-select {
    flex: 1;
    height: 32px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 12px;
    outline: none;
  }

  .field-input:focus, .field-select:focus {
    border-color: var(--border-hover);
  }

  .field-select {
    appearance: none;
    cursor: pointer;
  }

  .field-slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
    outline: none;
  }

  .field-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.7);
    cursor: pointer;
  }

  .field-value {
    min-width: 40px;
    font-size: 11px;
    font-family: var(--font-mono);
    color: var(--text-dim);
    text-align: right;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }

  .action-btn {
    padding: 8px 20px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .action-btn.primary {
    background: rgba(100, 140, 255, 0.15);
    border-color: rgba(100, 140, 255, 0.3);
  }

  .action-btn:hover {
    background: rgba(255, 255, 255, 0.06);
  }

  .action-btn.primary:hover {
    background: rgba(100, 140, 255, 0.25);
  }

  .placeholder {
    color: var(--text-dim);
    font-size: 13px;
    text-align: center;
    padding: 40px 0;
  }
</style>

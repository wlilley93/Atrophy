<script lang="ts">
  import { agents } from '../../stores/agents.svelte';
  import { api } from '../../api';

  interface Props {
    agentList: { name: string; display_name: string; description: string; role: string }[];
    userName: string;
    agentDisplayName: string;
    wakeWords: string;
    disabledTools: Set<string>;
    windowWidth: number;
    windowHeight: number;
    avatarEnabled: boolean;
    avatarResolution: number;
    ttsBackend: string;
    elevenlabsApiKey: string;
    elevenlabsVoiceId: string;
    elevenlabsModel: string;
    elevenlabsStability: number;
    elevenlabsSimilarity: number;
    elevenlabsStyle: number;
    ttsPlaybackRate: number;
    falApiKey: string;
    falVoiceId: string;
    inputMode: string;
    pttKey: string;
    wakeWordEnabled: boolean;
    wakeChunkSeconds: number;
    silenceTimerEnabled: boolean;
    silenceTimerMinutes: number;
    eyeModeDefault: boolean;
    muteByDefault: boolean;
    keepAwakeActive: boolean;
    notificationsEnabled: boolean;
    sampleRate: number;
    maxRecordSec: number;
    claudeBin: string;
    claudeModel: string;
    claudeEffort: string;
    adaptiveEffort: boolean;
    contextSummaries: number;
    maxContextTokens: number;
    vectorSearchWeight: number;
    embeddingModel: string;
    embeddingDim: number;
    sessionSoftLimitMins: number;
    heartbeatActiveStart: number;
    heartbeatActiveEnd: number;
    heartbeatIntervalMins: number;
    obsidianVault: string;
    dbPath: string;
    whisperBin: string;
    googleConfigured: boolean;
    googleAuthStatus: string;
    telegramBotToken: string;
    telegramChatId: string;
    telegramDaemonRunning: boolean;
    version: string;
    bundleRoot: string;
    saveStatus: string;
    onClose: () => void;
    onApply: () => void;
    onSave: () => void;
    onResetSetup: () => void;
  }

  let {
    agentList = $bindable(),
    userName = $bindable(),
    agentDisplayName = $bindable(),
    wakeWords = $bindable(),
    disabledTools = $bindable(),
    windowWidth = $bindable(),
    windowHeight = $bindable(),
    avatarEnabled = $bindable(),
    avatarResolution = $bindable(),
    ttsBackend = $bindable(),
    elevenlabsApiKey = $bindable(),
    elevenlabsVoiceId = $bindable(),
    elevenlabsModel = $bindable(),
    elevenlabsStability = $bindable(),
    elevenlabsSimilarity = $bindable(),
    elevenlabsStyle = $bindable(),
    ttsPlaybackRate = $bindable(),
    falApiKey = $bindable(),
    falVoiceId = $bindable(),
    inputMode = $bindable(),
    pttKey = $bindable(),
    wakeWordEnabled = $bindable(),
    wakeChunkSeconds = $bindable(),
    silenceTimerEnabled = $bindable(),
    silenceTimerMinutes = $bindable(),
    eyeModeDefault = $bindable(),
    muteByDefault = $bindable(),
    keepAwakeActive = $bindable(),
    notificationsEnabled = $bindable(),
    sampleRate = $bindable(),
    maxRecordSec = $bindable(),
    claudeBin = $bindable(),
    claudeModel = $bindable(),
    claudeEffort = $bindable(),
    adaptiveEffort = $bindable(),
    contextSummaries = $bindable(),
    maxContextTokens = $bindable(),
    vectorSearchWeight = $bindable(),
    embeddingModel = $bindable(),
    embeddingDim = $bindable(),
    sessionSoftLimitMins = $bindable(),
    heartbeatActiveStart = $bindable(),
    heartbeatActiveEnd = $bindable(),
    heartbeatIntervalMins = $bindable(),
    obsidianVault = $bindable(),
    dbPath,
    whisperBin,
    googleConfigured,
    googleAuthStatus,
    telegramBotToken = $bindable(),
    telegramChatId = $bindable(),
    telegramDaemonRunning = $bindable(),
    version,
    bundleRoot,
    saveStatus,
    onClose,
    onApply,
    onSave,
    onResetSetup,
  }: Props = $props();

  const toggleableTools = [
    ['mcp__memory__defer_to_agent', 'Agent deferral'],
    ['mcp__memory__send_telegram', 'Telegram messaging'],
    ['mcp__memory__set_reminder', 'Reminders'],
    ['mcp__memory__set_timer', 'Timers'],
    ['mcp__memory__create_task', 'Task scheduling'],
    ['mcp__memory__render_canvas', 'Canvas overlay'],
    ['mcp__memory__write_note', 'Write Obsidian notes'],
    ['mcp__memory__prompt_journal', 'Journal prompting'],
    ['mcp__memory__update_emotional_state', 'Emotional state'],
    ['mcp__memory__create_artefact', 'Artefact creation'],
    ['mcp__memory__manage_schedule', 'Schedule management'],
    ['mcp__puppeteer__*', 'Browser (Puppeteer)'],
    ['mcp__fal__*', 'Media generation (fal)'],
  ] as const;

  // Password visibility toggles
  let showElevenlabsKey = $state(false);
  let showFalKey = $state(false);
  let showTelegramToken = $state(false);

  // Telegram discovery
  let telegramDiscovering = $state(false);
  let telegramDiscoverStatus = $state('');

</script>

<div class="settings-form">

<!-- YOU -->
<div class="section full-width">
  <div class="section-header">You</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Your Name</span>
    <input type="text" bind:value={userName} class="field-input" />
  </label>
</div>

<!-- AGENT IDENTITY -->
<div class="section">
  <div class="section-header">Agent Identity</div>
  <div class="section-line"></div>
  <div class="field">
    <span class="field-label">Agent Slug</span>
    <span class="field-info">{agents.current}</span>
  </div>
  <label class="field">
    <span class="field-label">Display Name</span>
    <input type="text" bind:value={agentDisplayName} class="field-input" />
  </label>
  <label class="field">
    <span class="field-label">Wake Words</span>
    <input type="text" bind:value={wakeWords} class="field-input" placeholder="hey xan, xan" />
  </label>
</div>

<!-- TOOLS -->
<div class="section">
  <div class="section-header">Tools</div>
  <div class="section-line"></div>
  {#each toggleableTools as [toolId, label]}
    <label class="checkbox-row">
      <input
        type="checkbox"
        checked={!disabledTools.has(toolId)}
        onchange={() => {
          const next = new Set(disabledTools);
          if (next.has(toolId)) next.delete(toolId);
          else next.add(toolId);
          disabledTools = next;
        }}
      />
      <span>{label}</span>
    </label>
  {/each}
</div>

<!-- WINDOW -->
<div class="section">
  <div class="section-header">Window</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Width</span>
    <input type="number" min="300" max="1920" bind:value={windowWidth} class="field-input short" />
    <span class="field-suffix">px</span>
  </label>
  <label class="field">
    <span class="field-label">Height</span>
    <input type="number" min="400" max="1080" bind:value={windowHeight} class="field-input short" />
    <span class="field-suffix">px</span>
  </label>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={avatarEnabled} />
    <span>Avatar Enabled</span>
  </label>
  <label class="field">
    <span class="field-label">Avatar Resolution</span>
    <input type="number" min="128" max="1024" bind:value={avatarResolution} class="field-input short" />
  </label>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={eyeModeDefault} />
    <span>Eye Mode by default (hide transcript)</span>
  </label>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={silenceTimerEnabled} />
    <span>Silence timer ("Still here?" prompt)</span>
  </label>
  {#if silenceTimerEnabled}
    <label class="field">
      <span class="field-label">Silence Timeout</span>
      <input type="number" min="1" max="60" bind:value={silenceTimerMinutes} class="field-input short" />
      <span class="field-suffix">min</span>
    </label>
  {/if}
</div>

<!-- VOICE & TTS -->
<div class="section full-width">
  <div class="section-header">Voice & TTS</div>
  <div class="section-line"></div>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={muteByDefault} />
    <span>Mute TTS by default</span>
  </label>
  <label class="field">
    <span class="field-label">TTS Backend</span>
    <select bind:value={ttsBackend} class="field-select">
      <option value="elevenlabs">ElevenLabs</option>
      <option value="fal">Fal</option>
      <option value="none">None</option>
    </select>
  </label>
  <div class="field">
    <span class="field-label">ElevenLabs API Key</span>
    <div class="input-eye-wrap">
      <input type={showElevenlabsKey ? 'text' : 'password'} bind:value={elevenlabsApiKey} class="field-input has-eye" />
      <button class="eye-toggle" type="button" onclick={() => showElevenlabsKey = !showElevenlabsKey} aria-label={showElevenlabsKey ? 'Hide' : 'Show'}>
        {#if showElevenlabsKey}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>
        {:else}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
        {/if}
      </button>
    </div>
  </div>
  <label class="field">
    <span class="field-label">ElevenLabs Voice ID</span>
    <input type="text" bind:value={elevenlabsVoiceId} class="field-input" />
  </label>
  <label class="field">
    <span class="field-label">ElevenLabs Model</span>
    <select bind:value={elevenlabsModel} class="field-select">
      <option value="eleven_v3">eleven_v3</option>
      <option value="eleven_v2">eleven_v2</option>
      <option value="eleven_multilingual_v2">eleven_multilingual_v2</option>
      <option value="eleven_turbo_v2_5">eleven_turbo_v2_5</option>
      <option value="eleven_flash_v2_5">eleven_flash_v2_5</option>
    </select>
  </label>
  <label class="field">
    <span class="field-label">Stability</span>
    <input type="range" min="0" max="1" step="0.05" bind:value={elevenlabsStability} class="field-slider" />
    <span class="field-value">{elevenlabsStability.toFixed(2)}</span>
  </label>
  <label class="field">
    <span class="field-label">Similarity</span>
    <input type="range" min="0" max="1" step="0.05" bind:value={elevenlabsSimilarity} class="field-slider" />
    <span class="field-value">{elevenlabsSimilarity.toFixed(2)}</span>
  </label>
  <label class="field">
    <span class="field-label">Style</span>
    <input type="range" min="0" max="1" step="0.05" bind:value={elevenlabsStyle} class="field-slider" />
    <span class="field-value">{elevenlabsStyle.toFixed(2)}</span>
  </label>
  <label class="field">
    <span class="field-label">Playback Rate</span>
    <input type="range" min="0.5" max="2.0" step="0.01" bind:value={ttsPlaybackRate} class="field-slider" />
    <span class="field-value">{ttsPlaybackRate.toFixed(2)}x</span>
  </label>
  <div class="field">
    <span class="field-label">Fal API Key</span>
    <div class="input-eye-wrap">
      <input type={showFalKey ? 'text' : 'password'} bind:value={falApiKey} class="field-input has-eye" />
      <button class="eye-toggle" type="button" onclick={() => showFalKey = !showFalKey} aria-label={showFalKey ? 'Hide' : 'Show'}>
        {#if showFalKey}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>
        {:else}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
        {/if}
      </button>
    </div>
  </div>
  <label class="field">
    <span class="field-label">Fal Voice ID</span>
    <input type="text" bind:value={falVoiceId} class="field-input" />
  </label>
</div>

<!-- INPUT -->
<div class="section">
  <div class="section-header">Input</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Input Mode</span>
    <select bind:value={inputMode} class="field-select">
      <option value="dual">Dual</option>
      <option value="voice">Voice</option>
      <option value="text">Text</option>
    </select>
  </label>
  <label class="field">
    <span class="field-label">Push-to-Talk Key</span>
    <input type="text" bind:value={pttKey} class="field-input" />
  </label>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={wakeWordEnabled} />
    <span>Wake Word Detection</span>
  </label>
  <label class="field">
    <span class="field-label">Wake Chunk Duration</span>
    <input type="number" min="1" max="10" bind:value={wakeChunkSeconds} class="field-input short" />
    <span class="field-suffix">sec</span>
  </label>
</div>

<!-- KEEP AWAKE -->
<div class="section">
  <div class="section-header">Keep Awake</div>
  <div class="section-line"></div>
  <div class="field row">
    <span class="field-label">Prevent Sleep</span>
    <div class="daemon-control">
      <span class="daemon-status" class:active={keepAwakeActive}>
        {keepAwakeActive ? 'Active' : 'Off'}
      </span>
      <button
        class="daemon-btn"
        onclick={async () => {
          const result = await api?.toggleKeepAwake();
          keepAwakeActive = !!result;
        }}
      >
        {keepAwakeActive ? 'Disable' : 'Enable'}
      </button>
    </div>
  </div>
  <div class="section-hint">Prevents display and system sleep while the app is running.</div>
</div>

<!-- NOTIFICATIONS -->
<div class="section">
  <div class="section-header">Notifications</div>
  <div class="section-line"></div>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={notificationsEnabled} />
    <span>macOS Notifications</span>
  </label>
</div>

<!-- AUDIO CAPTURE -->
<div class="section">
  <div class="section-header">Audio Capture</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Sample Rate</span>
    <input type="number" min="8000" max="48000" bind:value={sampleRate} class="field-input short" />
    <span class="field-suffix">Hz</span>
  </label>
  <label class="field">
    <span class="field-label">Max Record Duration</span>
    <input type="number" min="10" max="300" bind:value={maxRecordSec} class="field-input short" />
    <span class="field-suffix">sec</span>
  </label>
</div>

<!-- INFERENCE -->
<div class="section">
  <div class="section-header">Inference</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Claude Binary</span>
    <input type="text" bind:value={claudeBin} class="field-input" />
  </label>
  <label class="field">
    <span class="field-label">Model</span>
    <select bind:value={claudeModel} class="field-select">
      <option value="claude-sonnet-4-6">Sonnet 4.6</option>
      <option value="claude-opus-4-6">Opus 4.6</option>
      <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
      <option value="claude-sonnet-4-5-20241022">Sonnet 4.5</option>
    </select>
  </label>
  <label class="field">
    <span class="field-label">Effort</span>
    <select bind:value={claudeEffort} class="field-select">
      <option value="low">Low</option>
      <option value="medium">Medium</option>
      <option value="high">High</option>
    </select>
  </label>
  <label class="checkbox-row">
    <input type="checkbox" bind:checked={adaptiveEffort} />
    <span>Adaptive Effort</span>
  </label>
</div>

<!-- MEMORY & CONTEXT -->
<div class="section full-width">
  <div class="section-header">Memory & Context</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Context Summaries</span>
    <input type="number" min="0" max="20" bind:value={contextSummaries} class="field-input short" />
  </label>
  <label class="field">
    <span class="field-label">Max Context Tokens</span>
    <input type="number" min="10000" max="500000" step="10000" bind:value={maxContextTokens} class="field-input short" />
  </label>
  <label class="field">
    <span class="field-label">Vector Search Weight</span>
    <input type="range" min="0" max="1" step="0.05" bind:value={vectorSearchWeight} class="field-slider" />
    <span class="field-value">{vectorSearchWeight.toFixed(2)}</span>
  </label>
  <label class="field">
    <span class="field-label">Embedding Model</span>
    <input type="text" bind:value={embeddingModel} class="field-input" />
  </label>
  <label class="field">
    <span class="field-label">Embedding Dimensions</span>
    <input type="number" min="64" max="2048" bind:value={embeddingDim} class="field-input short" />
  </label>
</div>

<!-- SESSION -->
<div class="section">
  <div class="section-header">Session</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Soft Limit</span>
    <input type="number" min="10" max="480" bind:value={sessionSoftLimitMins} class="field-input short" />
    <span class="field-suffix">min</span>
  </label>
</div>

<!-- HEARTBEAT -->
<div class="section">
  <div class="section-header">Heartbeat</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Active Start Hour</span>
    <input type="number" min="0" max="23" bind:value={heartbeatActiveStart} class="field-input short" />
    <span class="field-suffix">h</span>
  </label>
  <label class="field">
    <span class="field-label">Active End Hour</span>
    <input type="number" min="0" max="23" bind:value={heartbeatActiveEnd} class="field-input short" />
    <span class="field-suffix">h</span>
  </label>
  <label class="field">
    <span class="field-label">Interval</span>
    <input type="number" min="5" max="120" bind:value={heartbeatIntervalMins} class="field-input short" />
    <span class="field-suffix">min</span>
  </label>
</div>

<!-- PATHS -->
<div class="section full-width">
  <div class="section-header">Paths</div>
  <div class="section-line"></div>
  <label class="field">
    <span class="field-label">Obsidian Vault</span>
    <input type="text" bind:value={obsidianVault} class="field-input" />
  </label>
  <div class="field">
    <span class="field-label">Database</span>
    <span class="field-info mono">{dbPath}</span>
  </div>
  <div class="field">
    <span class="field-label">Whisper Binary</span>
    <span class="field-info mono">{whisperBin}</span>
  </div>
</div>

<!-- GOOGLE -->
<div class="section">
  <div class="section-header">Google</div>
  <div class="section-line"></div>
  <div class="field">
    <span class="field-label">Status</span>
    <span class="field-info" class:connected={googleConfigured}>
      {googleConfigured ? 'Connected' : 'Not connected'}
    </span>
  </div>
  {#if googleAuthStatus}
    <div class="field">
      <span class="field-label"></span>
      <span class="field-info">{googleAuthStatus}</span>
    </div>
  {/if}
</div>

<!-- TELEGRAM -->
<div class="section full-width">
  <div class="section-header">Telegram</div>
  <div class="section-line"></div>
  <div class="field">
    <span class="field-label">Bot Token</span>
    <div class="input-eye-wrap">
      <input type={showTelegramToken ? 'text' : 'password'} bind:value={telegramBotToken} class="field-input has-eye" />
      <button class="eye-toggle" type="button" onclick={() => showTelegramToken = !showTelegramToken} aria-label={showTelegramToken ? 'Hide' : 'Show'}>
        {#if showTelegramToken}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>
        {:else}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
        {/if}
      </button>
    </div>
  </div>
  <label class="field">
    <span class="field-label">Chat ID</span>
    <input type="text" bind:value={telegramChatId} class="field-input" />
  </label>
  {#if telegramBotToken && telegramBotToken !== '***' && !telegramChatId}
    <div class="field row">
      <span class="field-label"></span>
      <div class="daemon-control">
        <span class="field-info">{telegramDiscoverStatus || 'Send any message to the bot to link'}</span>
        <button
          class="daemon-btn"
          disabled={telegramDiscovering}
          onclick={async () => {
            telegramDiscovering = true;
            telegramDiscoverStatus = 'Waiting for message...';
            const result = await api?.discoverTelegramChatId(telegramBotToken);
            telegramDiscovering = false;
            if (result) {
              telegramChatId = result.chatId;
              telegramDiscoverStatus = `Linked${result.username ? ` (@${result.username})` : ''}`;
            } else {
              telegramDiscoverStatus = 'Timed out - try again';
            }
          }}
        >
          {telegramDiscovering ? 'Listening...' : 'Auto-detect'}
        </button>
      </div>
    </div>
  {/if}
  <div class="field row">
    <span class="field-label">Polling Daemon</span>
    <div class="daemon-control">
      <span class="daemon-status" class:active={telegramDaemonRunning}>
        {telegramDaemonRunning ? 'Running' : 'Stopped'}
      </span>
      <button
        class="daemon-btn"
        onclick={async () => {
          if (telegramDaemonRunning) {
            await api?.stopTelegramDaemon();
            telegramDaemonRunning = false;
          } else {
            const ok = await api?.startTelegramDaemon();
            telegramDaemonRunning = !!ok;
          }
        }}
      >
        {telegramDaemonRunning ? 'Stop' : 'Start'}
      </button>
    </div>
  </div>
</div>

<!-- ABOUT -->
<div class="section full-width">
  <div class="section-header">About</div>
  <div class="section-line"></div>
  <div class="field">
    <span class="field-label">Version</span>
    <span class="field-info">{version}</span>
  </div>
  <div class="field">
    <span class="field-label">Install Path</span>
    <span class="field-info mono">{bundleRoot}</span>
  </div>
</div>

<!-- APP -->
<div class="section">
  <div class="section-header">App</div>
  <div class="section-line"></div>
  <div class="field row">
    <span class="field-label">Reset Setup Wizard</span>
    <button
      class="small-btn danger-btn"
      onclick={onResetSetup}
    >Reset Setup</button>
  </div>
</div>

<!-- ACTIONS -->
<div class="actions full-width">
  {#if saveStatus}
    <span class="save-status">{saveStatus}</span>
  {/if}
  <button class="action-btn" onclick={onApply}>Apply</button>
  <button class="action-btn primary" onclick={onSave}>Save</button>
</div>

</div><!-- end settings-form -->

<style>
  .settings-form {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0;
    align-items: start;
  }

  @media (min-width: 700px) {
    .settings-form {
      grid-template-columns: 1fr 1fr;
      gap: 0 24px;
    }
  }

  .section {
    margin-bottom: 20px;
  }

  .section.full-width,
  .actions.full-width {
    grid-column: 1 / -1;
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

  .agent-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .agent-row {
    display: flex;
    flex-direction: column;
    padding: 8px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.02);
  }

  .agent-row.current {
    background: rgba(100, 140, 255, 0.08);
  }

  .agent-row-main {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .agent-detail-btn {
    font-size: 11px;
    padding: 2px 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 0.15s;
  }

  .agent-detail-btn:hover {
    background: var(--accent);
  }

  .agent-detail-btn.active {
    background: var(--accent);
    border-color: rgba(100, 140, 255, 0.4);
    color: rgba(255, 255, 255, 0.8);
  }

  .agent-detail-panel {
    padding: 8px 0 4px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .detail-group {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .detail-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  .detail-value {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
  }

  .detail-dim {
    color: rgba(255, 255, 255, 0.25);
    font-size: 11px;
    font-style: italic;
  }

  .detail-pills {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }

  .detail-pill {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.3);
  }

  .detail-pill.active {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.6);
  }

  .detail-jobs {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .detail-job-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .detail-job-name {
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
  }

  .detail-job-schedule {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    font-family: var(--font-mono);
  }

  .agent-telegram-btn {
    font-size: 11px;
    padding: 2px 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 0.15s;
  }

  .agent-telegram-btn:hover {
    background: var(--accent);
  }

  .agent-telegram-btn.active {
    background: var(--accent);
    border-color: rgba(100, 140, 255, 0.4);
    color: rgba(255, 255, 255, 0.8);
  }

  .agent-telegram-config {
    padding: 8px 0 4px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .agent-telegram-config .field-input {
    font-size: 12px;
  }

  .agent-info {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .agent-name-label {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.6);
  }

  .agent-name-label.bold {
    color: rgba(255, 255, 255, 0.95);
    font-weight: bold;
  }

  .agent-role {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.3);
  }

  .agent-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .notify-via-select {
    height: 24px;
    padding: 0 6px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
    cursor: pointer;
  }

  .notify-via-select:focus {
    border-color: rgba(255, 255, 255, 0.25);
  }

  .notify-via-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }

  .agent-active-label {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
  }

  .small-btn {
    padding: 4px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--text-secondary);
    font-size: 11px;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
  }

  .small-btn:hover {
    border-color: rgba(255, 255, 255, 0.25);
    color: var(--text-primary);
  }

  .danger-btn {
    border-color: rgba(255, 80, 80, 0.3);
    color: rgba(255, 80, 80, 0.7);
  }

  .danger-btn:hover {
    border-color: rgba(255, 80, 80, 0.5);
    color: rgba(255, 80, 80, 0.9);
    background: rgba(255, 80, 80, 0.08);
  }

  .field {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
    min-width: 0;
    max-width: 100%;
  }

  .field-label {
    min-width: 140px;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
  }

  .field-input {
    flex: 1;
    min-width: 0;
    height: 30px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 12px;
    outline: none;
    transition: border-color 0.15s;
    box-sizing: border-box;
  }

  .field-input:focus {
    border-color: rgba(255, 255, 255, 0.25);
  }

  .field-input.has-eye {
    padding-right: 36px;
  }

  .input-eye-wrap {
    position: relative;
    flex: 1;
  }

  .input-eye-wrap .field-input {
    width: 100%;
  }

  .eye-toggle {
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    width: 26px;
    height: 26px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-dim);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s, background 0.15s;
    padding: 0;
  }

  .eye-toggle:hover {
    color: var(--text-secondary);
    background: rgba(255, 255, 255, 0.06);
  }

  .field.row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .daemon-control {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .daemon-status {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.4);
  }

  .daemon-status.active {
    color: rgba(80, 200, 120, 0.9);
  }

  .daemon-btn {
    padding: 4px 14px;
    font-size: 11px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    transition: background 0.15s;
  }

  .daemon-btn:hover {
    background: rgba(255, 255, 255, 0.14);
  }

  .field-input.short {
    flex: 0;
    width: 100px;
  }

  .field-select {
    height: 30px;
    min-width: 140px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 12px;
    outline: none;
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='rgba(255,255,255,0.4)' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 10px center;
    padding-right: 28px;
  }

  .field-select:focus {
    border-color: rgba(255, 255, 255, 0.25);
  }

  .field-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }

  .field-suffix {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.4);
    min-width: 24px;
  }

  .field-info {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.5);
    user-select: text;
  }

  .field-info.mono {
    font-family: var(--font-mono);
    font-size: 11px;
    word-break: break-all;
  }

  .field-info.connected {
    color: rgba(100, 220, 100, 0.7);
  }

  .field-slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255, 255, 255, 0.15);
    border-radius: 2px;
    outline: none;
  }

  .field-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.8);
    cursor: pointer;
  }

  .field-value {
    min-width: 40px;
    font-size: 11px;
    font-family: var(--font-mono);
    color: rgba(255, 255, 255, 0.6);
    text-align: right;
  }

  .checkbox-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
    cursor: pointer;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
    padding-left: 4px;
  }

  .checkbox-row input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: rgba(100, 140, 255, 0.6);
    cursor: pointer;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    margin-top: 8px;
  }

  .save-status {
    font-size: 12px;
    color: rgba(100, 220, 100, 0.7);
    margin-right: auto;
  }

  .action-btn {
    padding: 8px 20px;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.12);
    color: rgba(255, 255, 255, 0.9);
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: bold;
    cursor: pointer;
    transition: background 0.15s;
  }

  .action-btn:hover {
    background: rgba(255, 255, 255, 0.18);
  }

  .action-btn.primary {
    background: rgba(100, 140, 255, 0.15);
    border-color: rgba(100, 140, 255, 0.3);
  }

  .action-btn.primary:hover {
    background: rgba(100, 140, 255, 0.25);
  }
</style>

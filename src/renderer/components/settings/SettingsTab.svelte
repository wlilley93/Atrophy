<script lang="ts">
  import { agents } from '../../stores/agents.svelte';
  import { api } from '../../api';

  interface Props {
    page: 'general' | 'voice' | 'input' | 'engine' | 'telegram' | 'connections' | 'about';
    agentList: { name: string; display_name: string; description: string; role: string }[];
    userName: string;
    agentDisplayName: string;
    wakeWords: string;
    disabledTools: Set<string>;
    windowWidth: number;
    windowHeight: number;
    settingsWindowWidth: number;
    settingsWindowHeight: number;
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
    telegramUsername: string;
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
    page,
    agentList = $bindable(),
    userName = $bindable(),
    agentDisplayName = $bindable(),
    wakeWords = $bindable(),
    disabledTools = $bindable(),
    windowWidth = $bindable(),
    windowHeight = $bindable(),
    settingsWindowWidth = $bindable(),
    settingsWindowHeight = $bindable(),
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
    telegramUsername = $bindable(),
    telegramDaemonRunning = $bindable(),
    version,
    bundleRoot,
    saveStatus,
    onClose,
    onApply,
    onSave,
    onResetSetup,
  }: Props = $props();

  // ── Toggleable tools list ─────────────────────────────────
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

  // ── Accordion state ───────────────────────────────────────
  let collapsed = $state<Set<string>>(new Set());
  function toggleSection(id: string) {
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    collapsed = next;
  }

  // ── Password visibility ───────────────────────────────────
  let showElevenlabsKey = $state(false);
  let showFalKey = $state(false);
  let showTelegramToken = $state(false);

  // ── Telegram discovery ────────────────────────────────────
  let telegramDiscovering = $state(false);
  let telegramDiscoverStatus = $state('');

  // ── Page titles ───────────────────────────────────────────
  const PAGE_TITLES: Record<string, string> = {
    general: 'General',
    voice: 'Voice & TTS',
    input: 'Input & Audio',
    engine: 'Inference & Memory',
    telegram: 'Telegram',
    connections: 'Services & Paths',
    about: 'About',
  };
</script>

<div class="settings-page">

  <h2 class="page-title">{PAGE_TITLES[page] ?? ''}</h2>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- GENERAL PAGE                                            -->
  <!-- ════════════════════════════════════════════════════════ -->
  {#if page === 'general'}

    <!-- You -->
    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('you')}>
        <span>You</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('you')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('you')}
        <div class="section-body">
          <div class="field-group">
            <label class="field-label" for="user-name">Your Name</label>
            <input id="user-name" type="text" bind:value={userName} class="field-input" />
          </div>
        </div>
      {/if}
    </section>

    <!-- Agent Identity -->
    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('identity')}>
        <span>Agent Identity</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('identity')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('identity')}
        <div class="section-body">
          <div class="field-group">
            <span class="field-label">Agent Slug</span>
            <span class="field-info">{agents.current}</span>
          </div>
          <div class="field-group">
            <label class="field-label" for="display-name">Display Name</label>
            <input id="display-name" type="text" bind:value={agentDisplayName} class="field-input" />
          </div>
          <div class="field-group">
            <label class="field-label" for="wake-words">Wake Words</label>
            <input id="wake-words" type="text" bind:value={wakeWords} class="field-input" placeholder="hey xan, xan" />
          </div>
        </div>
      {/if}
    </section>

    <!-- Tools -->
    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('tools')}>
        <span>Tools</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('tools')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('tools')}
        <div class="section-body">
          {#each toggleableTools as [toolId, label]}
            <label class="toggle-row">
              <span class="toggle-label">{label}</span>
              <button
                class="toggle-switch"
                class:on={!disabledTools.has(toolId)}
                onclick={() => {
                  const next = new Set(disabledTools);
                  if (next.has(toolId)) next.delete(toolId);
                  else next.add(toolId);
                  disabledTools = next;
                }}
                role="switch"
                aria-checked={!disabledTools.has(toolId)}
              >
                <span class="toggle-track"><span class="toggle-thumb"></span></span>
              </button>
            </label>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Window & Display -->
    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('window')}>
        <span>Window & Display</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('window')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('window')}
        <div class="section-body">
          <div class="field-row-inline">
            <div class="field-group compact">
              <label class="field-label" for="win-w">Main Width</label>
              <div class="input-with-suffix">
                <input id="win-w" type="number" min="300" max="2560" bind:value={windowWidth} class="field-input" />
                <span class="input-suffix">px</span>
              </div>
            </div>
            <div class="field-group compact">
              <label class="field-label" for="win-h">Main Height</label>
              <div class="input-with-suffix">
                <input id="win-h" type="number" min="400" max="1600" bind:value={windowHeight} class="field-input" />
                <span class="input-suffix">px</span>
              </div>
            </div>
          </div>
          <div class="field-row-inline">
            <div class="field-group compact">
              <label class="field-label" for="set-w">Settings Width</label>
              <div class="input-with-suffix">
                <input id="set-w" type="number" min="600" max="2560" bind:value={settingsWindowWidth} class="field-input" />
                <span class="input-suffix">px</span>
              </div>
            </div>
            <div class="field-group compact">
              <label class="field-label" for="set-h">Settings Height</label>
              <div class="input-with-suffix">
                <input id="set-h" type="number" min="500" max="1600" bind:value={settingsWindowHeight} class="field-input" />
                <span class="input-suffix">px</span>
              </div>
            </div>
          </div>
          <label class="toggle-row">
            <span class="toggle-label">Avatar</span>
            <button class="toggle-switch" class:on={avatarEnabled} onclick={() => avatarEnabled = !avatarEnabled} role="switch" aria-checked={avatarEnabled}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
          {#if avatarEnabled}
            <div class="field-group">
              <label class="field-label" for="avatar-res">Avatar Resolution</label>
              <div class="input-with-suffix">
                <input id="avatar-res" type="number" min="128" max="1024" bind:value={avatarResolution} class="field-input" />
                <span class="input-suffix">px</span>
              </div>
            </div>
          {/if}
          <label class="toggle-row">
            <span class="toggle-label">Eye Mode by default</span>
            <button class="toggle-switch" class:on={eyeModeDefault} onclick={() => eyeModeDefault = !eyeModeDefault} role="switch" aria-checked={eyeModeDefault}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
          <label class="toggle-row">
            <span class="toggle-label">Silence timer</span>
            <button class="toggle-switch" class:on={silenceTimerEnabled} onclick={() => silenceTimerEnabled = !silenceTimerEnabled} role="switch" aria-checked={silenceTimerEnabled}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
          {#if silenceTimerEnabled}
            <div class="field-group">
              <label class="field-label" for="silence-min">Silence Timeout</label>
              <div class="input-with-suffix">
                <input id="silence-min" type="number" min="1" max="60" bind:value={silenceTimerMinutes} class="field-input" />
                <span class="input-suffix">min</span>
              </div>
            </div>
          {/if}
        </div>
      {/if}
    </section>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- VOICE PAGE                                              -->
  <!-- ════════════════════════════════════════════════════════ -->
  {:else if page === 'voice'}

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('tts-general')}>
        <span>General</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('tts-general')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('tts-general')}
        <div class="section-body">
          <label class="toggle-row">
            <span class="toggle-label">Mute TTS by default</span>
            <button class="toggle-switch" class:on={muteByDefault} onclick={() => muteByDefault = !muteByDefault} role="switch" aria-checked={muteByDefault}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
          <div class="field-group">
            <span class="field-label">TTS Backend</span>
            <div class="segmented-control">
              <button class:active={ttsBackend === 'elevenlabs'} onclick={() => ttsBackend = 'elevenlabs'}>ElevenLabs</button>
              <button class:active={ttsBackend === 'fal'} onclick={() => ttsBackend = 'fal'}>Fal</button>
              <button class:active={ttsBackend === 'none'} onclick={() => ttsBackend = 'none'}>None</button>
            </div>
          </div>
          <div class="field-group">
            <label class="field-label" for="playback-rate">Playback Rate</label>
            <div class="slider-row">
              <input id="playback-rate" type="range" min="0.5" max="2.0" step="0.01" bind:value={ttsPlaybackRate} class="field-slider" />
              <span class="slider-value">{ttsPlaybackRate.toFixed(2)}x</span>
            </div>
          </div>
        </div>
      {/if}
    </section>

    <!-- ElevenLabs config - only when backend is elevenlabs -->
    {#if ttsBackend === 'elevenlabs'}
      <section class="section">
        <button class="section-toggle" onclick={() => toggleSection('elevenlabs')}>
          <span>ElevenLabs</span>
          <svg class="section-chevron" class:collapsed={collapsed.has('elevenlabs')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        {#if !collapsed.has('elevenlabs')}
          <div class="section-body">
            <div class="field-group">
              <span class="field-label">API Key</span>
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
            <div class="field-group">
              <label class="field-label" for="el-voice">Voice ID</label>
              <input id="el-voice" type="text" bind:value={elevenlabsVoiceId} class="field-input" />
            </div>
            <div class="field-group">
              <label class="field-label" for="el-model">Model</label>
              <select id="el-model" bind:value={elevenlabsModel} class="field-select">
                <option value="eleven_v3">eleven_v3</option>
                <option value="eleven_v2">eleven_v2</option>
                <option value="eleven_multilingual_v2">eleven_multilingual_v2</option>
                <option value="eleven_turbo_v2_5">eleven_turbo_v2_5</option>
                <option value="eleven_flash_v2_5">eleven_flash_v2_5</option>
              </select>
            </div>
            <div class="field-group">
              <label class="field-label" for="el-stability">Stability</label>
              <div class="slider-row">
                <input id="el-stability" type="range" min="0" max="1" step="0.05" bind:value={elevenlabsStability} class="field-slider" />
                <span class="slider-value">{elevenlabsStability.toFixed(2)}</span>
              </div>
            </div>
            <div class="field-group">
              <label class="field-label" for="el-similarity">Similarity</label>
              <div class="slider-row">
                <input id="el-similarity" type="range" min="0" max="1" step="0.05" bind:value={elevenlabsSimilarity} class="field-slider" />
                <span class="slider-value">{elevenlabsSimilarity.toFixed(2)}</span>
              </div>
            </div>
            <div class="field-group">
              <label class="field-label" for="el-style">Style</label>
              <div class="slider-row">
                <input id="el-style" type="range" min="0" max="1" step="0.05" bind:value={elevenlabsStyle} class="field-slider" />
                <span class="slider-value">{elevenlabsStyle.toFixed(2)}</span>
              </div>
            </div>
          </div>
        {/if}
      </section>
    {/if}

    <!-- Fal config - only when backend is fal -->
    {#if ttsBackend === 'fal'}
      <section class="section">
        <button class="section-toggle" onclick={() => toggleSection('fal')}>
          <span>Fal</span>
          <svg class="section-chevron" class:collapsed={collapsed.has('fal')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        {#if !collapsed.has('fal')}
          <div class="section-body">
            <div class="field-group">
              <span class="field-label">API Key</span>
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
            <div class="field-group">
              <label class="field-label" for="fal-voice">Voice ID</label>
              <input id="fal-voice" type="text" bind:value={falVoiceId} class="field-input" />
            </div>
          </div>
        {/if}
      </section>
    {/if}

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- INPUT PAGE                                              -->
  <!-- ════════════════════════════════════════════════════════ -->
  {:else if page === 'input'}

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('input-mode')}>
        <span>Input</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('input-mode')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('input-mode')}
        <div class="section-body">
          <div class="field-group">
            <span class="field-label">Input Mode</span>
            <div class="segmented-control">
              <button class:active={inputMode === 'dual'} onclick={() => inputMode = 'dual'}>Dual</button>
              <button class:active={inputMode === 'voice'} onclick={() => inputMode = 'voice'}>Voice</button>
              <button class:active={inputMode === 'text'} onclick={() => inputMode = 'text'}>Text</button>
            </div>
          </div>
          <div class="field-group">
            <label class="field-label" for="ptt-key">Push-to-Talk Key</label>
            <input id="ptt-key" type="text" bind:value={pttKey} class="field-input" />
          </div>
          <label class="toggle-row">
            <span class="toggle-label">Wake Word Detection</span>
            <button class="toggle-switch" class:on={wakeWordEnabled} onclick={() => wakeWordEnabled = !wakeWordEnabled} role="switch" aria-checked={wakeWordEnabled}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
          {#if wakeWordEnabled}
            <div class="field-group">
              <label class="field-label" for="wake-chunk">Wake Chunk Duration</label>
              <div class="input-with-suffix">
                <input id="wake-chunk" type="number" min="1" max="10" bind:value={wakeChunkSeconds} class="field-input" />
                <span class="input-suffix">sec</span>
              </div>
            </div>
          {/if}
        </div>
      {/if}
    </section>

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('audio-capture')}>
        <span>Audio Capture</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('audio-capture')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('audio-capture')}
        <div class="section-body">
          <div class="field-group">
            <label class="field-label" for="sample-rate">Sample Rate</label>
            <div class="input-with-suffix">
              <input id="sample-rate" type="number" min="8000" max="48000" bind:value={sampleRate} class="field-input" />
              <span class="input-suffix">Hz</span>
            </div>
          </div>
          <div class="field-group">
            <label class="field-label" for="max-record">Max Record Duration</label>
            <div class="input-with-suffix">
              <input id="max-record" type="number" min="10" max="300" bind:value={maxRecordSec} class="field-input" />
              <span class="input-suffix">sec</span>
            </div>
          </div>
        </div>
      {/if}
    </section>

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('system-toggles')}>
        <span>System</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('system-toggles')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('system-toggles')}
        <div class="section-body">
          <label class="toggle-row">
            <span class="toggle-label">Prevent Sleep</span>
            <button class="toggle-switch" class:on={keepAwakeActive}
              onclick={async () => { const result = await api?.toggleKeepAwake(); keepAwakeActive = !!result; }}
              role="switch" aria-checked={keepAwakeActive}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
          <span class="field-hint">Prevents display and system sleep while the app is running.</span>
          <label class="toggle-row">
            <span class="toggle-label">macOS Notifications</span>
            <button class="toggle-switch" class:on={notificationsEnabled} onclick={() => notificationsEnabled = !notificationsEnabled} role="switch" aria-checked={notificationsEnabled}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
        </div>
      {/if}
    </section>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- ENGINE PAGE                                             -->
  <!-- ════════════════════════════════════════════════════════ -->
  {:else if page === 'engine'}

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('inference')}>
        <span>Inference</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('inference')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('inference')}
        <div class="section-body">
          <div class="field-group">
            <label class="field-label" for="claude-bin">Claude Binary</label>
            <input id="claude-bin" type="text" bind:value={claudeBin} class="field-input" />
          </div>
          <div class="field-group">
            <label class="field-label" for="claude-model">Model</label>
            <select id="claude-model" bind:value={claudeModel} class="field-select">
              <option value="claude-sonnet-4-6">Sonnet 4.6</option>
              <option value="claude-opus-4-6">Opus 4.6</option>
              <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
              <option value="claude-sonnet-4-5-20241022">Sonnet 4.5</option>
            </select>
          </div>
          <div class="field-group">
            <span class="field-label">Effort</span>
            <div class="segmented-control">
              <button class:active={claudeEffort === 'low'} onclick={() => claudeEffort = 'low'}>Low</button>
              <button class:active={claudeEffort === 'medium'} onclick={() => claudeEffort = 'medium'}>Medium</button>
              <button class:active={claudeEffort === 'high'} onclick={() => claudeEffort = 'high'}>High</button>
            </div>
          </div>
          <label class="toggle-row">
            <span class="toggle-label">Adaptive Effort</span>
            <button class="toggle-switch" class:on={adaptiveEffort} onclick={() => adaptiveEffort = !adaptiveEffort} role="switch" aria-checked={adaptiveEffort}>
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
            </button>
          </label>
        </div>
      {/if}
    </section>

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('memory')}>
        <span>Memory & Context</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('memory')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('memory')}
        <div class="section-body">
          <div class="field-row-inline">
            <div class="field-group compact">
              <label class="field-label" for="ctx-sum">Context Summaries</label>
              <input id="ctx-sum" type="number" min="0" max="20" bind:value={contextSummaries} class="field-input" />
            </div>
            <div class="field-group compact">
              <label class="field-label" for="max-tokens">Max Context Tokens</label>
              <input id="max-tokens" type="number" min="10000" max="500000" step="10000" bind:value={maxContextTokens} class="field-input" />
            </div>
          </div>
          <div class="field-group">
            <label class="field-label" for="vec-weight">Vector Search Weight</label>
            <div class="slider-row">
              <input id="vec-weight" type="range" min="0" max="1" step="0.05" bind:value={vectorSearchWeight} class="field-slider" />
              <span class="slider-value">{vectorSearchWeight.toFixed(2)}</span>
            </div>
          </div>
          <div class="field-row-inline">
            <div class="field-group compact">
              <label class="field-label" for="emb-model">Embedding Model</label>
              <input id="emb-model" type="text" bind:value={embeddingModel} class="field-input" />
            </div>
            <div class="field-group compact">
              <label class="field-label" for="emb-dim">Dimensions</label>
              <input id="emb-dim" type="number" min="64" max="2048" bind:value={embeddingDim} class="field-input" />
            </div>
          </div>
        </div>
      {/if}
    </section>

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('session')}>
        <span>Session & Heartbeat</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('session')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('session')}
        <div class="section-body">
          <div class="field-group">
            <label class="field-label" for="session-limit">Session Soft Limit</label>
            <div class="input-with-suffix">
              <input id="session-limit" type="number" min="10" max="480" bind:value={sessionSoftLimitMins} class="field-input" />
              <span class="input-suffix">min</span>
            </div>
          </div>
          <div class="field-group">
            <span class="field-label">Active Hours</span>
            <div class="inline-range">
              <input type="number" min="0" max="23" bind:value={heartbeatActiveStart} class="field-input compact-num" />
              <span class="range-separator">to</span>
              <input type="number" min="0" max="23" bind:value={heartbeatActiveEnd} class="field-input compact-num" />
              <span class="input-suffix">h</span>
            </div>
          </div>
          <div class="field-group">
            <label class="field-label" for="hb-interval">Heartbeat Interval</label>
            <div class="input-with-suffix">
              <input id="hb-interval" type="number" min="5" max="120" bind:value={heartbeatIntervalMins} class="field-input" />
              <span class="input-suffix">min</span>
            </div>
          </div>
        </div>
      {/if}
    </section>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- TELEGRAM PAGE                                           -->
  <!-- ════════════════════════════════════════════════════════ -->
  {:else if page === 'telegram'}

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('telegram-config')}>
        <span>Configuration</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('telegram-config')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('telegram-config')}
        <div class="section-body">
          <div class="field-group">
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
          <div class="field-group">
            <label class="field-label" for="tg-chat">Chat ID</label>
            <input id="tg-chat" type="text" bind:value={telegramChatId} class="field-input" />
          </div>
          <div class="field-group">
            <label class="field-label" for="tg-user">Your Telegram Name</label>
            <input id="tg-user" type="text" bind:value={telegramUsername} class="field-input" placeholder="e.g. fellowear" />
            <span class="field-hint">Maps to your name in conversations</span>
          </div>
        </div>
      {/if}
    </section>

    <!-- Auto-detect + daemon controls -->
    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('telegram-daemon')}>
        <span>Daemon</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('telegram-daemon')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('telegram-daemon')}
        <div class="section-body">
          {#if telegramBotToken && telegramBotToken !== '***' && !telegramChatId}
            <div class="daemon-row">
              <span class="field-info">{telegramDiscoverStatus || 'Send any message to the bot to link'}</span>
              <button
                class="small-btn"
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
          {/if}
          <div class="daemon-row">
            <span class="toggle-label">Polling Daemon</span>
            <div class="daemon-control">
              <span class="daemon-status" class:active={telegramDaemonRunning}>
                {telegramDaemonRunning ? 'Running' : 'Stopped'}
              </span>
              <button
                class="small-btn"
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
      {/if}
    </section>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- CONNECTIONS PAGE                                        -->
  <!-- ════════════════════════════════════════════════════════ -->
  {:else if page === 'connections'}

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('google')}>
        <span>Google</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('google')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('google')}
        <div class="section-body">
          <div class="field-group">
            <span class="field-label">Status</span>
            <span class="field-info" class:connected={googleConfigured}>
              {googleConfigured ? 'Connected' : 'Not connected'}
            </span>
          </div>
          {#if googleAuthStatus}
            <div class="field-group">
              <span class="field-info">{googleAuthStatus}</span>
            </div>
          {/if}
        </div>
      {/if}
    </section>

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('paths')}>
        <span>Paths</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('paths')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('paths')}
        <div class="section-body">
          <div class="field-group">
            <label class="field-label" for="obsidian-vault">Obsidian Vault</label>
            <input id="obsidian-vault" type="text" bind:value={obsidianVault} class="field-input" />
          </div>
          <div class="field-group">
            <span class="field-label">Database</span>
            <span class="field-info mono">{dbPath}</span>
          </div>
          <div class="field-group">
            <span class="field-label">Whisper Binary</span>
            <span class="field-info mono">{whisperBin}</span>
          </div>
        </div>
      {/if}
    </section>

  <!-- ════════════════════════════════════════════════════════ -->
  <!-- ABOUT PAGE                                              -->
  <!-- ════════════════════════════════════════════════════════ -->
  {:else if page === 'about'}

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('about-info')}>
        <span>About</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('about-info')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('about-info')}
        <div class="section-body">
          <div class="field-group">
            <span class="field-label">Version</span>
            <span class="field-info">{version}</span>
          </div>
          <div class="field-group">
            <span class="field-label">Install Path</span>
            <span class="field-info mono">{bundleRoot}</span>
          </div>
        </div>
      {/if}
    </section>

    <section class="section">
      <button class="section-toggle" onclick={() => toggleSection('app-actions')}>
        <span>App</span>
        <svg class="section-chevron" class:collapsed={collapsed.has('app-actions')} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {#if !collapsed.has('app-actions')}
        <div class="section-body">
          <div class="daemon-row">
            <span class="toggle-label">Reset Setup Wizard</span>
            <button class="small-btn danger" onclick={onResetSetup}>Reset Setup</button>
          </div>
        </div>
      {/if}
    </section>
  {/if}

</div>

<style>
  .settings-page {
    max-width: 640px;
  }

  /* ── Page title ──────────────────────────────────────────── */

  .page-title {
    font-size: 18px;
    font-weight: 700;
    color: rgba(255, 255, 255, 0.9);
    margin: 0 0 20px;
    letter-spacing: -0.01em;
  }

  /* ── Sections with accordion ─────────────────────────────── */

  .section {
    margin-bottom: 4px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.02);
    overflow: hidden;
  }

  .section-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 10px 14px;
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
    font-weight: 600;
    font-family: var(--font-sans);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    cursor: pointer;
    text-align: left;
    transition: color 0.15s;
  }

  .section-toggle:hover {
    color: rgba(255, 255, 255, 0.85);
  }

  .section-chevron {
    transition: transform 0.2s ease;
    opacity: 0.4;
  }

  .section-chevron.collapsed {
    transform: rotate(-90deg);
  }

  .section-body {
    padding: 2px 14px 14px;
  }

  /* ── Field groups (stacked label-above-input) ────────────── */

  .field-group {
    margin-bottom: 12px;
  }

  .field-group.compact {
    margin-bottom: 8px;
  }

  .field-label {
    display: block;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.45);
    margin-bottom: 4px;
    letter-spacing: 0.01em;
  }

  .field-input {
    width: 100%;
    height: 32px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 13px;
    outline: none;
    transition: border-color 0.15s;
    box-sizing: border-box;
  }

  .field-input:focus {
    border-color: rgba(255, 255, 255, 0.2);
  }

  .field-input.has-eye {
    padding-right: 36px;
  }

  .field-input.compact-num {
    width: 64px;
    text-align: center;
  }

  /* ── Inline field rows ───────────────────────────────────── */

  .field-row-inline {
    display: flex;
    gap: 12px;
  }

  .field-row-inline .field-group {
    flex: 1;
    min-width: 0;
  }

  .inline-range {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .range-separator {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.3);
  }

  /* ── Input with suffix ───────────────────────────────────── */

  .input-with-suffix {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .input-with-suffix .field-input {
    width: 120px;
    flex: 0 0 auto;
  }

  .input-suffix {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.35);
  }

  /* ── Eye toggle (password visibility) ────────────────────── */

  .input-eye-wrap {
    position: relative;
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

  /* ── Select ──────────────────────────────────────────────── */

  .field-select {
    width: 100%;
    height: 32px;
    padding: 0 28px 0 10px;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 13px;
    outline: none;
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='rgba(255,255,255,0.4)' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 10px center;
  }

  .field-select:focus {
    border-color: rgba(255, 255, 255, 0.2);
  }

  .field-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }

  /* ── Slider ──────────────────────────────────────────────── */

  .slider-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .field-slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255, 255, 255, 0.12);
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

  .slider-value {
    min-width: 40px;
    font-size: 11px;
    font-family: var(--font-mono);
    color: rgba(255, 255, 255, 0.5);
    text-align: right;
  }

  /* ── Toggle switches ─────────────────────────────────────── */

  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    min-height: 32px;
  }

  .toggle-label {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.7);
  }

  .toggle-switch {
    position: relative;
    width: 38px;
    height: 22px;
    flex-shrink: 0;
    border: none;
    background: none;
    padding: 0;
    cursor: pointer;
  }

  .toggle-track {
    display: block;
    width: 38px;
    height: 22px;
    border-radius: 11px;
    background: rgba(255, 255, 255, 0.12);
    transition: background 0.2s;
    position: relative;
  }

  .toggle-switch.on .toggle-track {
    background: rgba(100, 140, 255, 0.45);
  }

  .toggle-thumb {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.75);
    transition: transform 0.2s ease;
  }

  .toggle-switch.on .toggle-thumb {
    transform: translateX(16px);
    background: rgba(255, 255, 255, 0.95);
  }

  /* ── Segmented controls ──────────────────────────────────── */

  .segmented-control {
    display: flex;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 7px;
    padding: 2px;
    gap: 2px;
  }

  .segmented-control button {
    flex: 1;
    padding: 5px 12px;
    border: none;
    border-radius: 5px;
    background: transparent;
    color: rgba(255, 255, 255, 0.4);
    font-family: var(--font-sans);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }

  .segmented-control button:hover {
    color: rgba(255, 255, 255, 0.6);
  }

  .segmented-control button.active {
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.9);
  }

  /* ── Info text + hints ───────────────────────────────────── */

  .field-info {
    font-size: 13px;
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

  .field-hint {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.25);
    margin-top: 3px;
    display: block;
  }

  /* ── Daemon controls + buttons ───────────────────────────── */

  .daemon-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    min-height: 32px;
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

  .small-btn {
    padding: 5px 14px;
    font-size: 11px;
    font-weight: 500;
    font-family: var(--font-sans);
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.65);
    cursor: pointer;
    transition: background 0.15s;
  }

  .small-btn:hover {
    background: rgba(255, 255, 255, 0.12);
  }

  .small-btn.danger {
    border-color: rgba(255, 80, 80, 0.3);
    color: rgba(255, 80, 80, 0.7);
  }

  .small-btn.danger:hover {
    border-color: rgba(255, 80, 80, 0.5);
    color: rgba(255, 80, 80, 0.9);
    background: rgba(255, 80, 80, 0.08);
  }
</style>

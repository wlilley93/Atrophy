<script lang="ts">
  import { onMount } from 'svelte';
  import { agents } from '../stores/agents.svelte';
  import { api } from '../api';

  interface Props {
    onClose: () => void;
  }

  let { onClose }: Props = $props();

  type Tab = 'settings' | 'usage' | 'activity' | 'jobs' | 'updates';
  let activeTab = $state<Tab>('settings');

  // ---------------------------------------------------------------------------
  // Config form state
  // ---------------------------------------------------------------------------

  // Agents
  let agentList = $state<{ name: string; display_name: string; description: string; role: string }[]>([]);

  // Identity
  let userName = $state('');
  let agentDisplayName = $state('');
  let openingLine = $state('');
  let wakeWords = $state('');

  // Tools
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
  let disabledTools = $state<Set<string>>(new Set());

  // Window
  let windowWidth = $state(622);
  let windowHeight = $state(830);
  let avatarEnabled = $state(false);
  let avatarResolution = $state(512);

  // Voice
  let falApiKey = $state('');
  let ttsBackend = $state('elevenlabs');
  let elevenlabsApiKey = $state('');
  let elevenlabsVoiceId = $state('');
  let elevenlabsModel = $state('eleven_v3');
  let elevenlabsStability = $state(0.5);
  let elevenlabsSimilarity = $state(0.75);
  let elevenlabsStyle = $state(0.35);
  let ttsPlaybackRate = $state(1.12);
  let falVoiceId = $state('');

  // Input
  let inputMode = $state('dual');
  let pttKey = $state('ctrl');
  let wakeWordEnabled = $state(false);
  let wakeChunkSeconds = $state(2);

  // Silence timer
  let silenceTimerEnabled = $state(true);
  let silenceTimerMinutes = $state(5);

  // Eye mode
  let eyeModeDefault = $state(false);

  // Mute
  let muteByDefault = $state(false);

  // Keep Awake
  let keepAwakeActive = $state(false);

  // Notifications
  let notificationsEnabled = $state(true);

  // Audio
  let sampleRate = $state(16000);
  let maxRecordSec = $state(120);

  // Inference
  let claudeBin = $state('claude');
  let claudeModel = $state('claude-sonnet-4-6');
  let claudeEffort = $state('medium');
  let adaptiveEffort = $state(true);

  // Memory
  let contextSummaries = $state(3);
  let maxContextTokens = $state(180000);
  let vectorSearchWeight = $state(0.7);
  let embeddingModel = $state('all-MiniLM-L6-v2');
  let embeddingDim = $state(384);

  // Session
  let sessionSoftLimitMins = $state(60);

  // Heartbeat
  let heartbeatActiveStart = $state(9);
  let heartbeatActiveEnd = $state(22);
  let heartbeatIntervalMins = $state(30);

  // Paths
  let obsidianVault = $state('');
  let dbPath = $state('');
  let whisperBin = $state('');

  // Google
  let googleConfigured = $state(false);
  let googleAuthStatus = $state('');

  // Telegram
  let telegramBotToken = $state('');
  let telegramChatId = $state('');
  let telegramDaemonRunning = $state(false);
  let telegramDiscovering = $state(false);
  let telegramDiscoverStatus = $state('');

  // Password visibility toggles
  let showElevenlabsKey = $state(false);
  let showFalKey = $state(false);
  let showTelegramToken = $state(false);

  // About
  let version = $state('0.0.0');
  let bundleRoot = $state('');

  // ---------------------------------------------------------------------------
  // Usage tab state
  // ---------------------------------------------------------------------------

  let usagePeriod = $state<number | null>(null);
  let usageData = $state<any[]>([]);
  let usageLoading = $state(false);

  // ---------------------------------------------------------------------------
  // Activity tab state
  // ---------------------------------------------------------------------------

  let activityItems = $state<any[]>([]);
  let activityFilter = $state('all');
  let activityAgentFilter = $state('all');
  let activitySearch = $state('');
  let activityLoading = $state(false);
  let expandedActivity = $state<number | null>(null);

  // ---------------------------------------------------------------------------
  // Jobs tab state
  // ---------------------------------------------------------------------------

  let jobsList = $state<any[]>([]);
  let jobHistory = $state<any[]>([]);
  let jobsLoading = $state(false);
  let runningJob = $state<string | null>(null);
  let expandedJob = $state<number | null>(null);
  let jobLogContent = $state('');
  let jobLogName = $state<string | null>(null);

  async function loadJobs() {
    if (!api) return;
    jobsLoading = true;
    try {
      const [jobs, history] = await Promise.all([
        api.getJobs(),
        api.getJobHistory(),
      ]);
      jobsList = jobs || [];
      jobHistory = history || [];
    } catch { /* ignore */ }
    jobsLoading = false;
  }

  async function triggerJob(name: string) {
    if (!api || runningJob) return;
    runningJob = name;
    try {
      await api.runJob(name);
      await loadJobs();
    } catch { /* ignore */ }
    runningJob = null;
  }

  async function viewJobLog(name: string) {
    if (!api) return;
    if (jobLogName === name) {
      jobLogName = null;
      jobLogContent = '';
      return;
    }
    jobLogName = name;
    try {
      jobLogContent = await api.readJobLog(name, 100) || '(empty)';
    } catch {
      jobLogContent = '(could not read log)';
    }
  }

  // ---------------------------------------------------------------------------
  // Updates tab state
  // ---------------------------------------------------------------------------

  let bundleVersion = $state<string | null>(null);
  let hotBundleActive = $state(false);
  let updateCheckStatus = $state<'idle' | 'checking' | 'downloading' | 'ready' | 'up-to-date' | 'error'>('idle');
  let updateDownloadPercent = $state(0);
  let updateReadyVersion = $state<string | null>(null);
  let updateStatusText = $state('');

  async function loadUpdatesTab() {
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

    // Listen for progress and ready events
    api.onBundleProgress?.((percent: number) => {
      updateDownloadPercent = percent;
      updateCheckStatus = 'downloading';
      updateStatusText = `Downloading... ${Math.round(percent)}%`;
    });
    api.onBundleReady?.((info: { version: string }) => {
      updateReadyVersion = info.version;
      updateCheckStatus = 'ready';
      updateStatusText = `v${info.version} downloaded - restart to apply`;
    });
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

  // ---------------------------------------------------------------------------
  // Load config on mount
  // ---------------------------------------------------------------------------

  onMount(async () => {
    if (!api) return;
    try {
      const [cfg, fullAgents] = await Promise.all([
        api.getConfig(),
        api.getAgentsFull(),
      ]);
      agentList = fullAgents || [];

      // Populate form
      userName = cfg.userName || '';
      agentDisplayName = cfg.agentDisplayName || '';
      openingLine = cfg.openingLine || '';
      wakeWords = (cfg.wakeWords || []).join(', ');
      disabledTools = new Set(cfg.disabledTools || []);

      windowWidth = cfg.windowWidth || 622;
      windowHeight = cfg.windowHeight || 830;
      avatarEnabled = cfg.avatarEnabled || false;
      avatarResolution = cfg.avatarResolution || 512;

      ttsBackend = cfg.ttsBackend || 'elevenlabs';
      elevenlabsApiKey = cfg.elevenlabsApiKey || '';
      elevenlabsVoiceId = cfg.elevenlabsVoiceId || '';
      elevenlabsModel = cfg.elevenlabsModel || 'eleven_v3';
      elevenlabsStability = cfg.elevenlabsStability ?? 0.5;
      elevenlabsSimilarity = cfg.elevenlabsSimilarity ?? 0.75;
      elevenlabsStyle = cfg.elevenlabsStyle ?? 0.35;
      ttsPlaybackRate = cfg.ttsPlaybackRate ?? 1.12;
      falApiKey = cfg.falApiKey || '';
      falVoiceId = cfg.falVoiceId || '';

      inputMode = cfg.inputMode || 'dual';
      pttKey = cfg.pttKey || 'ctrl';
      wakeWordEnabled = cfg.wakeWordEnabled || false;
      wakeChunkSeconds = cfg.wakeChunkSeconds || 2;

      silenceTimerEnabled = cfg.silenceTimerEnabled ?? true;
      silenceTimerMinutes = cfg.silenceTimerMinutes ?? 5;
      eyeModeDefault = cfg.eyeModeDefault ?? false;
      muteByDefault = cfg.muteByDefault ?? false;

      keepAwakeActive = cfg.keepAwakeActive ?? false;
      notificationsEnabled = cfg.notificationsEnabled ?? true;

      sampleRate = cfg.sampleRate || 16000;
      maxRecordSec = cfg.maxRecordSec || 120;

      claudeBin = cfg.claudeBin || 'claude';
      claudeModel = cfg.claudeModel || 'claude-sonnet-4-6';
      claudeEffort = cfg.claudeEffort || 'medium';
      adaptiveEffort = cfg.adaptiveEffort ?? true;

      contextSummaries = cfg.contextSummaries ?? 3;
      maxContextTokens = cfg.maxContextTokens || 180000;
      vectorSearchWeight = cfg.vectorSearchWeight ?? 0.7;
      embeddingModel = cfg.embeddingModel || 'all-MiniLM-L6-v2';
      embeddingDim = cfg.embeddingDim || 384;

      sessionSoftLimitMins = cfg.sessionSoftLimitMins || 60;

      heartbeatActiveStart = cfg.heartbeatActiveStart ?? 9;
      heartbeatActiveEnd = cfg.heartbeatActiveEnd ?? 22;
      heartbeatIntervalMins = cfg.heartbeatIntervalMins || 30;

      obsidianVault = cfg.obsidianVault || '';
      dbPath = cfg.dbPath || '';
      whisperBin = cfg.whisperBin || '';

      googleConfigured = cfg.googleConfigured || false;

      telegramBotToken = cfg.telegramBotToken || '';
      telegramChatId = cfg.telegramChatId || '';
      telegramDaemonRunning = cfg.telegramDaemonRunning || false;

      version = cfg.version || '0.0.0';
      bundleRoot = cfg.bundleRoot || '';
    } catch (e) {
      console.error('Failed to load config', e);
    }
  });

  // ---------------------------------------------------------------------------
  // Save / Apply
  // ---------------------------------------------------------------------------

  let saveStatus = $state('');

  function gatherUpdates(): Record<string, unknown> {
    const enabledToolsList = toggleableTools
      .map(([id]) => id)
      .filter(id => disabledTools.has(id));

    return {
      USER_NAME: userName,
      AGENT_DISPLAY_NAME: agentDisplayName,
      OPENING_LINE: openingLine,
      WAKE_WORDS: wakeWords.split(',').map((w: string) => w.trim()).filter(Boolean),
      DISABLED_TOOLS: enabledToolsList,
      WINDOW_WIDTH: windowWidth,
      WINDOW_HEIGHT: windowHeight,
      AVATAR_ENABLED: avatarEnabled,
      AVATAR_RESOLUTION: avatarResolution,
      TTS_BACKEND: ttsBackend,
      ELEVENLABS_VOICE_ID: elevenlabsVoiceId,
      ELEVENLABS_MODEL: elevenlabsModel,
      ELEVENLABS_STABILITY: elevenlabsStability,
      ELEVENLABS_SIMILARITY: elevenlabsSimilarity,
      ELEVENLABS_STYLE: elevenlabsStyle,
      TTS_PLAYBACK_RATE: ttsPlaybackRate,
      FAL_VOICE_ID: falVoiceId,
      INPUT_MODE: inputMode,
      PTT_KEY: pttKey,
      WAKE_WORD_ENABLED: wakeWordEnabled,
      WAKE_CHUNK_SECONDS: wakeChunkSeconds,
      SILENCE_TIMER_ENABLED: silenceTimerEnabled,
      SILENCE_TIMER_MINUTES: silenceTimerMinutes,
      EYE_MODE_DEFAULT: eyeModeDefault,
      MUTE_BY_DEFAULT: muteByDefault,
      NOTIFICATIONS_ENABLED: notificationsEnabled,
      SAMPLE_RATE: sampleRate,
      MAX_RECORD_SEC: maxRecordSec,
      CLAUDE_BIN: claudeBin,
      CLAUDE_MODEL: claudeModel,
      CLAUDE_EFFORT: claudeEffort,
      ADAPTIVE_EFFORT: adaptiveEffort,
      CONTEXT_SUMMARIES: contextSummaries,
      MAX_CONTEXT_TOKENS: maxContextTokens,
      VECTOR_SEARCH_WEIGHT: vectorSearchWeight,
      EMBEDDING_MODEL: embeddingModel,
      EMBEDDING_DIM: embeddingDim,
      SESSION_SOFT_LIMIT_MINS: sessionSoftLimitMins,
      HEARTBEAT_ACTIVE_START: heartbeatActiveStart,
      HEARTBEAT_ACTIVE_END: heartbeatActiveEnd,
      HEARTBEAT_INTERVAL_MINS: heartbeatIntervalMins,
      OBSIDIAN_VAULT: obsidianVault,
      TELEGRAM_CHAT_ID: telegramChatId,
    };
  }

  /**
   * Apply updates to the running config only - not persisted to disk.
   * Useful for testing runtime changes before committing them.
   */
  async function apply() {
    if (!api) return;
    try {
      await api.applyConfig(gatherUpdates());
      saveStatus = 'Applied (not saved)';
      setTimeout(() => saveStatus = '', 3000);
    } catch {
      saveStatus = 'Error';
    }
  }

  /**
   * Apply updates to the running config AND persist to disk.
   * Also saves any changed secrets to .env.
   */
  async function save() {
    if (!api) return;
    try {
      await api.updateConfig(gatherUpdates());
      // Save changed secrets to .env (not config.json)
      if (elevenlabsApiKey && elevenlabsApiKey !== '***') {
        await api.saveSecret('ELEVENLABS_API_KEY', elevenlabsApiKey);
      }
      if (falApiKey && falApiKey !== '***') {
        await api.saveSecret('FAL_KEY', falApiKey);
      }
      if (telegramBotToken && telegramBotToken !== '***') {
        await api.saveSecret('TELEGRAM_BOT_TOKEN', telegramBotToken);
      }
      saveStatus = 'Saved';
      setTimeout(() => saveStatus = '', 2000);
    } catch {
      saveStatus = 'Error';
    }
  }

  // ---------------------------------------------------------------------------
  // Agent actions
  // ---------------------------------------------------------------------------

  async function switchToAgent(name: string) {
    if (!api) return;
    const result = await api.switchAgent(name);
    agents.current = result.agentName;
    agents.displayName = result.agentDisplayName;
    onClose();
  }

  // ---------------------------------------------------------------------------
  // Usage tab
  // ---------------------------------------------------------------------------

  async function loadUsage(days: number | null) {
    usagePeriod = days;
    if (!api) return;
    usageLoading = true;
    try {
      usageData = await api.getUsage(days ?? undefined) || [];
    } catch {
      usageData = [];
    }
    usageLoading = false;
  }

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  }

  function formatDuration(ms: number): string {
    const secs = Math.floor(ms / 1000);
    if (secs < 60) return `${secs}s`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ${secs % 60}s`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  }

  // ---------------------------------------------------------------------------
  // Activity tab
  // ---------------------------------------------------------------------------

  async function loadActivity() {
    if (!api) return;
    activityLoading = true;
    try {
      activityItems = await api.getActivity(30, 500) || [];
    } catch {
      activityItems = [];
    }
    activityLoading = false;
  }

  function activityAgents(): string[] {
    const s = new Set(activityItems.map((i: any) => i.agent).filter(Boolean));
    return [...s].sort();
  }

  function filteredActivity(): any[] {
    let items = activityItems;
    if (activityFilter === 'flagged') {
      items = items.filter((i: any) => i.flagged);
    } else if (activityFilter !== 'all') {
      items = items.filter((i: any) => i.category === activityFilter);
    }
    if (activityAgentFilter !== 'all') {
      items = items.filter((i: any) => i.agent === activityAgentFilter);
    }
    if (activitySearch) {
      const q = activitySearch.toLowerCase();
      items = items.filter((i: any) =>
        `${i.action || ''} ${i.detail || ''} ${i.agent || ''}`.toLowerCase().includes(q)
      );
    }
    return items.slice(0, 200);
  }

  const categoryBadges: Record<string, [string, string]> = {
    tool_call: ['TOOL', '#4a9eff'],
    heartbeat: ['BEAT', '#9b59b6'],
    inference: ['INFER', '#2ecc71'],
  };

  function formatTimestamp(ts: string): string {
    try {
      const d = new Date(ts);
      return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}  ${d.toLocaleTimeString('en-US', { hour12: false })}`;
    } catch {
      return ts?.slice(0, 19) || '';
    }
  }

  // ---------------------------------------------------------------------------
  // Tab switching
  // ---------------------------------------------------------------------------

  function switchTab(tab: Tab) {
    activeTab = tab;
    if (tab === 'usage') loadUsage(usagePeriod);
    if (tab === 'activity') loadActivity();
    if (tab === 'jobs') loadJobs();
    if (tab === 'updates') loadUpdatesTab();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="settings-overlay" data-no-drag>
  <div class="settings-panel">
    <!-- Header -->
    <div class="settings-header">
      <div class="tabs">
        <button class="tab" class:active={activeTab === 'settings'} onclick={() => switchTab('settings')}>Settings</button>
        <button class="tab" class:active={activeTab === 'usage'} onclick={() => switchTab('usage')}>Usage</button>
        <button class="tab" class:active={activeTab === 'activity'} onclick={() => switchTab('activity')}>Activity</button>
        <button class="tab" class:active={activeTab === 'jobs'} onclick={() => switchTab('jobs')}>Jobs</button>
        <button class="tab" class:active={activeTab === 'updates'} onclick={() => switchTab('updates')}>Updates</button>
      </div>
      <button class="close-btn" onclick={onClose} aria-label="Close settings">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <!-- Content -->
    <div class="settings-content">

      {#if activeTab === 'settings'}
        <!-- ─── AGENTS ─── -->
        <div class="section">
          <div class="section-header">Agents</div>
          <div class="section-line"></div>
          <div class="agent-list">
            {#each agentList as agent}
              <div class="agent-row" class:current={agent.name === agents.current}>
                <div class="agent-info">
                  <span class="agent-name-label" class:bold={agent.name === agents.current}>
                    {agent.display_name || agent.name}
                  </span>
                  {#if agent.role}
                    <span class="agent-role">{agent.role}</span>
                  {/if}
                </div>
                <div class="agent-actions">
                  {#if agent.name === agents.current}
                    <span class="agent-active-label">active</span>
                  {:else}
                    <button class="small-btn" onclick={() => switchToAgent(agent.name)}>Switch</button>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </div>

        <!-- ─── YOU ─── -->
        <div class="section">
          <div class="section-header">You</div>
          <div class="section-line"></div>
          <label class="field">
            <span class="field-label">Your Name</span>
            <input type="text" bind:value={userName} class="field-input" />
          </label>
        </div>

        <!-- ─── AGENT IDENTITY ─── -->
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
            <span class="field-label">Opening Line</span>
            <input type="text" bind:value={openingLine} class="field-input" />
          </label>
          <label class="field">
            <span class="field-label">Wake Words</span>
            <input type="text" bind:value={wakeWords} class="field-input" placeholder="hey xan, xan" />
          </label>
        </div>

        <!-- ─── TOOLS ─── -->
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

        <!-- ─── WINDOW ─── -->
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

        <!-- ─── VOICE & TTS ─── -->
        <div class="section">
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

        <!-- ─── INPUT ─── -->
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

        <!-- ─── KEEP AWAKE ─── -->
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

        <!-- ─── NOTIFICATIONS ─── -->
        <div class="section">
          <div class="section-header">Notifications</div>
          <div class="section-line"></div>
          <label class="checkbox-row">
            <input type="checkbox" bind:checked={notificationsEnabled} />
            <span>macOS Notifications</span>
          </label>
        </div>

        <!-- ─── AUDIO CAPTURE ─── -->
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

        <!-- ─── INFERENCE ─── -->
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

        <!-- ─── MEMORY & CONTEXT ─── -->
        <div class="section">
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

        <!-- ─── SESSION ─── -->
        <div class="section">
          <div class="section-header">Session</div>
          <div class="section-line"></div>
          <label class="field">
            <span class="field-label">Soft Limit</span>
            <input type="number" min="10" max="480" bind:value={sessionSoftLimitMins} class="field-input short" />
            <span class="field-suffix">min</span>
          </label>
        </div>

        <!-- ─── HEARTBEAT ─── -->
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

        <!-- ─── PATHS ─── -->
        <div class="section">
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

        <!-- ─── GOOGLE ─── -->
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

        <!-- ─── TELEGRAM ─── -->
        <div class="section">
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

        <!-- ─── ABOUT ─── -->
        <div class="section">
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

        <!-- ─── APP ─── -->
        <div class="section">
          <div class="section-header">App</div>
          <div class="section-line"></div>
          <div class="field row">
            <span class="field-label">Reset Setup Wizard</span>
            <button
              class="small-btn danger-btn"
              onclick={async () => {
                if (!api) return;
                await api.updateConfig({ setup_complete: false });
                saveStatus = 'Setup will re-run on next launch';
                setTimeout(() => saveStatus = '', 3000);
              }}
            >Reset Setup</button>
          </div>
        </div>

        <!-- ─── ACTIONS ─── -->
        <div class="actions">
          {#if saveStatus}
            <span class="save-status">{saveStatus}</span>
          {/if}
          <button class="action-btn" onclick={apply}>Apply</button>
          <button class="action-btn primary" onclick={save}>Save</button>
        </div>

      {:else if activeTab === 'usage'}
        <!-- ─── USAGE TAB ─── -->
        <div class="filter-row">
          {#each [['Today', 1], ['7 days', 7], ['30 days', 30], ['All', null]] as [label, days]}
            <button
              class="filter-pill"
              class:active={usagePeriod === days}
              onclick={() => loadUsage(days as number | null)}
            >{label}</button>
          {/each}
        </div>

        {#if usageLoading}
          <p class="placeholder">Loading...</p>
        {:else if usageData.length === 0 || usageData.every((a: any) => a.total_calls === 0)}
          <p class="placeholder">No usage data yet. Stats will appear after inference calls.</p>
        {:else}
          <!-- Totals bar -->
          {@const totalCalls = usageData.reduce((s: number, a: any) => s + (a.total_calls || 0), 0)}
          {@const totalTokens = usageData.reduce((s: number, a: any) => s + (a.total_tokens || 0), 0)}
          {@const totalDuration = usageData.reduce((s: number, a: any) => s + (a.total_duration_ms || 0), 0)}
          {@const totalTools = usageData.reduce((s: number, a: any) => s + (a.total_tools || 0), 0)}

          <div class="totals-bar">
            <div class="total-stat">
              <span class="total-value">{totalCalls}</span>
              <span class="total-label">Inferences</span>
            </div>
            <div class="total-stat">
              <span class="total-value">{formatTokens(totalTokens)}</span>
              <span class="total-label">Tokens (est.)</span>
            </div>
            <div class="total-stat">
              <span class="total-value">{formatDuration(totalDuration)}</span>
              <span class="total-label">Time</span>
            </div>
            <div class="total-stat">
              <span class="total-value">{totalTools}</span>
              <span class="total-label">Tool Calls</span>
            </div>
          </div>

          <!-- Per-agent cards -->
          {#each usageData.filter((a: any) => a.total_calls > 0) as agent}
            <div class="usage-card">
              <div class="usage-card-header">
                <span class="usage-agent-name">{agent.display_name || agent.agent}</span>
                <span class="usage-tokens">{formatTokens(agent.total_tokens)} tokens</span>
              </div>
              <div class="usage-stats-row">
                <span>{agent.total_calls} calls</span>
                <span>in: {formatTokens(agent.total_tokens_in || 0)}</span>
                <span>out: {formatTokens(agent.total_tokens_out || 0)}</span>
                <span>{formatDuration(agent.total_duration_ms || 0)}</span>
                <span>{agent.total_tools || 0} tools</span>
              </div>
              {#if agent.by_source?.length}
                <div class="usage-sources">
                  {#each agent.by_source.slice(0, 5) as src}
                    <span class="source-pill">{src.source} ({src.calls})</span>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        {/if}

      {:else if activeTab === 'activity'}
        <!-- ─── ACTIVITY TAB ─── -->
        <input
          type="text"
          class="search-input"
          placeholder="Search activity..."
          bind:value={activitySearch}
        />

        <div class="filter-row">
          {#each [['All', 'all'], ['Tools', 'tool_call'], ['Heartbeats', 'heartbeat'], ['Inference', 'inference'], ['Flagged', 'flagged']] as [label, key]}
            <button
              class="filter-pill"
              class:active={activityFilter === key}
              onclick={() => activityFilter = key as string}
            >{label}</button>
          {/each}
          <select class="agent-filter-select" bind:value={activityAgentFilter}>
            <option value="all">All agents</option>
            {#each activityAgents() as a}
              <option value={a}>{a.replace('_', ' ')}</option>
            {/each}
          </select>
        </div>

        <div class="activity-count">
          {#if activityItems.length > 0}
            {filteredActivity().length} of {activityItems.length} entries
          {:else}
            No activity recorded yet
          {/if}
        </div>

        {#if activityLoading}
          <p class="placeholder">Loading...</p>
        {:else}
          {#each filteredActivity() as item, i}
            {@const [badgeText, badgeColor] = categoryBadges[item.category] || [item.category?.toUpperCase() || '?', '#888']}
            <button
              class="activity-card"
              class:expanded={expandedActivity === i}
              onclick={() => expandedActivity = expandedActivity === i ? null : i}
            >
              <div class="activity-summary">
                <span class="activity-badge" style="color: {badgeColor}">{badgeText}</span>
                {#if item.flagged}
                  <span class="activity-flag">!</span>
                {/if}
                <span class="activity-action">{item.action || ''}</span>
                <span class="activity-agent">{(item.agent || '').replace('_', ' ')}</span>
                <span class="activity-spacer"></span>
                <span class="activity-time">{formatTimestamp(item.timestamp)}</span>
              </div>
              {#if expandedActivity === i}
                <pre class="activity-detail">{item.detail || '(no detail)'}</pre>
              {/if}
            </button>
          {/each}
        {/if}

      {:else if activeTab === 'updates'}
        <!-- Updates tab -->
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

      {:else if activeTab === 'jobs'}
        <!-- Jobs tab -->
        {#if jobsLoading}
          <p class="placeholder">Loading...</p>
        {:else}
          <!-- Registered jobs -->
          <div class="section">
            <div class="section-header">Scheduled Jobs</div>
            <div class="section-line"></div>

            {#if jobsList.length === 0}
              <p class="placeholder">No jobs configured</p>
            {:else}
              {#each jobsList as job}
                <div class="job-row">
                  <div class="job-info">
                    <span class="job-name">{job.name}</span>
                    <span class="job-schedule">{job.schedule || ''}</span>
                    <span class="job-status" class:installed={job.installed}>
                      {job.installed ? 'installed' : 'not installed'}
                    </span>
                  </div>
                  <div class="job-actions">
                    <button
                      class="job-btn"
                      disabled={runningJob !== null}
                      onclick={() => triggerJob(job.name)}
                    >
                      {runningJob === job.name ? '...' : 'Run'}
                    </button>
                    <button class="job-btn" onclick={() => viewJobLog(job.name)}>
                      {jobLogName === job.name ? 'Hide' : 'Log'}
                    </button>
                  </div>
                </div>
                {#if job.description}
                  <div class="job-desc">{job.description}</div>
                {/if}
                {#if jobLogName === job.name}
                  <pre class="job-log">{jobLogContent}</pre>
                {/if}
              {/each}
            {/if}
          </div>

          <!-- Run history -->
          <div class="section">
            <div class="section-header">Run History</div>
            <div class="section-line"></div>

            {#if jobHistory.length === 0}
              <p class="placeholder">No runs yet this session</p>
            {:else}
              {#each jobHistory as entry, i}
                <button
                  class="activity-card"
                  class:expanded={expandedJob === i}
                  onclick={() => expandedJob = expandedJob === i ? null : i}
                >
                  <div class="activity-summary">
                    <span class="activity-badge" style="color: {entry.exitCode === 0 ? '#5ce0d6' : '#ff6b6b'}">
                      {entry.exitCode === 0 ? 'OK' : 'FAIL'}
                    </span>
                    <span class="activity-action">{entry.name}</span>
                    <span class="activity-agent">{entry.agent}</span>
                    <span class="activity-spacer"></span>
                    <span class="job-duration">{entry.durationMs < 1000 ? entry.durationMs + 'ms' : (entry.durationMs / 1000).toFixed(1) + 's'}</span>
                    <span class="activity-time">{formatTimestamp(entry.timestamp)}</span>
                  </div>
                  {#if expandedJob === i}
                    <pre class="activity-detail">{entry.output || '(no output)'}</pre>
                  {/if}
                </button>
              {/each}
            {/if}
          </div>
        {/if}
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
    width: 92%;
    max-width: 540px;
    max-height: 85%;
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
    flex-shrink: 0;
  }

  .tabs {
    display: flex;
    gap: 4px;
  }

  .tab {
    padding: 6px 16px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-dim);
    font-family: var(--font-sans);
    font-size: 12px;
    cursor: pointer;
    border-radius: 15px;
    transition: color 0.15s, background 0.15s;
  }

  .tab:hover {
    color: var(--text-secondary);
    background: rgba(255, 255, 255, 0.08);
  }

  .tab.active {
    color: rgba(255, 255, 255, 0.95);
    background: rgba(255, 255, 255, 0.15);
    border-color: rgba(255, 255, 255, 0.2);
    font-weight: bold;
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
    padding: 16px 20px;
  }

  /* Scrollbar */
  .settings-content::-webkit-scrollbar {
    width: 6px;
  }

  .settings-content::-webkit-scrollbar-track {
    background: rgba(255, 255, 255, 0.02);
    border-radius: 3px;
  }

  .settings-content::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
  }

  /* ── Sections ── */

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

  /* ── Agents ── */

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

  /* ── Fields ── */

  .field {
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

  .field-input {
    flex: 1;
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

  /* ── Checkbox ── */

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

  /* ── Actions ── */

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

  /* ── Filter pills ── */

  .filter-row {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  .filter-pill {
    padding: 4px 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .filter-pill:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  .filter-pill.active {
    background: rgba(255, 255, 255, 0.15);
    color: rgba(255, 255, 255, 0.9);
    border-color: rgba(255, 255, 255, 0.25);
  }

  .agent-filter-select {
    margin-left: auto;
    height: 26px;
    padding: 0 8px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    min-width: 100px;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
  }

  .agent-filter-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }

  /* ── Usage tab ── */

  .totals-bar {
    display: flex;
    justify-content: space-around;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 12px;
  }

  .total-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .total-value {
    color: rgba(255, 255, 255, 0.95);
    font-size: 20px;
    font-weight: bold;
  }

  .total-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
  }

  .usage-card {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
  }

  .usage-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }

  .usage-agent-name {
    color: rgba(255, 255, 255, 0.9);
    font-size: 14px;
    font-weight: bold;
  }

  .usage-tokens {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12px;
  }

  .usage-stats-row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
  }

  .usage-stats-row span {
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
  }

  .usage-sources {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 6px;
  }

  .source-pill {
    color: rgba(255, 255, 255, 0.35);
    font-size: 10px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 4px;
    padding: 1px 6px;
  }

  /* ── Activity tab ── */

  .search-input {
    width: 100%;
    height: 32px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: white;
    font-size: 13px;
    outline: none;
    margin-bottom: 10px;
    box-sizing: border-box;
  }

  .search-input::placeholder {
    color: rgba(255, 255, 255, 0.3);
  }

  .activity-count {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    margin-bottom: 8px;
  }

  .activity-card {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 6px;
    padding: 6px 10px;
    margin-bottom: 4px;
    cursor: pointer;
    border: none;
    width: 100%;
    text-align: left;
    color: inherit;
    font-family: inherit;
    transition: background 0.15s;
  }

  .activity-card:hover {
    background: rgba(255, 255, 255, 0.05);
  }

  .activity-card.expanded {
    background: rgba(255, 255, 255, 0.06);
  }

  .activity-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 24px;
  }

  .activity-badge {
    font-size: 9px;
    font-weight: bold;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 4px;
    padding: 2px 6px;
    min-width: 36px;
    text-align: center;
  }

  .activity-flag {
    color: #ff6b6b;
    font-size: 11px;
    font-weight: bold;
    background: rgba(255, 100, 100, 0.15);
    border-radius: 8px;
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .activity-action {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: bold;
  }

  .activity-agent {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
  }

  .activity-spacer {
    flex: 1;
  }

  .activity-time {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    white-space: nowrap;
  }

  .activity-detail {
    margin: 6px 0 2px;
    padding: 8px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-family: var(--font-mono);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
    overflow-y: auto;
  }

  .placeholder {
    color: var(--text-dim);
    font-size: 13px;
    text-align: center;
    padding: 40px 0;
  }

  /* -- Updates tab -- */

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

  /* -- Jobs tab -- */

  .job-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .job-info {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 0;
  }

  .job-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 600;
  }

  .job-schedule {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    font-family: var(--font-mono);
  }

  .job-status {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 100, 100, 0.1);
    color: rgba(255, 100, 100, 0.6);
  }

  .job-status.installed {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.6);
  }

  .job-actions {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
  }

  .job-btn {
    padding: 3px 10px;
    font-size: 11px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 4px;
    cursor: pointer;
    font-family: var(--font-sans);
    transition: background 0.15s, color 0.15s;
  }

  .job-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .job-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .job-desc {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    padding: 0 0 6px 0;
  }

  .job-log {
    margin: 4px 0 10px;
    padding: 8px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-family: var(--font-mono);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 300px;
    overflow-y: auto;
  }

  .job-duration {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    font-family: var(--font-mono);
  }
</style>

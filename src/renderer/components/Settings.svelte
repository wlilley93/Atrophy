<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { api } from '../api';

  import SettingsTab from './settings/SettingsTab.svelte';
  import UsageTab from './settings/UsageTab.svelte';
  import ActivityTab from './settings/ActivityTab.svelte';
  import JobsTab from './settings/JobsTab.svelte';
  import UpdatesTab from './settings/UpdatesTab.svelte';
  import ConsoleTab from './settings/ConsoleTab.svelte';
  import AgentsTab from './settings/AgentsTab.svelte';
  import SystemTab from './settings/SystemTab.svelte';

  interface Props {
    onClose: () => void;
    onOpenSystemMap?: () => void;
  }

  let { onClose, onOpenSystemMap }: Props = $props();

  type Tab = 'settings' | 'agents' | 'system' | 'usage' | 'activity' | 'jobs' | 'updates' | 'console';
  let activeTab = $state<Tab>('settings');

  // ---------------------------------------------------------------------------
  // Config form state (owned here, bound into SettingsTab)
  // ---------------------------------------------------------------------------

  // Agents
  let agentList = $state<{ name: string; display_name: string; description: string; role: string }[]>([]);

  // Identity
  let userName = $state('');
  let agentDisplayName = $state('');
  let wakeWords = $state('');

  // Tools
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
  let telegramUsername = $state('');
  let telegramDaemonRunning = $state(false);

  // About
  let version = $state('0.0.0');
  let bundleRoot = $state('');

  // ---------------------------------------------------------------------------
  // Tab component refs
  // ---------------------------------------------------------------------------

  let agentsTab: AgentsTab;
  let systemTab: SystemTab;
  let usageTab: UsageTab;
  let activityTab: ActivityTab;
  let jobsTab: JobsTab;
  let updatesTab: UpdatesTab;
  let consoleTab: ConsoleTab;

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
      userName = cfg.userName ?? '';
      agentDisplayName = cfg.agentDisplayName ?? '';
      wakeWords = (cfg.wakeWords ?? []).join(', ');
      disabledTools = new Set(cfg.disabledTools ?? []);

      windowWidth = cfg.windowWidth ?? 622;
      windowHeight = cfg.windowHeight ?? 830;
      avatarEnabled = cfg.avatarEnabled ?? false;
      avatarResolution = cfg.avatarResolution ?? 512;

      ttsBackend = cfg.ttsBackend ?? 'elevenlabs';
      elevenlabsApiKey = cfg.elevenlabsApiKey ?? '';
      elevenlabsVoiceId = cfg.elevenlabsVoiceId ?? '';
      elevenlabsModel = cfg.elevenlabsModel ?? 'eleven_v3';
      elevenlabsStability = cfg.elevenlabsStability ?? 0.5;
      elevenlabsSimilarity = cfg.elevenlabsSimilarity ?? 0.75;
      elevenlabsStyle = cfg.elevenlabsStyle ?? 0.35;
      ttsPlaybackRate = cfg.ttsPlaybackRate ?? 1.12;
      falApiKey = cfg.falApiKey ?? '';
      falVoiceId = cfg.falVoiceId ?? '';

      inputMode = cfg.inputMode ?? 'dual';
      pttKey = cfg.pttKey ?? 'ctrl';
      wakeWordEnabled = cfg.wakeWordEnabled ?? false;
      wakeChunkSeconds = cfg.wakeChunkSeconds ?? 2;

      silenceTimerEnabled = cfg.silenceTimerEnabled ?? true;
      silenceTimerMinutes = cfg.silenceTimerMinutes ?? 5;
      eyeModeDefault = cfg.eyeModeDefault ?? false;
      muteByDefault = cfg.muteByDefault ?? false;

      keepAwakeActive = cfg.keepAwakeActive ?? false;
      notificationsEnabled = cfg.notificationsEnabled ?? true;

      sampleRate = cfg.sampleRate ?? 16000;
      maxRecordSec = cfg.maxRecordSec ?? 120;

      claudeBin = cfg.claudeBin ?? 'claude';
      claudeModel = cfg.claudeModel ?? 'claude-sonnet-4-6';
      claudeEffort = cfg.claudeEffort ?? 'medium';
      adaptiveEffort = cfg.adaptiveEffort ?? true;

      contextSummaries = cfg.contextSummaries ?? 3;
      maxContextTokens = cfg.maxContextTokens ?? 180000;
      vectorSearchWeight = cfg.vectorSearchWeight ?? 0.7;
      embeddingModel = cfg.embeddingModel ?? 'all-MiniLM-L6-v2';
      embeddingDim = cfg.embeddingDim ?? 384;

      sessionSoftLimitMins = cfg.sessionSoftLimitMins ?? 60;

      heartbeatActiveStart = cfg.heartbeatActiveStart ?? 9;
      heartbeatActiveEnd = cfg.heartbeatActiveEnd ?? 22;
      heartbeatIntervalMins = cfg.heartbeatIntervalMins ?? 30;

      obsidianVault = cfg.obsidianVault ?? '';
      dbPath = cfg.dbPath ?? '';
      whisperBin = cfg.whisperBin ?? '';

      googleConfigured = cfg.googleConfigured ?? false;

      telegramBotToken = cfg.telegramBotToken ?? '';
      telegramChatId = cfg.telegramChatId ?? '';
      telegramUsername = cfg.telegramUsername ?? '';
      telegramDaemonRunning = cfg.telegramDaemonRunning ?? false;

      version = cfg.version ?? '0.0.0';
      bundleRoot = cfg.bundleRoot ?? '';
    } catch (e) {
      console.error('Failed to load config', e);
    }
  });

  // ---------------------------------------------------------------------------
  // Save / Apply
  // ---------------------------------------------------------------------------

  let saveStatus = $state('');

  function gatherUpdates(): Record<string, unknown> {
    return {
      USER_NAME: userName,
      AGENT_DISPLAY_NAME: agentDisplayName,
      WAKE_WORDS: wakeWords.split(',').map((w: string) => w.trim()).filter(Boolean),
      DISABLED_TOOLS: [...disabledTools],
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
      TELEGRAM_USERNAME: telegramUsername,
    };
  }

  async function apply() {
    if (!api) return;
    try {
      await api.applyConfig(gatherUpdates());
      saveStatus = 'Applied (not saved)';
      setTimeout(() => saveStatus = '', 3000);
    } catch {
      saveStatus = 'Error';
      setTimeout(() => saveStatus = '', 3000);
    }
  }

  async function save() {
    if (!api) return;
    try {
      await api.updateConfig(gatherUpdates());
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
      setTimeout(() => saveStatus = '', 3000);
    }
  }

  async function resetSetup() {
    if (!api) return;
    await api.updateConfig({ setup_complete: false });
    saveStatus = 'Setup will re-run on next launch';
    setTimeout(() => saveStatus = '', 3000);
  }

  // ---------------------------------------------------------------------------
  // Tab switching
  // ---------------------------------------------------------------------------

  async function switchTab(tab: Tab) {
    // Clean up console log listener when leaving that tab
    if (activeTab === 'console' && tab !== 'console') consoleTab?.cleanup();
    activeTab = tab;
    await tick(); // Wait for Svelte to mount the new tab component before calling load()
    if (tab === 'agents') agentsTab?.load();
    if (tab === 'system') systemTab?.load();
    if (tab === 'usage') usageTab?.load();
    if (tab === 'activity') activityTab?.load();
    if (tab === 'jobs') jobsTab?.load();
    if (tab === 'updates') updatesTab?.load();
    if (tab === 'console') consoleTab?.load();
  }

  function close() {
    if (activeTab === 'console') consoleTab?.cleanup();
    onClose();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="settings-fullscreen" data-no-drag>
  <nav class="settings-sidebar">
    <button class="sidebar-back" onclick={close}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
      Back
    </button>

    <div class="sidebar-group">
      <div class="sidebar-group-label">General</div>
      <button class="sidebar-item" class:active={activeTab === 'settings'} onclick={() => switchTab('settings')}>Settings</button>
      <button class="sidebar-item" class:active={activeTab === 'agents'} onclick={() => switchTab('agents')}>Agents</button>
      <button class="sidebar-item" class:active={activeTab === 'system'} onclick={() => switchTab('system')}>System Map</button>
    </div>

    <div class="sidebar-group">
      <div class="sidebar-group-label">Data</div>
      <button class="sidebar-item" class:active={activeTab === 'usage'} onclick={() => switchTab('usage')}>Usage</button>
      <button class="sidebar-item" class:active={activeTab === 'activity'} onclick={() => switchTab('activity')}>Activity</button>
    </div>

    <div class="sidebar-group">
      <div class="sidebar-group-label">System</div>
      <button class="sidebar-item" class:active={activeTab === 'jobs'} onclick={() => switchTab('jobs')}>Jobs</button>
      <button class="sidebar-item" class:active={activeTab === 'updates'} onclick={() => switchTab('updates')}>Updates</button>
      <button class="sidebar-item" class:active={activeTab === 'console'} onclick={() => switchTab('console')}>Console</button>
    </div>
  </nav>

  <main class="settings-content" class:no-pad={activeTab === 'agents'}>

    {#if activeTab === 'settings'}
      <SettingsTab
        bind:agentList
        bind:userName
        bind:agentDisplayName
        bind:wakeWords
        bind:disabledTools
        bind:windowWidth
        bind:windowHeight
        bind:avatarEnabled
        bind:avatarResolution
        bind:ttsBackend
        bind:elevenlabsApiKey
        bind:elevenlabsVoiceId
        bind:elevenlabsModel
        bind:elevenlabsStability
        bind:elevenlabsSimilarity
        bind:elevenlabsStyle
        bind:ttsPlaybackRate
        bind:falApiKey
        bind:falVoiceId
        bind:inputMode
        bind:pttKey
        bind:wakeWordEnabled
        bind:wakeChunkSeconds
        bind:silenceTimerEnabled
        bind:silenceTimerMinutes
        bind:eyeModeDefault
        bind:muteByDefault
        bind:keepAwakeActive
        bind:notificationsEnabled
        bind:sampleRate
        bind:maxRecordSec
        bind:claudeBin
        bind:claudeModel
        bind:claudeEffort
        bind:adaptiveEffort
        bind:contextSummaries
        bind:maxContextTokens
        bind:vectorSearchWeight
        bind:embeddingModel
        bind:embeddingDim
        bind:sessionSoftLimitMins
        bind:heartbeatActiveStart
        bind:heartbeatActiveEnd
        bind:heartbeatIntervalMins
        bind:obsidianVault
        {dbPath}
        {whisperBin}
        {googleConfigured}
        {googleAuthStatus}
        bind:telegramBotToken
        bind:telegramChatId
        bind:telegramUsername
        bind:telegramDaemonRunning
        {version}
        {bundleRoot}
        {saveStatus}
        {onClose}
        onApply={apply}
        onSave={save}
        onResetSetup={resetSetup}
      />

    {:else if activeTab === 'agents'}
      <AgentsTab bind:this={agentsTab} />

    {:else if activeTab === 'system'}
      <SystemTab bind:this={systemTab} />

    {:else if activeTab === 'usage'}
      <UsageTab bind:this={usageTab} />

    {:else if activeTab === 'activity'}
      <ActivityTab bind:this={activityTab} />

    {:else if activeTab === 'jobs'}
      <JobsTab bind:this={jobsTab} />

    {:else if activeTab === 'updates'}
      <UpdatesTab bind:this={updatesTab} {version} />

    {:else if activeTab === 'console'}
      <ConsoleTab bind:this={consoleTab} />

    {/if}
  </main>
</div>

<style>
  .settings-fullscreen {
    position: absolute;
    inset: 0;
    display: flex;
    background: var(--bg, #0C0C0E);
    z-index: 60;
    -webkit-app-region: no-drag;
    overflow: hidden;
  }

  .settings-sidebar {
    width: 180px;
    flex-shrink: 0;
    min-height: 0;
    background: rgba(8, 8, 10, 0.98);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 38px 0 12px; /* Leave room for macOS traffic lights */
    overflow-y: auto;
    -webkit-app-region: drag;
  }

  .sidebar-back {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    margin: 0 8px 12px;
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.5);
    font-size: 13px;
    font-family: var(--font-sans);
    cursor: pointer;
    border-radius: 6px;
    -webkit-app-region: no-drag;
    transition: color 0.15s, background 0.15s;
  }

  .sidebar-back:hover {
    color: rgba(255, 255, 255, 0.8);
    background: rgba(255, 255, 255, 0.04);
  }

  .sidebar-group {
    margin-bottom: 16px;
  }

  .sidebar-group-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgba(255, 255, 255, 0.25);
    padding: 0 20px 4px;
  }

  .sidebar-item {
    display: block;
    width: 100%;
    padding: 7px 20px;
    background: none;
    border: none;
    border-left: 2px solid transparent;
    color: rgba(255, 255, 255, 0.55);
    font-size: 13px;
    font-family: var(--font-sans);
    text-align: left;
    cursor: pointer;
    -webkit-app-region: no-drag;
    transition: color 0.15s, background 0.15s;
  }

  .sidebar-item:hover {
    color: rgba(255, 255, 255, 0.8);
    background: rgba(255, 255, 255, 0.03);
  }

  .sidebar-item.active {
    color: rgba(255, 255, 255, 0.9);
    border-left-color: rgba(100, 140, 255, 0.6);
    background: rgba(100, 140, 255, 0.06);
  }

  .settings-content {
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 24px 28px;
  }

  .settings-content.no-pad {
    padding: 0;
    overflow: hidden;
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
</style>

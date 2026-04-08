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
  import FederationTab from './settings/FederationTab.svelte';

  interface Props {
    onClose: () => void;
    onOpenSystemMap?: () => void;
  }

  let { onClose, onOpenSystemMap }: Props = $props();

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  type SettingsPage = 'general' | 'voice' | 'input' | 'engine' | 'telegram' | 'connections' | 'about';
  type ComponentPage = 'agents' | 'system' | 'usage' | 'activity' | 'jobs' | 'updates' | 'console' | 'federation';
  type PageId = SettingsPage | ComponentPage;

  interface NavItem {
    id: PageId;
    label: string;
    keywords: string[];
    icon: string; // SVG path data (24x24 viewBox)
    isSettingsPage?: boolean;
  }

  interface NavGroup {
    label: string;
    items: NavItem[];
  }

  const NAV_GROUPS: NavGroup[] = [
    {
      label: 'General',
      items: [
        { id: 'general', label: 'General', icon: 'M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z', keywords: ['name', 'identity', 'window', 'avatar', 'display', 'width', 'height', 'eye mode', 'silence', 'wake', 'tools'], isSettingsPage: true },
        { id: 'agents', label: 'Agents', icon: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75', keywords: ['agent', 'switch', 'create', 'organisation', 'org', 'hierarchy', 'mirror'] },
      ],
    },
    {
      label: 'Voice & Input',
      items: [
        { id: 'voice', label: 'Voice & TTS', icon: 'M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z M19 10v2a7 7 0 0 1-14 0v-2 M12 19v4 M8 23h8', keywords: ['voice', 'tts', 'elevenlabs', 'fal', 'mute', 'playback', 'stability', 'similarity', 'style'], isSettingsPage: true },
        { id: 'input', label: 'Input & Audio', icon: 'M18 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3 3 3 0 0 0-3-3H6a3 3 0 0 0-3 3 3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0 3 3h12a3 3 0 0 0 3-3 3 3 0 0 0-3-3z', keywords: ['input', 'push to talk', 'ptt', 'wake word', 'audio', 'sample rate', 'record', 'notifications', 'keep awake'], isSettingsPage: true },
      ],
    },
    {
      label: 'Engine',
      items: [
        { id: 'engine', label: 'Inference & Memory', icon: 'M22 12h-4l-3 9L9 3l-3 9H2', keywords: ['inference', 'claude', 'model', 'effort', 'memory', 'context', 'vector', 'embedding', 'session', 'heartbeat', 'tokens'], isSettingsPage: true },
      ],
    },
    {
      label: 'Connections',
      items: [
        { id: 'telegram', label: 'Telegram', icon: 'M22 2L11 13 M22 2l-7 20-4-9-9-4 20-7z', keywords: ['telegram', 'bot', 'token', 'chat id', 'daemon', 'polling'], isSettingsPage: true },
        { id: 'connections', label: 'Services & Paths', icon: 'M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71 M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71', keywords: ['google', 'oauth', 'obsidian', 'vault', 'database', 'whisper', 'path'], isSettingsPage: true },
      ],
    },
    {
      label: 'System',
      items: [
        { id: 'system', label: 'System Map', icon: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z M3.27 6.96L12 12.01l8.73-5.05 M12 22.08V12', keywords: ['system', 'mcp', 'topology', 'server'] },
        { id: 'jobs', label: 'Jobs', icon: 'M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10z M12 6v6l4 2', keywords: ['jobs', 'cron', 'schedule', 'task'] },
        { id: 'federation', label: 'Federation', icon: 'M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10z M2 12h20 M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z', keywords: ['federation', 'link', 'trust', 'cross-instance'] },
      ],
    },
    {
      label: 'Monitoring',
      items: [
        { id: 'usage', label: 'Usage', icon: 'M18 20V10 M12 20V4 M6 20v-6', keywords: ['usage', 'tokens', 'cost', 'spend'] },
        { id: 'activity', label: 'Activity', icon: 'M22 12h-4l-3 9L9 3l-3 9H2', keywords: ['activity', 'log', 'history', 'events'] },
        { id: 'console', label: 'Console', icon: 'M4 17l6-6-6-6 M12 19h8', keywords: ['console', 'logs', 'debug', 'output', 'terminal'] },
      ],
    },
    {
      label: 'App',
      items: [
        { id: 'updates', label: 'Updates', icon: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3', keywords: ['update', 'version', 'bundle', 'download'] },
        { id: 'about', label: 'About', icon: 'M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10z M12 16v-4 M12 8h.01', keywords: ['about', 'version', 'reset', 'setup', 'install'], isSettingsPage: true },
      ],
    },
  ];

  const SETTINGS_PAGES = new Set<string>(
    NAV_GROUPS.flatMap(g => g.items.filter(i => i.isSettingsPage).map(i => i.id))
  );

  let activePage = $state<PageId>('general');
  let searchQuery = $state('');
  let originalWindowSize = $state<{ width: number; height: number } | null>(null);

  // Derived: filtered nav groups for search
  let filteredGroups = $derived.by(() => {
    if (!searchQuery.trim()) return NAV_GROUPS;
    const q = searchQuery.toLowerCase();
    return NAV_GROUPS.map(g => ({
      ...g,
      items: g.items.filter(item =>
        item.label.toLowerCase().includes(q) ||
        item.keywords.some(k => k.includes(q))
      ),
    })).filter(g => g.items.length > 0);
  });

  let isOnSettingsPage = $derived(SETTINGS_PAGES.has(activePage));

  // ---------------------------------------------------------------------------
  // Config form state (owned here, bound into SettingsTab)
  // ---------------------------------------------------------------------------

  let agentList = $state<{ name: string; display_name: string; description: string; role: string }[]>([]);
  let userName = $state('');
  let agentDisplayName = $state('');
  let wakeWords = $state('');
  let disabledTools = $state<Set<string>>(new Set());

  let windowWidth = $state(622);
  let windowHeight = $state(830);
  let avatarEnabled = $state(false);
  let avatarResolution = $state(512);

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

  let inputMode = $state('dual');
  let pttKey = $state('ctrl');
  let wakeWordEnabled = $state(false);
  let wakeChunkSeconds = $state(2);

  let silenceTimerEnabled = $state(true);
  let silenceTimerMinutes = $state(5);
  let eyeModeDefault = $state(false);
  let muteByDefault = $state(false);
  let keepAwakeActive = $state(false);
  let notificationsEnabled = $state(true);

  let sampleRate = $state(16000);
  let maxRecordSec = $state(120);

  let claudeBin = $state('claude');
  let claudeModel = $state('claude-sonnet-4-6');
  let claudeEffort = $state('medium');
  let adaptiveEffort = $state(true);

  let contextSummaries = $state(3);
  let maxContextTokens = $state(180000);
  let vectorSearchWeight = $state(0.7);
  let embeddingModel = $state('all-MiniLM-L6-v2');
  let embeddingDim = $state(384);

  let sessionSoftLimitMins = $state(60);

  let heartbeatActiveStart = $state(9);
  let heartbeatActiveEnd = $state(22);
  let heartbeatIntervalMins = $state(30);

  let obsidianVault = $state('');
  let dbPath = $state('');
  let whisperBin = $state('');

  let googleConfigured = $state(false);
  let googleAuthStatus = $state('');

  let telegramBotToken = $state('');
  let telegramChatId = $state('');
  let telegramUsername = $state('');
  let telegramDaemonRunning = $state(false);

  let version = $state('0.0.0');
  let bundleRoot = $state('');

  // ---------------------------------------------------------------------------
  // Component refs
  // ---------------------------------------------------------------------------

  let agentsTab: AgentsTab;
  let systemTab: SystemTab;
  let usageTab: UsageTab;
  let activityTab: ActivityTab;
  let jobsTab: JobsTab;
  let updatesTab: UpdatesTab;
  let consoleTab: ConsoleTab;
  let federationTab: FederationTab;

  // ---------------------------------------------------------------------------
  // Load config + expand window on mount
  // ---------------------------------------------------------------------------

  onMount(async () => {
    if (!api) return;

    // Store original window size and expand for settings.
    // Settings is a wide two-column layout (nav + content). 1600x1200 gives
    // Activity logs, Console streams, and the Agents/Org tabs proper room
    // to breathe alongside the larger main-window default (1100x1466).
    try {
      const size = await api.getWindowSize();
      originalWindowSize = size;
      await api.setWindowSize(1600, 1200);
    } catch { /* pre-existing window, skip resize */ }

    try {
      const [cfg, fullAgents] = await Promise.all([
        api.getConfig(),
        api.getAgentsFull(),
      ]);
      agentList = fullAgents || [];

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
  // Page switching
  // ---------------------------------------------------------------------------

  async function switchPage(id: PageId) {
    if (activePage === 'console' && id !== 'console') consoleTab?.cleanup();
    activePage = id;
    await tick();
    if (id === 'agents') agentsTab?.load();
    if (id === 'system') systemTab?.load();
    if (id === 'usage') usageTab?.load();
    if (id === 'activity') activityTab?.load();
    if (id === 'jobs') jobsTab?.load();
    if (id === 'updates') updatesTab?.load();
    if (id === 'console') consoleTab?.load();
    if (id === 'federation') federationTab?.load();
  }

  function close() {
    if (activePage === 'console') consoleTab?.cleanup();
    if (api && originalWindowSize) {
      api.setWindowSize(originalWindowSize.width, originalWindowSize.height);
    }
    onClose();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="settings-fullscreen" data-no-drag>
  <!-- Left nav pane -->
  <nav class="settings-nav">
    <button class="nav-back" onclick={close}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
      Back
    </button>

    <!-- Search -->
    <div class="nav-search-wrap">
      <svg class="nav-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <input
        type="text"
        class="nav-search"
        placeholder="Search settings..."
        bind:value={searchQuery}
      />
      {#if searchQuery}
        <button class="nav-search-clear" onclick={() => searchQuery = ''}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      {/if}
    </div>

    <!-- Category list -->
    <div class="nav-list">
      {#each filteredGroups as group}
        <div class="nav-group">
          <div class="nav-group-label">{group.label}</div>
          {#each group.items as item}
            <button
              class="nav-item"
              class:active={activePage === item.id}
              onclick={() => switchPage(item.id)}
            >
              <svg class="nav-item-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d={item.icon}/>
              </svg>
              <span class="nav-item-label">{item.label}</span>
              <svg class="nav-item-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
            </button>
          {/each}
        </div>
      {/each}

      {#if filteredGroups.length === 0}
        <div class="nav-empty">No matching settings</div>
      {/if}
    </div>
  </nav>

  <!-- Right content pane -->
  <main class="settings-content" class:no-pad={activePage === 'agents'}>

    {#if SETTINGS_PAGES.has(activePage)}
      <SettingsTab
        page={activePage as SettingsPage}
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

    {:else if activePage === 'agents'}
      <AgentsTab bind:this={agentsTab} />

    {:else if activePage === 'system'}
      <SystemTab bind:this={systemTab} />

    {:else if activePage === 'usage'}
      <UsageTab bind:this={usageTab} />

    {:else if activePage === 'activity'}
      <ActivityTab bind:this={activityTab} />

    {:else if activePage === 'jobs'}
      <JobsTab bind:this={jobsTab} />

    {:else if activePage === 'updates'}
      <UpdatesTab bind:this={updatesTab} {version} />

    {:else if activePage === 'console'}
      <ConsoleTab bind:this={consoleTab} />

    {:else if activePage === 'federation'}
      <FederationTab bind:this={federationTab} />

    {/if}

    <!-- Sticky save bar - only for settings pages -->
    {#if isOnSettingsPage}
      <div class="save-bar">
        {#if saveStatus}
          <span class="save-bar-status">{saveStatus}</span>
        {/if}
        <button class="save-bar-btn" onclick={apply}>Apply</button>
        <button class="save-bar-btn primary" onclick={save}>Save</button>
      </div>
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

  /* ── Nav pane ────────────────────────────────────────────── */

  .settings-nav {
    width: 220px;
    flex-shrink: 0;
    min-height: 0;
    background: rgba(8, 8, 10, 0.98);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 38px 0 12px;
    overflow: hidden;
    -webkit-app-region: drag;
  }

  .nav-back {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    margin: 0 8px 8px;
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.45);
    font-size: 13px;
    font-family: var(--font-sans);
    cursor: pointer;
    border-radius: 6px;
    -webkit-app-region: no-drag;
    transition: color 0.15s, background 0.15s;
  }

  .nav-back:hover {
    color: rgba(255, 255, 255, 0.75);
    background: rgba(255, 255, 255, 0.04);
  }

  /* ── Search ──────────────────────────────────────────────── */

  .nav-search-wrap {
    position: relative;
    margin: 0 10px 10px;
    -webkit-app-region: no-drag;
  }

  .nav-search-icon {
    position: absolute;
    left: 8px;
    top: 50%;
    transform: translateY(-50%);
    color: rgba(255, 255, 255, 0.25);
    pointer-events: none;
  }

  .nav-search {
    width: 100%;
    height: 30px;
    padding: 0 28px 0 28px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 12px;
    outline: none;
    transition: border-color 0.15s;
    box-sizing: border-box;
  }

  .nav-search:focus {
    border-color: rgba(255, 255, 255, 0.2);
  }

  .nav-search::placeholder {
    color: rgba(255, 255, 255, 0.2);
  }

  .nav-search-clear {
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: rgba(255, 255, 255, 0.3);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
  }

  .nav-search-clear:hover {
    color: rgba(255, 255, 255, 0.6);
    background: rgba(255, 255, 255, 0.06);
  }

  /* ── Category list ───────────────────────────────────────── */

  .nav-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 6px;
    -webkit-app-region: no-drag;
  }

  .nav-list::-webkit-scrollbar { width: 4px; }
  .nav-list::-webkit-scrollbar-track { background: transparent; }
  .nav-list::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.08); border-radius: 2px; }

  .nav-group {
    margin-bottom: 12px;
  }

  .nav-group-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgba(255, 255, 255, 0.2);
    padding: 0 10px 3px;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 7px 10px;
    background: none;
    border: none;
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.55);
    font-size: 13px;
    font-family: var(--font-sans);
    text-align: left;
    cursor: pointer;
    -webkit-app-region: no-drag;
    transition: color 0.15s, background 0.15s;
  }

  .nav-item:hover {
    color: rgba(255, 255, 255, 0.8);
    background: rgba(255, 255, 255, 0.04);
  }

  .nav-item.active {
    color: rgba(255, 255, 255, 0.9);
    background: rgba(100, 140, 255, 0.08);
  }

  .nav-item-icon {
    flex-shrink: 0;
    opacity: 0.5;
  }

  .nav-item.active .nav-item-icon {
    opacity: 0.8;
  }

  .nav-item-label {
    flex: 1;
  }

  .nav-item-chevron {
    flex-shrink: 0;
    opacity: 0.2;
  }

  .nav-item.active .nav-item-chevron {
    opacity: 0.4;
  }

  .nav-empty {
    padding: 20px 10px;
    color: rgba(255, 255, 255, 0.2);
    font-size: 12px;
    text-align: center;
  }

  /* ── Content pane ────────────────────────────────────────── */

  .settings-content {
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 24px 28px 80px; /* bottom padding for sticky save bar */
    position: relative;
  }

  .settings-content.no-pad {
    padding: 0 0 80px;
    overflow: hidden;
  }

  .settings-content::-webkit-scrollbar { width: 6px; }
  .settings-content::-webkit-scrollbar-track { background: rgba(255, 255, 255, 0.02); border-radius: 3px; }
  .settings-content::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 3px; }

  /* ── Sticky save bar ─────────────────────────────────────── */

  .save-bar {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
    padding: 12px 28px;
    background: rgba(12, 12, 14, 0.92);
    backdrop-filter: blur(12px);
    border-top: 1px solid var(--border);
    z-index: 10;
  }

  .save-bar-status {
    font-size: 12px;
    color: rgba(100, 220, 100, 0.7);
    margin-right: auto;
  }

  .save-bar-btn {
    padding: 7px 18px;
    border-radius: 7px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.85);
    font-family: var(--font-sans);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .save-bar-btn:hover {
    background: rgba(255, 255, 255, 0.16);
  }

  .save-bar-btn.primary {
    background: rgba(100, 140, 255, 0.15);
    border-color: rgba(100, 140, 255, 0.3);
  }

  .save-bar-btn.primary:hover {
    background: rgba(100, 140, 255, 0.25);
  }
</style>

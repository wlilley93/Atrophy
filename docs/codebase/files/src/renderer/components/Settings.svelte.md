# src/renderer/components/Settings.svelte - Settings Modal

**Line count:** ~581 lines  
**Dependencies:** `svelte`, `../api`, tab component imports  
**Purpose:** Settings modal with multiple tabs (Settings, Agents, System, Usage, Activity, Jobs, Updates, Console)

## Overview

This component provides a comprehensive settings modal with 8 tabs covering all configuration aspects of the application. It owns the config form state and passes it to tab components via binding.

## Props

```typescript
interface Props {
  onClose: () => void;
  onOpenSystemMap?: () => void;
}
```

## Tab Types

```typescript
type Tab = 'settings' | 'agents' | 'system' | 'usage' | 'activity' | 'jobs' | 'updates' | 'console';
let activeTab = $state<Tab>('settings');
```

**Available tabs:**
1. **settings** - General configuration
2. **agents** - Agent management
3. **system** - System topology
4. **usage** - Token usage statistics
5. **activity** - Activity feed
6. **jobs** - Background job management
7. **updates** - Update management
8. **console** - Log console

## Config Form State

### Identity

```typescript
let userName = $state('');
let agentDisplayName = $state('');
let wakeWords = $state('');
```

### Tools

```typescript
let disabledTools = $state<Set<string>>(new Set());
```

### Window

```typescript
let windowWidth = $state(622);
let windowHeight = $state(830);
let avatarEnabled = $state(false);
let avatarResolution = $state(512);
```

### Voice

```typescript
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
```

### Input

```typescript
let inputMode = $state('dual');
let pttKey = $state('ctrl');
let wakeWordEnabled = $state(false);
let wakeChunkSeconds = $state(2);
```

### Silence Timer

```typescript
let silenceTimerEnabled = $state(true);
let silenceTimerMinutes = $state(5);
```

### UI Defaults

```typescript
let eyeModeDefault = $state(false);
let muteByDefault = $state(false);
```

### Keep Awake

```typescript
let keepAwakeActive = $state(false);
```

### Notifications

```typescript
let notificationsEnabled = $state(true);
```

### Audio

```typescript
let sampleRate = $state(16000);
let maxRecordSec = $state(120);
```

### Inference

```typescript
let claudeBin = $state('claude');
let claudeModel = $state('claude-sonnet-4-6');
let claudeEffort = $state('medium');
let adaptiveEffort = $state(true);
```

### Memory

```typescript
let contextSummaries = $state(3);
let maxContextTokens = $state(180000);
let vectorSearchWeight = $state(0.7);
let embeddingModel = $state('all-MiniLM-L6-v2');
let embeddingDim = $state(384);
```

### Session

```typescript
let sessionSoftLimitMins = $state(60);
```

### Heartbeat

```typescript
let heartbeatActiveStart = $state(9);
let heartbeatActiveEnd = $state(22);
let heartbeatIntervalMins = $state(30);
```

### Paths

```typescript
let obsidianVault = $state('');
let dbPath = $state('');
let whisperBin = $state('');
```

### Google

```typescript
let googleConfigured = $state(false);
let googleAuthStatus = $state('');
```

### Telegram

```typescript
let telegramBotToken = $state('');
let telegramChatId = $state('');
let telegramUsername = $state('');
let telegramDaemonRunning = $state(false);
```

### About

```typescript
let version = $state('0.0.0');
let bundleRoot = $state('');
```

## Tab Component References

```typescript
let agentsTab: AgentsTab;
let systemTab: SystemTab;
let usageTab: UsageTab;
let activityTab: ActivityTab;
let jobsTab: JobsTab;
let updatesTab: UpdatesTab;
let consoleTab: ConsoleTab;
```

## Lifecycle

### onMount

```typescript
onMount(async () => {
  if (!api) return;
  try {
    const [cfg, fullAgents] = await Promise.all([
      api.getConfig(),
      api.getAgentsFull(),
    ]);
    agentList = fullAgents || [];

    // Populate form from config
    userName = cfg.userName ?? '';
    agentDisplayName = cfg.agentDisplayName ?? '';
    // ... populate all form fields
  } catch { /* handle error */ }
});
```

**Purpose:** Load config and agents on mount.

## Tab Components

### Imported Tabs

```typescript
import SettingsTab from './settings/SettingsTab.svelte';
import UsageTab from './settings/UsageTab.svelte';
import ActivityTab from './settings/ActivityTab.svelte';
import JobsTab from './settings/JobsTab.svelte';
import UpdatesTab from './settings/UpdatesTab.svelte';
import ConsoleTab from './settings/ConsoleTab.svelte';
import AgentsTab from './settings/AgentsTab.svelte';
import SystemTab from './settings/SystemTab.svelte';
```

### Tab Rendering

```svelte
<div class="settings-modal" data-no-drag>
  <!-- Tab navigation -->
  <div class="tab-nav">
    <button class:active={activeTab === 'settings'} onclick={() => activeTab = 'settings'}>Settings</button>
    <button class:active={activeTab === 'agents'} onclick={() => activeTab = 'agents'}>Agents</button>
    <button class:active={activeTab === 'system'} onclick={() => activeTab = 'system'}>System</button>
    <button class:active={activeTab === 'usage'} onclick={() => activeTab = 'usage'}>Usage</button>
    <button class:active={activeTab === 'activity'} onclick={() => activeTab = 'activity'}>Activity</button>
    <button class:active={activeTab === 'jobs'} onclick={() => activeTab = 'jobs'}>Jobs</button>
    <button class:active={activeTab === 'updates'} onclick={() => activeTab = 'updates'}>Updates</button>
    <button class:active={activeTab === 'console'} onclick={() => activeTab = 'console'}>Console</button>
  </div>

  <!-- Tab content -->
  <div class="tab-content">
    {#if activeTab === 'settings'}
      <SettingsTab 
        bind:userName
        bind:agentDisplayName
        bind:wakeWords
        bind:disabledTools
        bind:windowWidth
        bind:windowHeight
        bind:avatarEnabled
        bind:avatarResolution
        bind:falApiKey
        bind:ttsBackend
        bind:elevenlabsApiKey
        bind:elevenlabsVoiceId
        bind:elevenlabsModel
        bind:elevenlabsStability
        bind:elevenlabsSimilarity
        bind:elevenlabsStyle
        bind:ttsPlaybackRate
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
        bind:dbPath
        bind:whisperBin
        bind:googleConfigured
        bind:googleAuthStatus
        bind:telegramBotToken
        bind:telegramChatId
        bind:telegramUsername
        bind:telegramDaemonRunning
        bind:version
        bind:bundleRoot
        onSave={saveConfig}
      />
    {:else if activeTab === 'agents'}
      <AgentsTab bind:this={agentsTab} bind:agentList />
    {:else if activeTab === 'system'}
      <SystemTab bind:this={systemTab} onOpenSystemMap={onOpenSystemMap} />
    {:else if activeTab === 'usage'}
      <UsageTab bind:this={usageTab} />
    {:else if activeTab === 'activity'}
      <ActivityTab bind:this={activityTab} />
    {:else if activeTab === 'jobs'}
      <JobsTab bind:this={jobsTab} />
    {:else if activeTab === 'updates'}
      <UpdatesTab bind:this={updatesTab} />
    {:else if activeTab === 'console'}
      <ConsoleTab bind:this={consoleTab} />
    {/if}
  </div>

  <!-- Close button -->
  <button class="close-btn" onclick={onClose}>✕</button>
</div>
```

## saveConfig

```typescript
async function saveConfig() {
  if (!api) return;
  
  const updates = {
    userName,
    AGENT_DISPLAY_NAME: agentDisplayName,
    WAKE_WORDS: wakeWords.split(',').map(s => s.trim()),
    DISABLED_TOOLS: Array.from(disabledTools),
    WINDOW_WIDTH: windowWidth,
    WINDOW_HEIGHT: windowHeight,
    AVATAR_ENABLED: avatarEnabled,
    AVATAR_RESOLUTION: avatarResolution,
    // ... all other fields
  };

  await api.updateConfig(updates);
}
```

**Purpose:** Save config changes to main process.

## Styling

```css
.settings-modal {
  position: absolute;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, 0.95);
  display: flex;
  flex-direction: column;
}

.tab-nav {
  display: flex;
  gap: 8px;
  padding: 20px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}

.tab-nav button {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: none;
  border-radius: 8px;
  color: var(--text-dim);
  cursor: pointer;
  white-space: nowrap;
}

.tab-nav button.active {
  background: var(--accent);
  color: white;
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.close-btn {
  position: absolute;
  top: 20px;
  right: 20px;
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 24px;
  cursor: pointer;
  padding: 8px;
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/renderer/components/settings/SettingsTab.svelte` - Settings tab component
- `src/main/ipc/config.ts` - Config IPC handlers

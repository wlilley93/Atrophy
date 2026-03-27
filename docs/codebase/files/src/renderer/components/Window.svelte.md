# src/renderer/components/Window.svelte - Main Layout Orchestrator

**Line count:** ~2182 lines  
**Dependencies:** `svelte`, component imports, store imports, `../api`  
**Purpose:** Main layout orchestrator - manages boot sequence, overlay coordination, agent switching, deferrals, ask-user dialogs

## Overview

Window.svelte is the root layout component that orchestrates the entire application UI. It manages the boot sequence, coordinates which overlays are visible, handles agent switching animations, agent deferral handoffs, ask-user dialogs, and the silence timer.

## Component Imports

```typescript
import OrbAvatar from './OrbAvatar.svelte';
import AgentName from './AgentName.svelte';
import Transcript from './Transcript.svelte';
import InputBar from './InputBar.svelte';
import ServiceCard from './ServiceCard.svelte';
import Timer from './Timer.svelte';
import Canvas from './Canvas.svelte';
import Artefact from './Artefact.svelte';
import Settings from './Settings.svelte';
import SystemMap from './SystemMap.svelte';
import SetupWizard from './SetupWizard.svelte';
import MirrorSetup from './MirrorSetup.svelte';
import SplashScreen from './SplashScreen.svelte';
import ShutdownScreen from './ShutdownScreen.svelte';
```

## Store Imports

```typescript
import { session } from '../stores/session.svelte';
import { audio } from '../stores/audio.svelte';
import { agents } from '../stores/agents.svelte';
import { addMessage, addDivider, completeLast, clearTranscript, transcript } from '../stores/transcript.svelte';
import { getArtifact } from '../stores/artifacts.svelte';
import { api } from '../api';
```

## State Variables

### Overlay Visibility

```typescript
let showSettings = $state(false);
let showTimer = $state(false);
let showCanvas = $state(false);
let showArtefact = $state(false);
let showSystemMap = $state(false);
let needsSetup = $state(false);
let mirrorSetupVisible = $state(false);
```

### Boot Sequence

```typescript
let updateCheckVisible = $state(true);
let updateStatus = $state<'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'up-to-date' | 'error'>('idle');
let updateVersion = $state('');
let updatePercent = $state(0);

let bootDecayVisible = $state(false);
let bootDecayFrame = $state(0);
let bootDecayOpacity = $state(1);
let bootDecayTimer: ReturnType<typeof setInterval> | null = null;

let splashVisible = $state(false);
let avatarDownloading = $state(false);
let avatarDownloadPercent = $state(0);

let shutdownVisible = $state(false);
```

### Mode Toggles

```typescript
let avatarVisible = $state(true);
let isMuted = $state(false);
let wakeListening = $state(false);
let hasNewArtefacts = $state(false);
let eyeMode = $state(false);  // Hides transcript when active
```

### Setup Flow

```typescript
let setupWizardPhase = $state<'welcome' | 'creating' | 'done' | 'hidden'>('hidden');
let setupActive = $state(false);
let setupJustEnteredChat = $state(false);
let setupServiceStep = $state(0);
let setupShowServiceCard = $state(false);
let setupServicesSaved: string[] = [];
let setupServicesSkipped: string[] = [];
let setupCreatedAgentName = $state('');
let setupUserName = $state('');
```

### Agent Switching

```typescript
let agentSwitchActive = $state(false);
let agentSwitchClip = $state('circle(0% at 50% 50%)');
```

### Agent Deferral

```typescript
let deferralActive = $state(false);
let deferralTarget = $state('');
let deferralProgress = $state(0);  // 0=start, 1=closing, 2=opening
```

### Ask-User Dialog

```typescript
let askVisible = $state(false);
let askQuestion = $state('');
let askActionType = $state<'question' | 'confirmation' | 'permission' | 'secure_input'>('question');
let askRequestId = $state('');
let askReply = $state('');
let askInputType = $state<'password' | 'email' | 'url' | 'number' | 'text'>('password');
let askLabel = $state('');
let askDestination = $state('');
let askShowSecure = $state(false);
```

### Silence Timer

```typescript
let lastInputTime = $state(Date.now());
let silencePromptVisible = $state(false);
let silenceTimerId: ReturnType<typeof setTimeout> | null = null;
let silenceTimerEnabled = true;
let silenceTimeoutMs = 5 * 60 * 1000;  // default 5 minutes
```

### Pending Updates

```typescript
let pendingUpdateVersion = $state<string | null>(null);
let pendingUpdateType = $state<'bundle' | 'app'>('bundle');
let pendingUpdateApplying = $state(false);
```

## Boot Sequence

### onMount

```typescript
onMount(async () => {
  // 1. Check if setup is needed
  needsSetup = await api.needsSetup();

  // 2. Load config
  const config = await api.getConfig();
  settings.userName = config.userName;
  settings.version = config.version;
  settings.avatarEnabled = config.avatarEnabled;
  settings.ttsBackend = config.ttsBackend;
  settings.inputMode = config.inputMode;
  settings.loaded = true;

  // 3. Load agents
  const agentsList = await api.getAgents();
  agents.list = agentsList;
  agents.current = config.agentName;
  agents.displayName = config.agentDisplayName;

  // 4. Load state
  isMuted = config.muteByDefault;
  eyeMode = config.eyeModeDefault;

  // 5. Start silence timer
  resetSilenceTimer();

  // 6. Boot sequence
  if (!needsSetup) {
    // Normal boot
    session.phase = 'boot';
    startBootDecay();
    setTimeout(() => {
      bootDecayVisible = false;
      splashVisible = true;
      setTimeout(() => {
        splashVisible = false;
        session.phase = 'ready';
      }, 2000);
    }, 1500);
  } else {
    // First launch - show setup wizard
    session.phase = 'setup';
  }

  // 7. Register IPC listeners
  const cleanup = registerIpcListeners();
  onDestroy(cleanup);
});
```

**Boot flow:**
1. Check setup needed
2. Load config → settings store
3. Load agents → agents store
4. Load state (mute, eye mode)
5. Start silence timer
6. Boot animation (decay → splash → ready)
7. Register IPC listeners

## IPC Event Handlers

### Inference Events

```typescript
api.onTextDelta((text) => {
  appendToLast(text);
  resetSilenceTimer();
});

api.onSentenceReady((sentence, index, ttsActive) => {
  // TTS handled automatically
});

api.onDone((fullText) => {
  completeLast();
  session.inferenceState = 'idle';
  resetSilenceTimer();
});

api.onError((message) => {
  completeLast();
  session.inferenceState = 'idle';
});

api.onArtifact((artifact) => {
  storeArtifact(artifact);
  hasNewArtefacts = true;
});
```

### Agent Events

```typescript
api.onAgentSwitched((data) => {
  agentSwitchActive = true;
  deferralProgress = 0;
  
  // Animate clip-path
  animateAgentSwitch();
  
  // Update stores
  agents.current = data.agentName;
  agents.displayName = data.agentDisplayName;
  
  // Clear transcript
  clearTranscript();
  
  // Reset session
  session.inferenceState = 'idle';
});

api.onDeferralRequest((data) => {
  deferralActive = true;
  deferralTarget = data.target;
  deferralProgress = 0;
  
  // Start codec-style handoff animation
  animateDeferral();
});
```

### Ask-User Events

```typescript
api.onAskUser((data) => {
  askVisible = true;
  askQuestion = data.question;
  askActionType = data.action_type;
  askRequestId = data.request_id;
  askInputType = data.input_type || 'text';
  askLabel = data.label || '';
  askDestination = data.destination || '';
  
  if (data.action_type === 'secure_input') {
    askShowSecure = true;
  }
});
```

## Agent Switch Animation

```typescript
function animateAgentSwitch() {
  // Start closing animation
  agentSwitchClip = 'circle(0% at 50% 50%)';
  deferralProgress = 1;
  
  setTimeout(() => {
    // Switch complete - start opening
    agentSwitchClip = 'circle(150% at 50% 50%)';
    deferralProgress = 2;
    
    setTimeout(() => {
      agentSwitchActive = false;
      agentSwitchClip = 'circle(0% at 50% 50%)';
      deferralProgress = 0;
    }, 400);
  }, 400);
}
```

**Animation:**
1. Circle closes to 0% (closing eye)
2. Agent switches
3. Circle opens to 150% (opening eye)
4. Reset to 0%

## Deferral Animation

```typescript
function animateDeferral() {
  // Phase 1: Closing
  deferralProgress = 1;
  
  setTimeout(() => {
    // Phase 2: Opening with new agent
    deferralProgress = 2;
    
    setTimeout(() => {
      deferralActive = false;
      deferralProgress = 0;
    }, 600);
  }, 400);
}
```

## Silence Timer

```typescript
function resetSilenceTimer() {
  lastInputTime = Date.now();
  if (silenceTimerId) clearTimeout(silenceTimerId);
  if (silencePromptVisible) return;
  
  if (silenceTimerEnabled) {
    silenceTimerId = setTimeout(() => {
      silencePromptVisible = true;
    }, silenceTimeoutMs);
  }
}

function dismissSilencePrompt() {
  silencePromptVisible = false;
  resetSilenceTimer();
}
```

**Purpose:** Prompt user after 5 minutes of inactivity.

## Ask-User Response

```typescript
async function submitAskResponse() {
  let response: string | boolean | null = askReply;
  
  if (askActionType === 'confirmation') {
    response = askReply.toLowerCase() === 'yes' || askReply === 'true';
  }
  
  await api.respondToAsk(askRequestId, response);
  askVisible = false;
  askReply = '';
}
```

## Template Structure

```svelte
<div class="window">
  <!-- Boot overlays -->
  {#if updateCheckVisible}
    <UpdateCheckScreen />
  {/if}
  
  {#if bootDecayVisible}
    <BootDecayScreen />
  {/if}
  
  {#if splashVisible}
    <SplashScreen />
  {/if}
  
  {#if shutdownVisible}
    <ShutdownScreen />
  {/if}
  
  <!-- Main content -->
  <div class="main-content">
    <!-- Orb avatar (background layer) -->
    {#if avatarVisible}
      <OrbAvatar />
    {/if}
    
    <!-- Agent name (top-left) -->
    <AgentName 
      name={agents.displayName}
      direction={agents.switchDirection}
      onCycleUp={() => cycleAgent(-1)}
      onCycleDown={() => cycleAgent(1)}
    />
    
    <!-- Transcript (flex body) -->
    <Transcript 
      messages={transcript.messages}
      onArtifactClick={(id) => showArtefact = true}
    />
    
    <!-- Input bar (bottom) -->
    <InputBar 
      disabled={session.inferenceState !== 'idle'}
      onSubmit={submitMessage}
    />
  </div>
  
  <!-- Overlays -->
  {#if showTimer}
    <Timer onClose={() => showTimer = false} />
  {/if}
  
  {#if showCanvas}
    <Canvas onClose={() => showCanvas = false} />
  {/if}
  
  {#if showArtefact}
    <Artefact onClose={() => showArtefact = false} />
  {/if}
  
  {#if showSettings}
    <Settings onClose={() => showSettings = false} />
  {/if}
  
  {#if showSystemMap}
    <SystemMap onClose={() => showSystemMap = false} />
  {/if}
  
  {#if setupWizardPhase !== 'hidden'}
    <SetupWizard 
      phase={setupWizardPhase}
      onComplete={() => setupWizardPhase = 'hidden'}
    />
  {/if}
  
  {#if mirrorSetupVisible}
    <MirrorSetup onClose={() => mirrorSetupVisible = false} />
  {/if}
  
  {#if askVisible}
    <AskDialog 
      question={askQuestion}
      actionType={askActionType}
      inputType={askInputType}
      label={askLabel}
      bind:reply={askReply}
      onConfirm={submitAskResponse}
      onCancel={() => askVisible = false}
    />
  {/if}
  
  {#if silencePromptVisible}
    <SilencePrompt onDismiss={dismissSilencePrompt} />
  {/if}
</div>
```

## Z-Index Layers

| Component | Z-Index |
|-----------|---------|
| OrbAvatar | 0 (background) |
| Transcript | 5 |
| AgentName, ThinkingIndicator, InputBar | 10 |
| Artefact | 40 |
| Canvas | 45 |
| Timer | 50 |
| SetupWizard, MirrorSetup | 70 |
| ShutdownScreen | 100 |

## Exported API

None - Window.svelte is the root component, not imported elsewhere.

## See Also

- `src/renderer/App.svelte` - Parent component that mounts Window
- `src/renderer/stores/session.svelte.ts` - Session state
- `src/main/ipc/agents.ts` - Agent switching IPC
- `src/main/ipc/inference.ts` - Inference events

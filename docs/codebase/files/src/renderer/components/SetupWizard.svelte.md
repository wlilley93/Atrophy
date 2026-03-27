# src/renderer/components/SetupWizard.svelte - Setup Wizard Overlay

**Line count:** ~309 lines  
**Dependencies:** `svelte`  
**Purpose:** Setup wizard overlay for welcome, creating, and done phases

## Overview

This component provides the setup wizard overlay that appears on first launch. It handles three phases: welcome (name input), creating (agent scaffolding), and done (brief intro before dismissal).

**Note:** The actual setup conversation (service cards + AI agent creation) happens in the main chat via Window.svelte, not in this component.

## Props

```typescript
type Phase = 'welcome' | 'creating' | 'done' | 'hidden';

let {
  phase = 'welcome',
  createdAgentName = '',
  onNameEntered,
  onComplete,
}: {
  phase: Phase;
  createdAgentName?: string;
  onNameEntered: (name: string) => void;
  onComplete?: () => void;
} = $props();
```

**Phases:**
- `welcome`: Ask user's name
- `creating`: Spinner while agent is scaffolded
- `done`: Brief "Meet X" before dismissal
- `hidden`: Wizard not visible

## State Variables

```typescript
let userName = $state('');
const brainFramePaths: string[] = [];  // Brain frames for welcome + done
```

## Brain Frame Loading

```typescript
const frameModules = import.meta.glob(
  '../../../resources/icons/brain_frames/brain_*.png',
  { eager: true, query: '?url', import: 'default' }
);
const sortedKeys = Object.keys(frameModules).sort();
for (const key of sortedKeys) {
  brainFramePaths.push(frameModules[key] as string);
}
```

**Source:** `resources/icons/brain_frames/brain_*.png`

## Functions

### submitName

```typescript
function submitName() {
  if (!userName.trim()) return;
  onNameEntered(userName.trim());
}
```

**Purpose:** Submit user name and proceed to next phase.

### onKeydown

```typescript
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitName();
  }
}
```

**Purpose:** Handle Enter key submission.

### Auto-dismiss Done Phase

```typescript
$effect(() => {
  if (phase === 'done') {
    const timer = setTimeout(() => {
      onComplete?.();
    }, 3000);
    return () => clearTimeout(timer);
  }
});
```

**Purpose:** Auto-dismiss after 3 seconds.

## Template

```svelte
{#if phase !== 'hidden'}
  <div class="wizard-overlay" data-no-drag>
    <div class="wizard-content">
      {#if phase === 'welcome'}
        <div class="wizard-center fade-in">
          {#if brainFramePaths.length > 0}
            <img class="welcome-brain" src={brainFramePaths[0]} alt="" draggable="false" />
          {/if}

          <h1 class="wizard-title">Atrophy</h1>
          <p class="wizard-tagline">Offload your mind.</p>
        </div>

      {:else if phase === 'creating'}
        <div class="wizard-center fade-in">
          <div class="creating-spinner"></div>
          <h2 class="wizard-title">Creating {createdAgentName}...</h2>
          <p class="wizard-subtitle">Building identity, voice, and prompts.</p>
        </div>

      {:else if phase === 'done'}
        <div class="wizard-center fade-in">
          {#if brainFramePaths.length > 0}
            <img class="welcome-brain" src={brainFramePaths[0]} alt="" draggable="false" />
          {/if}
          <h2 class="wizard-title">
            {createdAgentName ? `Meet ${createdAgentName}.` : 'Ready.'}
          </h2>
          <p class="wizard-subtitle">Starting up...</p>
        </div>
      {/if}
    </div>

    <!-- Name input pinned to bottom -->
    {#if phase === 'welcome'}
      <div class="name-bar-container fade-in">
        <p class="name-prompt">What is your name, human?</p>
        <div class="name-bar">
          <input
            type="text"
            bind:value={userName}
            onkeydown={onKeydown}
            class="name-input"
            placeholder="Your name"
            autofocus
          />
          {#if userName.trim()}
            <button class="name-submit-btn poof-in" onclick={submitName} aria-label="Continue">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="19" x2="12" y2="5"/>
                <polyline points="5 12 12 5 19 12"/>
              </svg>
            </button>
          {/if}
        </div>
      </div>
    {/if}
  </div>
{/if}
```

**Structure by phase:**

### Welcome Phase
1. Brain icon (frame 00)
2. Title: "Atrophy"
3. Tagline: "Offload your mind."
4. Name input bar (bottom pinned)

### Creating Phase
1. Spinning loader
2. Title: "Creating {name}..."
3. Subtitle: "Building identity, voice, and prompts."

### Done Phase
1. Brain icon (frame 00)
2. Title: "Meet {name}." or "Ready."
3. Subtitle: "Starting up..."
4. Auto-dismiss after 3 seconds

## Styling

```css
.wizard-overlay {
  position: absolute;
  inset: 0;
  z-index: 70;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.85);
  overflow: hidden;
}

.wizard-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.wizard-center {
  text-align: center;
  animation: fadeIn 0.5s ease;
}

.welcome-brain {
  width: 120px;
  height: 120px;
  object-fit: contain;
  filter: grayscale(0.3) brightness(0.85);
  margin-bottom: 24px;
}

.wizard-title {
  font-size: 48px;
  font-weight: 700;
  color: white;
  margin: 0 0 8px 0;
}

.wizard-tagline {
  font-size: 20px;
  color: var(--text-dim);
  margin: 0;
}

.creating-spinner {
  width: 48px;
  height: 48px;
  border: 4px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 24px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Name input bar */
.name-bar-container {
  position: absolute;
  bottom: 40px;
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.name-prompt {
  color: var(--text-dim);
  font-size: 16px;
}

.name-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  width: 400px;
  max-width: 90%;
}

.name-input {
  flex: 1;
  background: transparent;
  border: none;
  color: white;
  font-size: 16px;
  outline: none;
}

.name-submit-btn {
  background: var(--accent);
  border: none;
  border-radius: 8px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  cursor: pointer;
  animation: poofIn 0.3s ease;
}

@keyframes poofIn {
  from { opacity: 0; transform: scale(0.8); }
  to { opacity: 1; transform: scale(1); }
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component that manages wizard phase
- `src/main/ipc/window.ts` - Setup IPC handlers
- `src/main/create-agent.ts` - Agent scaffolding

<script lang="ts">
  /**
   * Setup wizard overlay - welcome screen + creating/done transitions.
   *
   * The actual setup conversation (service cards + AI agent creation)
   * happens in the main chat via Window.svelte, using the real Transcript
   * and InputBar - not static screens.
   *
   * This component only handles:
   *   welcome  - ask user's name
   *   creating - spinner while agent is scaffolded
   *   done     - brief "Meet X" before dismissal
   */

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

  let userName = $state('');

  // Brain frames for welcome + done
  const brainFramePaths: string[] = [];
  const frameModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: true, query: '?url', import: 'default' }
  );
  const sortedKeys = Object.keys(frameModules).sort();
  for (const key of sortedKeys) {
    brainFramePaths.push(frameModules[key] as string);
  }

  function submitName() {
    if (!userName.trim()) return;
    onNameEntered(userName.trim());
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitName();
    }
  }

  // Auto-dismiss done phase after 3 seconds
  $effect(() => {
    if (phase === 'done') {
      const timer = setTimeout(() => {
        onComplete?.();
      }, 3000);
      return () => clearTimeout(timer);
    }
  });
</script>

{#if phase !== 'hidden'}
  <div class="wizard-overlay" data-no-drag>
    <div class="wizard-content">
      {#if phase === 'welcome'}
        <div class="wizard-center fade-in">
          {#if brainFramePaths.length > 0}
            <img
              class="welcome-brain"
              src={brainFramePaths[0]}
              alt=""
              draggable="false"
            />
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
            <img
              class="welcome-brain"
              src={brainFramePaths[0]}
              alt=""
              draggable="false"
            />
          {/if}
          <h2 class="wizard-title">
            {createdAgentName ? `Meet ${createdAgentName}.` : 'Ready.'}
          </h2>
          <p class="wizard-subtitle">Starting up...</p>
        </div>
      {/if}
    </div>

    <!-- Name input pinned to bottom, styled like InputBar -->
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
            <button
              class="name-submit-btn poof-in"
              onclick={submitName}
              aria-label="Continue"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
              </svg>
            </button>
          {/if}
        </div>
      </div>
    {/if}
  </div>
{/if}

<style>
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
    position: relative;
    z-index: 2;
    width: 100%;
    max-width: 460px;
    padding: var(--pad);
    pointer-events: none;
  }

  .wizard-content > * {
    pointer-events: auto;
  }

  .wizard-center {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .fade-in {
    animation: fadeIn 0.5s ease forwards;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ---- Welcome ---- */

  .welcome-brain {
    width: 80px;
    height: 80px;
    object-fit: contain;
    user-select: none;
    -webkit-user-drag: none;
    margin-bottom: 20px;
    filter: brightness(0.9) contrast(1.05);
  }

  .wizard-title {
    font-family: 'Bricolage Grotesque', var(--font-sans);
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 8px;
  }

  .wizard-tagline {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.4);
    margin-bottom: 40px;
  }

  .wizard-subtitle {
    font-size: 15px;
    color: var(--text-secondary);
    margin-bottom: 16px;
  }

  /* Name input bar pinned to bottom */
  .name-bar-container {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 12px var(--pad, 20px) var(--pad, 20px);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }

  .name-prompt {
    font-size: 14px;
    color: var(--text-secondary, rgba(255, 255, 255, 0.5));
    font-family: var(--font-sans, -apple-system, system-ui, sans-serif);
  }

  .name-bar {
    position: relative;
    width: 100%;
    height: var(--bar-height, 48px);
    background: var(--bg-input, rgba(255, 255, 255, 0.04));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    border-radius: var(--bar-radius, 14px);
    display: flex;
    align-items: center;
    transition: border-color 0.2s;
  }

  .name-bar:focus-within {
    border-color: var(--border-hover, rgba(255, 255, 255, 0.2));
  }

  .name-input {
    flex: 1;
    height: 100%;
    background: transparent;
    border: none;
    outline: none;
    color: rgba(255, 255, 255, 0.9);
    font-family: var(--font-sans, -apple-system, system-ui, sans-serif);
    font-size: 14px;
    padding: 0 20px;
    text-align: center;
  }

  .name-input::placeholder {
    color: var(--text-dim, rgba(255, 255, 255, 0.3));
  }

  .name-submit-btn {
    position: absolute;
    right: 6px;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: rgba(255, 255, 255, 0.16);
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s;
  }

  .name-submit-btn:hover {
    background: rgba(255, 255, 255, 0.24);
    color: rgba(255, 255, 255, 0.9);
  }

  .poof-in {
    animation: poof 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
  }

  @keyframes poof {
    from { opacity: 0; transform: scale(0); }
    to { opacity: 1; transform: scale(1); }
  }

  /* ---- Creating ---- */

  .creating-spinner {
    width: 48px;
    height: 48px;
    border: 2px solid rgba(100, 140, 255, 0.15);
    border-top-color: rgba(100, 140, 255, 0.6);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 24px;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>

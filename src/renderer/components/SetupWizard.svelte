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

          <div class="welcome-name-section">
            <p class="wizard-subtitle">What is your name, human?</p>
            <input
              type="text"
              bind:value={userName}
              onkeydown={onKeydown}
              class="wizard-input"
              placeholder="Your name"
              autofocus
            />
            <button
              class="wizard-btn"
              disabled={!userName.trim()}
              onclick={submitName}
            >Continue</button>
          </div>
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
    background: transparent;
    overflow: hidden;
  }

  .wizard-content {
    position: relative;
    z-index: 2;
    width: 100%;
    max-width: 460px;
    padding: var(--pad);
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

  .welcome-name-section {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .wizard-subtitle {
    font-size: 15px;
    color: var(--text-secondary);
    margin-bottom: 16px;
  }

  .wizard-input {
    width: 100%;
    max-width: 320px;
    height: 44px;
    padding: 0 16px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 15px;
    outline: none;
    text-align: center;
    margin-bottom: 16px;
  }

  .wizard-input:focus {
    border-color: var(--border-hover);
  }

  .wizard-btn {
    padding: 10px 28px;
    border: 1px solid rgba(100, 140, 255, 0.3);
    border-radius: 10px;
    background: rgba(100, 140, 255, 0.1);
    color: rgba(255, 255, 255, 0.85);
    font-family: var(--font-sans);
    font-size: 14px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .wizard-btn:hover:not(:disabled) {
    background: rgba(100, 140, 255, 0.2);
  }

  .wizard-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
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

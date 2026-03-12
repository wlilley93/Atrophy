<script lang="ts">
  /**
   * First-launch wizard: name -> AI-driven agent creation -> service setup.
   * Port of display/setup_wizard.py.
   */

  type Phase = 'welcome' | 'create' | 'services' | 'done';

  let phase = $state<Phase>('welcome');
  let userName = $state('');
  let conversationLog = $state<{ role: string; text: string }[]>([]);
  let currentInput = $state('');
  let isInferring = $state(false);

  // Service keys
  let elevenLabsKey = $state('');
  let telegramToken = $state('');
  let telegramChatId = $state('');

  // Allowed secure keys
  const SECURE_KEYS = [
    'ELEVENLABS_API_KEY',
    'FAL_KEY',
    'TELEGRAM_BOT_TOKEN',
    'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY',
  ];

  function nextPhase() {
    if (phase === 'welcome' && userName.trim()) {
      phase = 'create';
      conversationLog.push({
        role: 'agent',
        text: `You are ${userName}. Good. Now - who do you want to create? Tell me about the companion you want.`,
      });
    } else if (phase === 'create') {
      phase = 'services';
    } else if (phase === 'services') {
      phase = 'done';
      finishSetup();
    }
  }

  async function sendMessage() {
    const text = currentInput.trim();
    if (!text || isInferring) return;
    currentInput = '';

    conversationLog.push({ role: 'user', text });
    isInferring = true;

    const api = (window as any).atrophy;
    if (api) {
      try {
        const response = await api.wizardInference(text);
        conversationLog.push({ role: 'agent', text: response });
      } catch {
        conversationLog.push({ role: 'agent', text: 'Something went wrong. Try again.' });
      }
    }
    isInferring = false;
  }

  async function finishSetup() {
    const api = (window as any).atrophy;
    if (api) {
      await api.updateConfig({
        USER_NAME: userName,
        setup_complete: true,
      });
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (phase === 'welcome') nextPhase();
      else if (phase === 'create') sendMessage();
      else if (phase === 'services') nextPhase();
    }
  }
</script>

<div class="wizard-overlay" data-no-drag>
  <div class="wizard-content">
    {#if phase === 'welcome'}
      <div class="wizard-center">
        <div class="wizard-orb"></div>
        <h1 class="wizard-title">Hello.</h1>
        <p class="wizard-subtitle">What's your name?</p>
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
          onclick={nextPhase}
        >Continue</button>
      </div>

    {:else if phase === 'create'}
      <div class="wizard-chat">
        <div class="chat-messages">
          {#each conversationLog as msg}
            <div class="chat-msg {msg.role}">
              <p>{msg.text}</p>
            </div>
          {/each}
          {#if isInferring}
            <div class="chat-msg agent">
              <p class="thinking-dots">...</p>
            </div>
          {/if}
        </div>
        <div class="chat-input-bar">
          <input
            type="text"
            bind:value={currentInput}
            onkeydown={onKeydown}
            class="chat-input"
            placeholder="Describe who you want to create..."
            disabled={isInferring}
          />
        </div>
        <button class="wizard-btn skip-btn" onclick={nextPhase}>
          Skip to services
        </button>
      </div>

    {:else if phase === 'services'}
      <div class="wizard-center">
        <h2 class="wizard-title">Services</h2>
        <p class="wizard-subtitle">Optional. You can set these up later in Settings.</p>

        <div class="service-fields">
          <label class="service-field">
            <span>ElevenLabs API Key</span>
            <input type="password" bind:value={elevenLabsKey} class="wizard-input" placeholder="sk-..." />
          </label>
          <label class="service-field">
            <span>Telegram Bot Token</span>
            <input type="password" bind:value={telegramToken} class="wizard-input" placeholder="123456:ABC..." />
          </label>
          <label class="service-field">
            <span>Telegram Chat ID</span>
            <input type="text" bind:value={telegramChatId} class="wizard-input" placeholder="12345678" />
          </label>
        </div>

        <button class="wizard-btn" onclick={nextPhase}>
          {elevenLabsKey || telegramToken ? 'Save & Finish' : 'Skip & Finish'}
        </button>
      </div>

    {:else if phase === 'done'}
      <div class="wizard-center">
        <div class="wizard-orb done"></div>
        <h2 class="wizard-title">Ready.</h2>
        <p class="wizard-subtitle">Close this to start.</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .wizard-overlay {
    position: absolute;
    inset: 0;
    z-index: 70;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg);
  }

  .wizard-content {
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

  .wizard-orb {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 35%,
      rgba(100, 160, 255, 0.4),
      rgba(60, 100, 200, 0.15) 60%,
      transparent
    );
    box-shadow: 0 0 40px rgba(100, 140, 255, 0.15);
    margin-bottom: 32px;
    animation: pulse-orb 3s ease-in-out infinite;
  }

  .wizard-orb.done {
    background: radial-gradient(circle at 35% 35%,
      rgba(120, 200, 120, 0.4),
      rgba(60, 160, 80, 0.15) 60%,
      transparent
    );
    box-shadow: 0 0 40px rgba(120, 200, 120, 0.15);
  }

  @keyframes pulse-orb {
    0%, 100% { transform: scale(1); opacity: 0.8; }
    50% { transform: scale(1.08); opacity: 1; }
  }

  .wizard-title {
    font-family: var(--font-sans);
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 8px;
  }

  .wizard-subtitle {
    font-size: 14px;
    color: var(--text-secondary);
    margin-bottom: 28px;
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

  /* Chat phase */
  .wizard-chat {
    display: flex;
    flex-direction: column;
    height: 100%;
    max-height: 600px;
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px 0;
  }

  .chat-msg {
    margin-bottom: 16px;
  }

  .chat-msg.agent p {
    color: var(--text-companion);
  }

  .chat-msg.user p {
    color: var(--text-user);
  }

  .thinking-dots {
    animation: blink 1.2s infinite;
  }

  @keyframes blink {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 1; }
  }

  .chat-input-bar {
    padding: 12px 0;
  }

  .chat-input {
    width: 100%;
    height: 44px;
    padding: 0 16px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 22px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 14px;
    outline: none;
  }

  .chat-input:focus {
    border-color: var(--border-hover);
  }

  .skip-btn {
    margin-top: 8px;
    background: transparent;
    border-color: var(--border);
    color: var(--text-dim);
    font-size: 12px;
    align-self: center;
  }

  /* Services */
  .service-fields {
    width: 100%;
    max-width: 360px;
    margin-bottom: 24px;
  }

  .service-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 16px;
    text-align: left;
  }

  .service-field span {
    font-size: 12px;
    color: var(--text-secondary);
    padding-left: 4px;
  }
</style>

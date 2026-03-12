<script lang="ts">
  /**
   * First-launch wizard: brain intro -> name -> AI-driven agent creation -> service cards -> done.
   * Port of display/setup_wizard.py.
   */
  import { onMount, onDestroy } from 'svelte';

  type Phase = 'intro' | 'welcome' | 'create' | 'elevenlabs' | 'telegram' | 'done';

  let phase = $state<Phase>('intro');
  let userName = $state('');
  let conversationLog = $state<{ role: string; text: string }[]>([]);
  let currentInput = $state('');
  let isInferring = $state(false);

  // Service keys
  let elevenLabsKey = $state('');
  let telegramToken = $state('');
  let telegramChatId = $state('');

  // Service verification state
  let elevenLabsVerifying = $state(false);
  let elevenLabsVerified = $state<boolean | null>(null);
  let telegramVerifying = $state(false);
  let telegramVerified = $state<boolean | null>(null);

  // Brain frame animation
  let brainFrame = $state(0);
  let brainInterval: ReturnType<typeof setInterval> | null = null;
  const BRAIN_FRAME_COUNT = 10;

  // Build frame paths using Vite static imports
  const brainFramePaths: string[] = [];
  const frameModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: true, query: '?url', import: 'default' }
  );
  // Sort by filename to ensure correct order
  const sortedKeys = Object.keys(frameModules).sort();
  for (const key of sortedKeys) {
    brainFramePaths.push(frameModules[key] as string);
  }

  // Allowed secure keys
  const SECURE_KEYS = [
    'ELEVENLABS_API_KEY',
    'FAL_KEY',
    'TELEGRAM_BOT_TOKEN',
    'OPENAI_API_KEY',
    'ANTHROPIC_API_KEY',
  ];

  // ---------------------------------------------------------------------------
  // Brain intro animation
  // ---------------------------------------------------------------------------

  function startBrainAnimation() {
    brainFrame = 0;
    brainInterval = setInterval(() => {
      brainFrame = (brainFrame + 1) % BRAIN_FRAME_COUNT;
    }, 180);

    // Auto-advance after the animation plays through a couple of times
    setTimeout(() => {
      phase = 'welcome';
    }, 3200);
  }

  function stopBrainAnimation() {
    if (brainInterval) {
      clearInterval(brainInterval);
      brainInterval = null;
    }
  }

  onMount(() => {
    if (phase === 'intro') {
      startBrainAnimation();
    }
  });

  onDestroy(() => {
    stopBrainAnimation();
  });

  // ---------------------------------------------------------------------------
  // Phase transitions
  // ---------------------------------------------------------------------------

  function nextPhase() {
    if (phase === 'welcome' && userName.trim()) {
      phase = 'create';
      conversationLog.push({
        role: 'agent',
        text: `You are ${userName}. Good. Now - who do you want to create? Tell me about the companion you want.`,
      });
    } else if (phase === 'create') {
      phase = 'elevenlabs';
    } else if (phase === 'elevenlabs') {
      phase = 'telegram';
    } else if (phase === 'telegram') {
      phase = 'done';
      finishSetup();
    }
  }

  function skipToNext() {
    if (phase === 'elevenlabs') {
      phase = 'telegram';
    } else if (phase === 'telegram') {
      phase = 'done';
      finishSetup();
    }
  }

  // ---------------------------------------------------------------------------
  // Wizard conversation (agent creation phase)
  // ---------------------------------------------------------------------------

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

  // ---------------------------------------------------------------------------
  // Service verification
  // ---------------------------------------------------------------------------

  async function verifyElevenLabs() {
    if (!elevenLabsKey.trim()) return;
    elevenLabsVerifying = true;
    elevenLabsVerified = null;

    try {
      // Test the key by hitting the ElevenLabs user endpoint
      const res = await fetch('https://api.elevenlabs.io/v1/user', {
        headers: { 'xi-api-key': elevenLabsKey.trim() },
      });
      elevenLabsVerified = res.ok;
    } catch {
      elevenLabsVerified = false;
    }
    elevenLabsVerifying = false;
  }

  async function verifyTelegram() {
    if (!telegramToken.trim()) return;
    telegramVerifying = true;
    telegramVerified = null;

    try {
      const res = await fetch(`https://api.telegram.org/bot${telegramToken.trim()}/getMe`);
      const data = await res.json();
      telegramVerified = data.ok === true;
    } catch {
      telegramVerified = false;
    }
    telegramVerifying = false;
  }

  // ---------------------------------------------------------------------------
  // Finish
  // ---------------------------------------------------------------------------

  let { onComplete }: { onComplete?: () => void } = $props();

  async function finishSetup() {
    const api = (window as any).atrophy;
    if (api) {
      const updates: Record<string, unknown> = {
        USER_NAME: userName,
        setup_complete: true,
      };
      if (elevenLabsKey.trim()) updates.ELEVENLABS_API_KEY = elevenLabsKey.trim();
      if (telegramToken.trim()) updates.TELEGRAM_BOT_TOKEN = telegramToken.trim();
      if (telegramChatId.trim()) updates.TELEGRAM_CHAT_ID = telegramChatId.trim();
      await api.updateConfig(updates);
    }

    // Auto-dismiss after a moment
    setTimeout(() => {
      onComplete?.();
    }, 2000);
  }

  // ---------------------------------------------------------------------------
  // Keyboard
  // ---------------------------------------------------------------------------

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (phase === 'welcome') nextPhase();
      else if (phase === 'create') sendMessage();
      else if (phase === 'elevenlabs' || phase === 'telegram') nextPhase();
    }
  }
</script>

<div class="wizard-overlay" data-no-drag>
  <div class="wizard-content">
    {#if phase === 'intro'}
      <!-- Brain frame animation intro -->
      <div class="wizard-center brain-intro">
        {#if brainFramePaths.length > 0}
          <img
            class="brain-frame"
            src={brainFramePaths[brainFrame]}
            alt="Brain animation"
            draggable="false"
          />
        {:else}
          <div class="wizard-orb"></div>
        {/if}
      </div>

    {:else if phase === 'welcome'}
      <div class="wizard-center fade-in">
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
      <div class="wizard-chat fade-in">
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

    {:else if phase === 'elevenlabs'}
      <!-- ElevenLabs service card -->
      <div class="wizard-center fade-in">
        <div class="service-card">
          <div class="service-card-header">
            <h2 class="service-card-title">Voice - ElevenLabs</h2>
            <p class="service-card-desc">
              Paste your API key to enable natural voice synthesis.
              Get one at <span class="service-link">elevenlabs.io</span>
            </p>
          </div>

          <div class="service-card-body">
            <label class="service-field">
              <span>API Key</span>
              <input
                type="password"
                bind:value={elevenLabsKey}
                onkeydown={onKeydown}
                class="wizard-input secure-input"
                placeholder="xi-..."
                autofocus
              />
            </label>

            {#if elevenLabsVerified === true}
              <span class="verify-status verified">Verified</span>
            {:else if elevenLabsVerified === false}
              <span class="verify-status failed">Invalid key</span>
            {/if}
          </div>

          <div class="service-card-actions">
            <button
              class="wizard-btn verify-btn"
              disabled={!elevenLabsKey.trim() || elevenLabsVerifying}
              onclick={verifyElevenLabs}
            >
              {elevenLabsVerifying ? 'Checking...' : 'Verify'}
            </button>
            <button class="wizard-btn" onclick={nextPhase}>
              {elevenLabsKey.trim() ? 'Next' : 'Skip'}
            </button>
          </div>
        </div>
      </div>

    {:else if phase === 'telegram'}
      <!-- Telegram service card -->
      <div class="wizard-center fade-in">
        <div class="service-card">
          <div class="service-card-header">
            <h2 class="service-card-title">Messaging - Telegram</h2>
            <p class="service-card-desc">
              Connect a Telegram bot for mobile messaging.
              Talk to <span class="service-link">@BotFather</span> to create one.
            </p>
          </div>

          <div class="service-card-body">
            <label class="service-field">
              <span>Bot Token</span>
              <input
                type="password"
                bind:value={telegramToken}
                onkeydown={onKeydown}
                class="wizard-input secure-input"
                placeholder="123456:ABC-DEF..."
                autofocus
              />
            </label>

            <label class="service-field">
              <span>Chat ID</span>
              <input
                type="text"
                bind:value={telegramChatId}
                onkeydown={onKeydown}
                class="wizard-input"
                placeholder="12345678"
              />
            </label>

            {#if telegramVerified === true}
              <span class="verify-status verified">Bot verified</span>
            {:else if telegramVerified === false}
              <span class="verify-status failed">Invalid token</span>
            {/if}
          </div>

          <div class="service-card-actions">
            <button
              class="wizard-btn verify-btn"
              disabled={!telegramToken.trim() || telegramVerifying}
              onclick={verifyTelegram}
            >
              {telegramVerifying ? 'Checking...' : 'Verify'}
            </button>
            <button class="wizard-btn" onclick={nextPhase}>
              {telegramToken.trim() ? 'Finish' : 'Skip & Finish'}
            </button>
          </div>
        </div>
      </div>

    {:else if phase === 'done'}
      <div class="wizard-center fade-in">
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

  .fade-in {
    animation: fadeIn 0.5s ease forwards;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  /* ---- Brain intro animation ---- */

  .brain-intro {
    justify-content: center;
    min-height: 300px;
  }

  .brain-frame {
    width: 200px;
    height: 200px;
    object-fit: contain;
    image-rendering: auto;
    filter: brightness(0.9) contrast(1.05);
    animation: brainPulse 2.4s ease-in-out infinite;
  }

  @keyframes brainPulse {
    0%, 100% { opacity: 0.85; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.03); }
  }

  /* ---- Orb ---- */

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

  /* ---- Typography ---- */

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

  /* ---- Inputs ---- */

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

  .secure-input {
    border-color: rgba(220, 140, 40, 0.45);
    text-align: left;
    font-family: var(--font-mono);
    font-size: 13px;
    letter-spacing: 0.5px;
  }

  .secure-input:focus {
    border-color: rgba(220, 160, 60, 0.7);
    box-shadow: 0 0 0 2px rgba(220, 140, 40, 0.12);
  }

  /* ---- Buttons ---- */

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

  .verify-btn {
    background: rgba(220, 140, 40, 0.12);
    border-color: rgba(220, 140, 40, 0.35);
  }

  .verify-btn:hover:not(:disabled) {
    background: rgba(220, 140, 40, 0.22);
  }

  /* ---- Service cards ---- */

  .service-card {
    width: 100%;
    max-width: 380px;
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 28px 24px;
    background: rgba(255, 255, 255, 0.02);
  }

  .service-card-header {
    margin-bottom: 20px;
  }

  .service-card-title {
    font-family: var(--font-sans);
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 6px;
  }

  .service-card-desc {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.4;
  }

  .service-link {
    color: rgba(100, 160, 255, 0.8);
  }

  .service-card-body {
    margin-bottom: 20px;
  }

  .service-card-body .service-field {
    margin-bottom: 12px;
  }

  .service-card-body .wizard-input {
    max-width: 100%;
    text-align: left;
  }

  .service-card-actions {
    display: flex;
    gap: 10px;
    justify-content: center;
  }

  .verify-status {
    display: inline-block;
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 6px;
    margin-bottom: 4px;
  }

  .verify-status.verified {
    color: rgba(120, 220, 140, 0.9);
    background: rgba(60, 160, 80, 0.15);
  }

  .verify-status.failed {
    color: rgba(255, 120, 100, 0.9);
    background: rgba(200, 60, 40, 0.15);
  }

  /* ---- Chat phase ---- */

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

  /* ---- Service fields (shared) ---- */

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

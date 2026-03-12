<script lang="ts">
  /**
   * First-launch wizard: welcome -> services (in chat) -> AI agent creation -> done.
   * Port of display/setup_wizard.py.
   *
   * The SplashScreen handles the cinematic intro (brain decay + voiceover).
   * This wizard starts at the welcome/name page.
   *
   * Flow: welcome -> chat (opening text + deterministic service cards + AI creation) -> creating -> done
   */
  type Phase = 'welcome' | 'chat' | 'creating' | 'done';

  let phase = $state<Phase>('welcome');
  let userName = $state('');
  let conversationLog = $state<{ role: string; text: string }[]>([]);
  let currentInput = $state('');
  let isInferring = $state(false);

  // Service keys (collected in chat phase via deterministic cards)
  let elevenLabsKey = $state('');
  let falKey = $state('');
  let telegramToken = $state('');
  let telegramChatId = $state('');

  // Service verification state
  let elevenLabsVerifying = $state(false);
  let elevenLabsVerified = $state<boolean | null>(null);
  let falVerifying = $state(false);
  let falVerified = $state<boolean | null>(null);
  let telegramVerifying = $state(false);
  let telegramVerified = $state<boolean | null>(null);

  // Google OAuth state
  let googleWorkspace = $state(true);
  let googleExtra = $state(true);
  let googleAuthing = $state(false);
  let googleResult = $state<string | null>(null);

  // Track which services were configured (injected into AI context)
  let servicesSaved = $state<string[]>([]);
  let servicesSkipped = $state<string[]>([]);

  // Deterministic service setup step (0-3: elevenlabs, fal, telegram, google)
  let serviceStep = $state(-1); // -1 = not started, 0-3 = showing card, 4 = done
  let showServiceCard = $state(false);

  // Agent creation result
  let createdAgentName = $state('');

  // Video background
  let videoPath = $state<string | null>(null);

  // Brain frame for welcome page
  const brainFramePaths: string[] = [];
  const frameModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: true, query: '?url', import: 'default' }
  );
  const sortedKeys = Object.keys(frameModules).sort();
  for (const key of sortedKeys) {
    brainFramePaths.push(frameModules[key] as string);
  }

  const api = (window as any).atrophy;

  /** Escape HTML entities then convert newlines to <br> tags. */
  function safeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/\n/g, '<br>');
  }

  // Pre-baked opening text (matches Python _OPENING_TEXT)
  const OPENING_TEXT =
    "I'm Xan. I ship with the system - protector, first contact, always on.\n\n" +
    "You already have me. But the real power is in creating something yours - " +
    "a companion with its own edges, its own voice, someone shaped by you " +
    "for a specific purpose.\n\n" +
    "This is the last you'll hear of my voice until you've added your " +
    "ElevenLabs API key, which I will ask you to do in a moment.\n\n" +
    "First, we need to set up your system. Let's get started.";

  // Service definitions (deterministic flow)
  const SERVICE_PROMPTS = [
    {
      key: 'ELEVENLABS_API_KEY',
      title: 'Voice - ElevenLabs',
      description: "Gives your companion a real voice - speaks out loud.\n$5/month minimum. Hundreds of voices, or clone your own.",
      label: 'ElevenLabs API Key',
      placeholder: 'xi-...',
    },
    {
      key: 'FAL_KEY',
      title: 'Visual Presence - Fal.ai',
      description: "Handles image and video generation. Pay-as-you-go:\navatar images ~$0.01 each, ambient video clips ~$0.30 each.",
      label: 'Fal API Key',
      placeholder: 'fal-...',
    },
    {
      key: 'TELEGRAM',
      title: 'Messaging - Telegram',
      description: "Your companion can message you directly - check-ins,\nbriefs, reminders. Free.",
      label: '',
      placeholder: '',
    },
    {
      key: 'GOOGLE',
      title: 'Google Workspace + YouTube + Photos',
      description: "Gmail, Calendar, Drive, Sheets, Docs, Tasks, Contacts,\nMeet, YouTube, Photos, and Search Console.\nFree - opens your browser for Google consent.",
      label: '',
      placeholder: '',
    },
  ];

  let chatMessagesEl: HTMLDivElement;

  // ---------------------------------------------------------------------------
  // Phase transitions
  // ---------------------------------------------------------------------------

  async function startChat() {
    if (!userName.trim()) return;

    // Save name
    if (api) await api.updateConfig({ USER_NAME: userName.trim() });

    phase = 'chat';

    // Play name.mp3 transition audio
    api?.playAgentAudio?.('name.mp3');

    // Load video background
    loadVideoBackground();

    // After a brief pause, show opening text + play opening.mp3
    setTimeout(() => {
      api?.playAgentAudio?.('opening.mp3');
      conversationLog.push({ role: 'agent', text: OPENING_TEXT });
      scrollToBottom();

      // Start deterministic service setup after opening finishes
      setTimeout(() => {
        serviceStep = 0;
        showServiceCard = true;
        scrollToBottom();
      }, 2000);
    }, 500);
  }

  async function loadVideoBackground() {
    if (!api) return;
    const vp = await api.getAvatarVideoPath?.('blue', 'bounce_playful');
    if (vp) videoPath = vp;
  }

  // ---------------------------------------------------------------------------
  // Service card actions
  // ---------------------------------------------------------------------------

  async function saveCurrentService() {
    const svc = SERVICE_PROMPTS[serviceStep];
    if (!svc) return;

    if (svc.key === 'ELEVENLABS_API_KEY' && elevenLabsKey.trim()) {
      await api?.saveSecret('ELEVENLABS_API_KEY', elevenLabsKey.trim());
      servicesSaved.push('ELEVENLABS_API_KEY');
      conversationLog.push({ role: 'system', text: '(SECURE_INPUT: ELEVENLABS_API_KEY saved)' });
      api?.playAgentAudio?.('elevenlabs_saved.mp3');
    } else if (svc.key === 'FAL_KEY' && falKey.trim()) {
      await api?.saveSecret('FAL_KEY', falKey.trim());
      servicesSaved.push('FAL_KEY');
      conversationLog.push({ role: 'system', text: '(SECURE_INPUT: FAL_KEY saved)' });
    } else if (svc.key === 'TELEGRAM' && telegramToken.trim()) {
      await api?.saveSecret('TELEGRAM_BOT_TOKEN', telegramToken.trim());
      if (telegramChatId.trim()) {
        await api?.updateConfig({ TELEGRAM_CHAT_ID: telegramChatId.trim() });
      }
      servicesSaved.push('TELEGRAM_BOT_TOKEN');
      conversationLog.push({ role: 'system', text: '(SERVICE: TELEGRAM saved)' });
    } else if (svc.key === 'GOOGLE' && googleResult === 'complete') {
      servicesSaved.push('GOOGLE');
      conversationLog.push({ role: 'system', text: '(SERVICE: GOOGLE saved)' });
    }

    advanceService();
  }

  function skipCurrentService() {
    const svc = SERVICE_PROMPTS[serviceStep];
    if (svc) {
      servicesSkipped.push(svc.key);
      conversationLog.push({ role: 'system', text: `(SERVICE: ${svc.key} skipped)` });
    }
    advanceService();
  }

  function advanceService() {
    serviceStep++;
    showServiceCard = serviceStep < SERVICE_PROMPTS.length;

    if (serviceStep >= SERVICE_PROMPTS.length) {
      // All services done - transition to AI agent creation
      api?.playAgentAudio?.('service_complete.mp3');
      conversationLog.push({
        role: 'agent',
        text: 'System configured. Now - who do you want to create?',
      });

      // Seed conversation history with service context
      const ctx: string[] = [];
      for (const key of servicesSaved) ctx.push(`(SERVICE: ${key} saved)`);
      for (const key of servicesSkipped) ctx.push(`(SERVICE: ${key} skipped)`);
      conversationLog.push({ role: 'system', text: ctx.join(' ') });

      scrollToBottom();
    } else {
      scrollToBottom();
    }
  }

  // ---------------------------------------------------------------------------
  // Service verification
  // ---------------------------------------------------------------------------

  async function verifyElevenLabs() {
    if (!elevenLabsKey.trim()) return;
    elevenLabsVerifying = true;
    elevenLabsVerified = null;
    try {
      const res = await fetch('https://api.elevenlabs.io/v1/user', {
        headers: { 'xi-api-key': elevenLabsKey.trim() },
      });
      elevenLabsVerified = res.ok;
    } catch {
      elevenLabsVerified = false;
    }
    elevenLabsVerifying = false;
  }

  async function verifyFal() {
    if (!falKey.trim()) return;
    falVerifying = true;
    falVerified = null;
    try {
      const res = await fetch('https://queue.fal.run/fal-ai/fast-sdxl', {
        method: 'POST',
        headers: {
          'Authorization': `Key ${falKey.trim()}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt: 'test', image_size: 'square_hd' }),
      });
      falVerified = res.status < 400;
    } catch {
      falVerified = false;
    }
    falVerifying = false;
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

  async function startGoogleAuth() {
    if (!api) return;
    googleAuthing = true;
    googleResult = null;
    try {
      const result = await api.startGoogleOAuth(googleWorkspace, googleExtra);
      googleResult = result;
    } catch {
      googleResult = 'failed';
    }
    googleAuthing = false;
  }

  // ---------------------------------------------------------------------------
  // AI conversation (agent creation phase)
  // ---------------------------------------------------------------------------

  async function sendMessage() {
    const text = currentInput.trim();
    if (!text || isInferring || showServiceCard) return;
    currentInput = '';

    conversationLog.push({ role: 'user', text });
    isInferring = true;
    scrollToBottom();

    if (api) {
      try {
        const response = await api.wizardInference(text);
        conversationLog.push({ role: 'agent', text: response });

        // Check if the response contains AGENT_CONFIG JSON
        const configMatch = response.match(/```json\s*(\{[\s\S]*?"AGENT_CONFIG"[\s\S]*?\})\s*```/);
        if (configMatch) {
          try {
            const parsed = JSON.parse(configMatch[1]);
            const agentConfig = parsed.AGENT_CONFIG;
            if (agentConfig && agentConfig.display_name) {
              // Play farewell BEFORE switching agent (so it uses Xan's audio dir)
              api?.playAgentAudio?.('voice_farewell.mp3');

              // Transition to creating phase
              phase = 'creating';
              createdAgentName = agentConfig.display_name;

              const manifest = await api.createAgent(agentConfig);
              if (manifest && manifest.name) {
                await api.switchAgent(manifest.name);
              }

              // Brief pause on creating screen, then done
              setTimeout(() => {
                phase = 'done';
                finishSetup();
              }, 2500);
            }
          } catch {
            // JSON parse failed - continue conversation
          }
        }
      } catch {
        conversationLog.push({ role: 'agent', text: 'Something went wrong. Try again.' });
      }
    }
    isInferring = false;
    scrollToBottom();
  }

  function skipAgentCreation() {
    phase = 'done';
    finishSetup();
  }

  // ---------------------------------------------------------------------------
  // Finish
  // ---------------------------------------------------------------------------

  let { onComplete }: { onComplete?: () => void } = $props();

  async function finishSetup() {
    if (api) {
      const updates: Record<string, unknown> = {
        USER_NAME: userName,
        setup_complete: true,
      };
      if (telegramChatId.trim()) updates.TELEGRAM_CHAT_ID = telegramChatId.trim();
      await api.updateConfig(updates);
    }

    setTimeout(() => {
      onComplete?.();
    }, 3000);
  }

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  function scrollToBottom() {
    setTimeout(() => {
      if (chatMessagesEl) {
        chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
      }
    }, 50);
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (phase === 'welcome') startChat();
      else if (phase === 'chat' && !showServiceCard) sendMessage();
    }
  }


</script>

<div class="wizard-overlay" data-no-drag>
  <!-- Video background (chat phase) -->
  {#if phase === 'chat' && videoPath}
    <video
      class="wizard-video-bg"
      src="file://{videoPath}"
      autoplay
      loop
      muted
      playsinline
    ></video>
    <div class="wizard-video-scrim"></div>
  {/if}

  <div class="wizard-content" class:chat-mode={phase === 'chat'}>
    {#if phase === 'welcome'}
      <div class="wizard-center fade-in">
        <!-- Brain icon (frame 0 - pristine) -->
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
            onclick={startChat}
          >Continue</button>
        </div>
      </div>

    {:else if phase === 'chat'}
      <div class="wizard-chat fade-in">
        <div class="chat-messages" bind:this={chatMessagesEl}>
          {#each conversationLog as msg}
            {#if msg.role !== 'system'}
              <div class="chat-msg {msg.role}">
                <p>{@html safeHtml(msg.text)}</p>
              </div>
            {/if}
          {/each}
          {#if isInferring}
            <div class="chat-msg agent">
              <p class="thinking-dots">...</p>
            </div>
          {/if}

          <!-- Deterministic service card (inline in chat) -->
          {#if showServiceCard && serviceStep >= 0 && serviceStep < SERVICE_PROMPTS.length}
            {@const svc = SERVICE_PROMPTS[serviceStep]}
            <div class="service-card-inline fade-in">
              <div class="service-card-header">
                <h3 class="service-card-title">{svc.title}</h3>
                <p class="service-card-desc">{@html safeHtml(svc.description)}</p>
              </div>

              <div class="service-card-body">
                {#if svc.key === 'ELEVENLABS_API_KEY'}
                  <label class="service-field">
                    <span>{svc.label}</span>
                    <input
                      type="password"
                      bind:value={elevenLabsKey}
                      class="wizard-input secure-input"
                      placeholder={svc.placeholder}
                      autofocus
                    />
                  </label>
                  {#if elevenLabsVerified === true}
                    <span class="verify-status verified">Verified</span>
                  {:else if elevenLabsVerified === false}
                    <span class="verify-status failed">Invalid key</span>
                  {/if}
                  <div class="service-card-actions">
                    <button class="wizard-btn verify-btn" disabled={!elevenLabsKey.trim() || elevenLabsVerifying} onclick={verifyElevenLabs}>
                      {elevenLabsVerifying ? 'Checking...' : 'Verify'}
                    </button>
                    <button class="wizard-btn" onclick={elevenLabsKey.trim() ? saveCurrentService : skipCurrentService}>
                      {elevenLabsKey.trim() ? 'Save' : 'Skip'}
                    </button>
                  </div>

                {:else if svc.key === 'FAL_KEY'}
                  <label class="service-field">
                    <span>{svc.label}</span>
                    <input
                      type="password"
                      bind:value={falKey}
                      class="wizard-input secure-input"
                      placeholder={svc.placeholder}
                      autofocus
                    />
                  </label>
                  {#if falVerified === true}
                    <span class="verify-status verified">Verified</span>
                  {:else if falVerified === false}
                    <span class="verify-status failed">Invalid key</span>
                  {/if}
                  <div class="service-card-actions">
                    <button class="wizard-btn verify-btn" disabled={!falKey.trim() || falVerifying} onclick={verifyFal}>
                      {falVerifying ? 'Checking...' : 'Verify'}
                    </button>
                    <button class="wizard-btn" onclick={falKey.trim() ? saveCurrentService : skipCurrentService}>
                      {falKey.trim() ? 'Save' : 'Skip'}
                    </button>
                  </div>

                {:else if svc.key === 'TELEGRAM'}
                  <label class="service-field">
                    <span>Bot Token</span>
                    <input
                      type="password"
                      bind:value={telegramToken}
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
                      class="wizard-input"
                      placeholder="12345678"
                    />
                  </label>
                  {#if telegramVerified === true}
                    <span class="verify-status verified">Bot verified</span>
                  {:else if telegramVerified === false}
                    <span class="verify-status failed">Invalid token</span>
                  {/if}
                  <div class="service-card-actions">
                    <button class="wizard-btn verify-btn" disabled={!telegramToken.trim() || telegramVerifying} onclick={verifyTelegram}>
                      {telegramVerifying ? 'Checking...' : 'Verify'}
                    </button>
                    <button class="wizard-btn" onclick={telegramToken.trim() ? saveCurrentService : skipCurrentService}>
                      {telegramToken.trim() ? 'Save' : 'Skip'}
                    </button>
                  </div>

                {:else if svc.key === 'GOOGLE'}
                  <label class="google-scope-row">
                    <input type="checkbox" bind:checked={googleWorkspace} disabled={googleAuthing} />
                    <div>
                      <span class="scope-label">Workspace</span>
                      <span class="scope-desc">Gmail, Calendar, Drive, Sheets, Docs, Tasks, Contacts, Meet</span>
                    </div>
                  </label>
                  <label class="google-scope-row">
                    <input type="checkbox" bind:checked={googleExtra} disabled={googleAuthing} />
                    <div>
                      <span class="scope-label">Extra</span>
                      <span class="scope-desc">YouTube, Photos, Search Console</span>
                    </div>
                  </label>
                  {#if googleResult === 'complete'}
                    <span class="verify-status verified">Connected</span>
                  {:else if googleResult}
                    <span class="verify-status failed">{googleResult}</span>
                  {/if}
                  <div class="service-card-actions">
                    <button class="wizard-btn verify-btn" disabled={googleAuthing || (!googleWorkspace && !googleExtra)} onclick={startGoogleAuth}>
                      {googleAuthing ? 'Waiting for browser...' : 'Connect selected'}
                    </button>
                    <button class="wizard-btn" onclick={googleResult === 'complete' ? saveCurrentService : skipCurrentService}>
                      {googleResult === 'complete' ? 'Next' : 'Skip'}
                    </button>
                  </div>
                {/if}
              </div>
            </div>
          {/if}
        </div>

        <!-- Chat input (only active when service cards are done) -->
        <div class="chat-input-bar">
          <input
            type="text"
            bind:value={currentInput}
            onkeydown={onKeydown}
            class="chat-input"
            placeholder={showServiceCard ? 'Complete the setup above...' : 'Describe who you want to create...'}
            disabled={isInferring || showServiceCard}
          />
        </div>
        <button class="wizard-btn skip-btn" onclick={skipAgentCreation}>
          Skip agent creation
        </button>
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

<style>
  .wizard-overlay {
    position: absolute;
    inset: 0;
    z-index: 70;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg);
    overflow: hidden;
  }

  /* ---- Video background ---- */

  .wizard-video-bg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    z-index: 0;
  }

  .wizard-video-scrim {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    z-index: 1;
  }

  .wizard-content {
    position: relative;
    z-index: 2;
    width: 100%;
    max-width: 460px;
    padding: var(--pad);
  }

  .wizard-content.chat-mode {
    max-width: 520px;
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 40px 20px 20px;
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

  /* ---- Welcome page ---- */

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
    max-width: 100%;
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

  /* ---- Chat phase ---- */

  .wizard-chat {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px 0;
    min-height: 0;
  }

  .chat-msg {
    margin-bottom: 16px;
    font-size: 14px;
    line-height: 1.6;
  }

  .chat-msg.agent p {
    color: var(--text-companion, rgba(255, 255, 255, 0.85));
  }

  .chat-msg.user p {
    color: var(--text-user, rgba(100, 160, 255, 0.9));
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
    flex-shrink: 0;
  }

  .chat-input {
    width: 100%;
    height: 44px;
    padding: 0 16px;
    background: var(--bg-input, rgba(255, 255, 255, 0.04));
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
    margin-top: 4px;
    background: transparent;
    border-color: var(--border);
    color: var(--text-dim);
    font-size: 12px;
    align-self: center;
    flex-shrink: 0;
  }

  /* ---- Inline service card (inside chat) ---- */

  .service-card-inline {
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    background: rgba(255, 255, 255, 0.02);
    margin-bottom: 16px;
  }

  .service-card-header {
    margin-bottom: 16px;
  }

  .service-card-title {
    font-family: var(--font-sans);
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0 0 6px;
  }

  .service-card-desc {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.4;
    margin: 0;
  }

  .service-card-body {
    margin-bottom: 0;
  }

  .service-card-actions {
    display: flex;
    gap: 10px;
    justify-content: center;
    margin-top: 12px;
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

  /* ---- Service fields ---- */

  .service-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
    text-align: left;
  }

  .service-field span {
    font-size: 12px;
    color: var(--text-secondary);
    padding-left: 4px;
  }

  /* ---- Google scope checkboxes ---- */

  .google-scope-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.02);
    margin-bottom: 8px;
    cursor: pointer;
  }

  .google-scope-row input[type="checkbox"] {
    margin-top: 3px;
    accent-color: rgba(100, 140, 255, 0.7);
  }

  .scope-label {
    display: block;
    font-size: 14px;
    color: var(--text-primary);
    font-weight: 500;
  }

  .scope-desc {
    display: block;
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 2px;
  }

  /* ---- Creating phase ---- */

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

<script lang="ts">
  /**
   * Inline service card for setup flow - renders between Transcript and InputBar.
   * Handles API key input, verification, and save/skip actions.
   */

  const SERVICE_PROMPTS = [
    {
      key: 'ELEVENLABS_API_KEY',
      title: 'Voice - ElevenLabs',
      description: "Gives your companion a real voice - speaks out loud.\n$5/month minimum. Hundreds of voices, or clone your own.",
      label: 'ElevenLabs API Key',
      placeholder: 'xi-...',
      url: 'https://elevenlabs.io/app/settings/api-keys',
      urlLabel: 'Get your API key',
      skipWarning: "Without ElevenLabs, your companion will have no voice. You can add this later in Settings.",
    },
    {
      key: 'FAL_KEY',
      title: 'Visual Presence - Fal.ai',
      description: "Handles image and video generation. Pay-as-you-go:\navatar images ~$0.01 each, ambient video clips ~$0.30 each.",
      label: 'Fal API Key',
      placeholder: 'fal-...',
      url: 'https://fal.ai/dashboard/keys',
      urlLabel: 'Get your API key',
      skipWarning: "Without Fal, you won't be able to generate pictures or videos for your avatar. Are you sure?",
    },
    {
      key: 'TELEGRAM',
      title: 'Messaging - Telegram',
      description: "Your companion can message you directly - check-ins,\nbriefs, reminders. Free.",
      label: '',
      placeholder: '',
      url: 'https://t.me/BotFather',
      urlLabel: 'Create a bot with @BotFather',
      skipWarning: "Without Telegram, you won't be able to talk to your agent remotely. If you change your mind later, you can set this up in Settings.",
    },
    {
      key: 'GOOGLE',
      title: 'Google Workspace + YouTube + Photos',
      description: "Gmail, Calendar, Drive, Sheets, Docs, Tasks, Contacts,\nMeet, YouTube, Photos, and Search Console.\nFree - opens your browser for Google consent.",
      label: '',
      placeholder: '',
      skipWarning: "No problem - we won't save anything to your Google Drive. Note that this means your agent can't tell you about your schedule or emails, if you use Google.",
    },
    {
      key: 'GITHUB',
      title: 'GitHub',
      description: "Repos, issues, PRs, code search, gists, and releases.\nFree - opens your browser for GitHub login.\nRequires the gh CLI (installed automatically via Homebrew).",
      label: '',
      placeholder: '',
      url: 'https://github.com/settings/tokens',
      urlLabel: 'GitHub settings',
    },
  ];

  let {
    step,
    onSaved,
    onSkipped,
  }: {
    step: number;
    onSaved: (key: string) => void;
    onSkipped: (key: string) => void;
  } = $props();

  const api = (window as any).atrophy;

  // Input values
  let elevenLabsKey = $state('');
  let falKey = $state('');
  let telegramToken = $state('');
  let telegramChatId = $state('');

  // Verification state
  let elevenLabsVerifying = $state(false);
  let elevenLabsVerified = $state<boolean | null>(null);
  let falVerifying = $state(false);
  let falVerified = $state<boolean | null>(null);
  let telegramVerifying = $state(false);
  let telegramVerified = $state<boolean | null>(null);

  // Google OAuth
  let googleWorkspace = $state(true);
  let googleExtra = $state(true);
  let googleAuthing = $state(false);
  let googleResult = $state<string | null>(null);

  // Skip confirmation
  let skipConfirmVisible = $state(false);

  // GitHub
  let githubChecking = $state(false);
  let githubInstalled = $state<boolean | null>(null);
  let githubAuthed = $state<boolean | null>(null);
  let githubAccount = $state('');
  let githubAuthing = $state(false);
  let githubError = $state('');

  function safeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/\n/g, '<br>');
  }

  // ---- Verification ----

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

  // ---- GitHub auth ----

  async function checkGitHub() {
    if (!api?.githubAuthStatus) return;
    githubChecking = true;
    githubError = '';
    try {
      const status = await api.githubAuthStatus();
      githubInstalled = status.installed;
      githubAuthed = status.authenticated;
      githubAccount = status.account;
      if (!status.installed) {
        githubError = 'gh CLI not installed. Run "brew install gh" in your terminal, then try again.';
      }
    } catch {
      githubError = 'Could not check GitHub status';
    }
    githubChecking = false;
  }

  async function startGitHubAuth() {
    if (!api?.githubAuthLogin) return;
    githubAuthing = true;
    githubError = '';
    try {
      const result = await api.githubAuthLogin();
      if (result.success) {
        githubAuthed = true;
        // Refresh account info
        try {
          const status = await api.githubAuthStatus();
          githubAccount = status.account;
        } catch { /* account display is non-critical */ }
      } else {
        githubError = result.error || 'Authentication failed';
      }
    } catch {
      githubError = 'Authentication failed - try running "gh auth login" in your terminal instead';
    } finally {
      githubAuthing = false;
    }
  }

  // ---- Save / Skip ----

  async function saveCurrentService() {
    const s = SERVICE_PROMPTS[step];
    if (!s) return;

    if (s.key === 'ELEVENLABS_API_KEY' && elevenLabsKey.trim()) {
      await api?.saveSecret('ELEVENLABS_API_KEY', elevenLabsKey.trim());
      onSaved('ELEVENLABS_API_KEY');
    } else if (s.key === 'FAL_KEY' && falKey.trim()) {
      await api?.saveSecret('FAL_KEY', falKey.trim());
      onSaved('FAL_KEY');
    } else if (s.key === 'TELEGRAM' && telegramToken.trim()) {
      await api?.saveSecret('TELEGRAM_BOT_TOKEN', telegramToken.trim());
      if (telegramChatId.trim()) {
        await api?.updateConfig({ TELEGRAM_CHAT_ID: telegramChatId.trim() });
      }
      // Start the polling daemon now that credentials are saved
      api?.startTelegramDaemon?.().catch(() => { /* non-critical */ });
      onSaved('TELEGRAM_BOT_TOKEN');
    } else if (s.key === 'GOOGLE' && googleResult === 'complete') {
      onSaved('GOOGLE');
    } else if (s.key === 'GITHUB' && githubAuthed) {
      onSaved('GITHUB');
    }
  }

  function skipCurrentService() {
    const s = SERVICE_PROMPTS[step];
    if (!s) return;
    // If service has a skip warning and we haven't confirmed yet, show it
    if (s.skipWarning && !skipConfirmVisible) {
      skipConfirmVisible = true;
      return;
    }
    skipConfirmVisible = false;
    onSkipped(s.key);
  }

  function cancelSkip() {
    skipConfirmVisible = false;
  }

  // Reset skip confirm when step changes
  $effect(() => {
    step; // track
    skipConfirmVisible = false;
  });

  function hasValue(): boolean {
    const s = SERVICE_PROMPTS[step];
    if (!s) return false;
    if (s.key === 'ELEVENLABS_API_KEY') return !!elevenLabsKey.trim();
    if (s.key === 'FAL_KEY') return !!falKey.trim();
    if (s.key === 'TELEGRAM') return !!telegramToken.trim();
    if (s.key === 'GOOGLE') return googleResult === 'complete';
    if (s.key === 'GITHUB') return githubAuthed === true;
    return false;
  }
</script>

{#if step >= 0 && step < SERVICE_PROMPTS.length}
  {@const svc = SERVICE_PROMPTS[step]}
  <div class="service-card fade-in" data-no-drag>
    <div class="service-card-header">
      <h3 class="service-card-title">{svc.title}</h3>
      <p class="service-card-desc">{@html safeHtml(svc.description)}</p>
      {#if svc.url}
        <a class="service-link" href={svc.url} target="_blank" rel="noopener">{svc.urlLabel || 'Open'} &#8599;</a>
      {/if}
    </div>

    {#if skipConfirmVisible && svc.skipWarning}
      <div class="skip-warning fade-in">
        <p class="skip-warning-text">{svc.skipWarning}</p>
        <div class="service-card-actions">
          <button class="svc-btn" onclick={cancelSkip}>Go back</button>
          <button class="svc-btn skip-confirm-btn" onclick={skipCurrentService}>Skip anyway</button>
        </div>
      </div>
    {/if}

    {#if !skipConfirmVisible}
    <div class="service-card-body">
      {#if svc.key === 'ELEVENLABS_API_KEY'}
        <label class="service-field">
          <span>{svc.label}</span>
          <input
            type="password"
            bind:value={elevenLabsKey}
            class="svc-input secure-input"
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
          <button class="svc-btn verify-btn" disabled={!elevenLabsKey.trim() || elevenLabsVerifying} onclick={verifyElevenLabs}>
            {elevenLabsVerifying ? 'Checking...' : 'Verify'}
          </button>
          <button class="svc-btn" onclick={elevenLabsKey.trim() ? saveCurrentService : skipCurrentService}>
            {elevenLabsKey.trim() ? 'Save' : 'Skip'}
          </button>
        </div>

      {:else if svc.key === 'FAL_KEY'}
        <label class="service-field">
          <span>{svc.label}</span>
          <input
            type="password"
            bind:value={falKey}
            class="svc-input secure-input"
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
          <button class="svc-btn verify-btn" disabled={!falKey.trim() || falVerifying} onclick={verifyFal}>
            {falVerifying ? 'Checking...' : 'Verify'}
          </button>
          <button class="svc-btn" onclick={falKey.trim() ? saveCurrentService : skipCurrentService}>
            {falKey.trim() ? 'Save' : 'Skip'}
          </button>
        </div>

      {:else if svc.key === 'TELEGRAM'}
        <label class="service-field">
          <span>Bot Token</span>
          <input
            type="password"
            bind:value={telegramToken}
            class="svc-input secure-input"
            placeholder="123456:ABC-DEF..."
            autofocus
          />
        </label>
        <label class="service-field">
          <span>Chat ID</span>
          <input
            type="text"
            bind:value={telegramChatId}
            class="svc-input"
            placeholder="12345678"
          />
        </label>
        {#if telegramVerified === true}
          <span class="verify-status verified">Bot verified</span>
        {:else if telegramVerified === false}
          <span class="verify-status failed">Invalid token</span>
        {/if}
        <div class="service-card-actions">
          <button class="svc-btn verify-btn" disabled={!telegramToken.trim() || telegramVerifying} onclick={verifyTelegram}>
            {telegramVerifying ? 'Checking...' : 'Verify'}
          </button>
          <button class="svc-btn" onclick={telegramToken.trim() ? saveCurrentService : skipCurrentService}>
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
          <button class="svc-btn verify-btn" disabled={googleAuthing || (!googleWorkspace && !googleExtra)} onclick={startGoogleAuth}>
            {googleAuthing ? 'Waiting for browser...' : 'Connect selected'}
          </button>
          <button class="svc-btn" onclick={googleResult === 'complete' ? saveCurrentService : skipCurrentService}>
            {googleResult === 'complete' ? 'Next' : 'Skip'}
          </button>
        </div>
      {:else if svc.key === 'GITHUB'}
        {#if githubInstalled === null}
          <div class="service-card-actions">
            <button class="svc-btn verify-btn" disabled={githubChecking} onclick={checkGitHub}>
              {githubChecking ? 'Checking...' : 'Check status'}
            </button>
            <button class="svc-btn" onclick={skipCurrentService}>Skip</button>
          </div>
        {:else if !githubInstalled}
          <p class="github-hint">
            Open your terminal and run:<br>
            <code class="github-code">brew install gh</code><br>
            Then come back and tap "Check again".
          </p>
          <div class="service-card-actions">
            <button class="svc-btn verify-btn" disabled={githubChecking} onclick={checkGitHub}>
              {githubChecking ? 'Checking...' : 'Check again'}
            </button>
            <button class="svc-btn" onclick={skipCurrentService}>Skip</button>
          </div>
        {:else if githubAuthed}
          <span class="verify-status verified">Connected as {githubAccount}</span>
          <div class="service-card-actions">
            <button class="svc-btn" onclick={saveCurrentService}>Next</button>
          </div>
        {:else}
          <p class="github-hint">
            This opens your browser for GitHub login.<br>
            No tokens or keys to copy.
          </p>
          {#if githubError}
            <span class="verify-status failed">{githubError}</span>
          {/if}
          <div class="service-card-actions">
            <button class="svc-btn verify-btn" disabled={githubAuthing} onclick={startGitHubAuth}>
              {githubAuthing ? 'Waiting for browser...' : 'Connect GitHub'}
            </button>
            <button class="svc-btn" onclick={skipCurrentService}>Skip</button>
          </div>
        {/if}
      {/if}
    </div>
    {/if}
  </div>
{/if}

<style>
  .service-card {
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    background: rgba(255, 255, 255, 0.02);
    margin: 0 var(--pad);
    flex-shrink: 0;
  }

  .fade-in {
    animation: fadeIn 0.4s ease forwards;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
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

  .service-link {
    display: inline-block;
    margin-top: 8px;
    font-size: 12px;
    color: rgba(100, 140, 255, 0.8);
    text-decoration: none;
    transition: color 0.15s;
  }

  .service-link:hover {
    color: rgba(100, 140, 255, 1);
    text-decoration: underline;
  }

  .skip-warning {
    padding: 12px 0;
  }

  .skip-warning-text {
    font-size: 13px;
    color: rgba(255, 180, 80, 0.9);
    line-height: 1.5;
    text-align: center;
    margin: 0 0 12px;
  }

  .skip-confirm-btn {
    background: rgba(255, 120, 80, 0.12);
    border-color: rgba(255, 120, 80, 0.35);
  }

  .skip-confirm-btn:hover:not(:disabled) {
    background: rgba(255, 120, 80, 0.22);
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

  /* ---- Inputs ---- */

  .svc-input {
    width: 100%;
    height: 44px;
    padding: 0 16px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: 15px;
    outline: none;
  }

  .svc-input:focus {
    border-color: var(--border-hover);
  }

  .secure-input {
    border-color: rgba(220, 140, 40, 0.45);
    font-family: var(--font-mono);
    font-size: 13px;
    letter-spacing: 0.5px;
  }

  .secure-input:focus {
    border-color: rgba(220, 160, 60, 0.7);
    box-shadow: 0 0 0 2px rgba(220, 140, 40, 0.12);
  }

  /* ---- Buttons ---- */

  .svc-btn {
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

  .svc-btn:hover:not(:disabled) {
    background: rgba(100, 140, 255, 0.2);
  }

  .svc-btn:disabled {
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

  /* ---- Verification status ---- */

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

  /* ---- Fields ---- */

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

  /* ---- GitHub ---- */

  .github-hint {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.5;
    margin: 0 0 12px;
    text-align: center;
  }

  .github-code {
    display: inline-block;
    margin-top: 6px;
    padding: 4px 12px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-family: var(--font-mono);
    font-size: 13px;
    color: var(--text-primary);
    user-select: all;
  }
</style>

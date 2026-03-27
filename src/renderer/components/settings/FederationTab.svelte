<!-- src/renderer/components/settings/FederationTab.svelte -->
<script lang="ts">
  const api = (window as any).api;

  interface FederationLink {
    remote_bot_username: string;
    telegram_group_id: string;
    local_agent: string;
    trust_tier: string;
    enabled: boolean;
    muted: boolean;
    description: string;
    rate_limit_per_hour: number;
    created_at: string;
  }

  interface TranscriptEntry {
    timestamp: string;
    direction: string;
    from_bot: string;
    to_bot: string;
    text: string;
    inference_triggered: boolean;
    trust_tier: string;
    skipped_reason?: string;
  }

  let links = $state<Record<string, FederationLink>>({});
  let activePollers = $state<string[]>([]);
  let selectedLink = $state<string | null>(null);
  let transcript = $state<TranscriptEntry[]>([]);
  let stats = $state<{ messageCount: number; lastMessage: string | null; sizeBytes: number } | null>(null);

  // Add link form
  let showAddForm = $state(false);
  let newName = $state('');
  let newRemoteBot = $state('');
  let newGroupId = $state('');
  let newLocalAgent = $state('');
  let newDescription = $state('');

  // Invite token
  let showInviteForm = $state(false);
  let inviteToken = $state('');
  let inviteLocalAgent = $state('');
  let inviteError = $state('');
  let invitePreview = $state<{ remoteBotUsername: string; telegramGroupId: string; description: string } | null>(null);

  export async function load() {
    await loadConfig();
  }

  async function loadConfig() {
    const config = await api.federationGetConfig();
    links = config?.links || {};
    activePollers = await api.federationGetActivePollers() || [];
  }

  async function selectLink(name: string) {
    selectedLink = name;
    transcript = await api.federationGetTranscript(name, 50) || [];
    stats = await api.federationGetStats(name) || null;
  }

  async function toggleEnabled(name: string) {
    const link = links[name];
    if (!link) return;
    await api.federationUpdateLink(name, { enabled: !link.enabled });
    await loadConfig();
  }

  async function toggleMuted(name: string) {
    const link = links[name];
    if (!link) return;
    await api.federationUpdateLink(name, { muted: !link.muted });
    await loadConfig();
  }

  async function changeTier(name: string, tier: string) {
    await api.federationUpdateLink(name, { trust_tier: tier });
    await loadConfig();
  }

  async function removeLinkByName(name: string) {
    await api.federationRemoveLink(name);
    if (selectedLink === name) {
      selectedLink = null;
      transcript = [];
      stats = null;
    }
    await loadConfig();
  }

  async function addLink() {
    if (!newName || !newRemoteBot || !newGroupId || !newLocalAgent) return;
    await api.federationAddLink(newName, {
      remote_bot_username: newRemoteBot,
      telegram_group_id: newGroupId,
      local_agent: newLocalAgent,
      description: newDescription,
    });
    showAddForm = false;
    newName = ''; newRemoteBot = ''; newGroupId = ''; newLocalAgent = ''; newDescription = '';
    await loadConfig();
  }

  async function previewInvite() {
    inviteError = '';
    invitePreview = null;
    if (!inviteToken.trim()) return;
    try {
      const parsed = await api.federationParseInvite(inviteToken.trim());
      invitePreview = parsed;
    } catch (e: any) {
      inviteError = e?.message || 'Invalid token';
    }
  }

  async function acceptInvite() {
    if (!inviteToken.trim() || !inviteLocalAgent.trim()) return;
    inviteError = '';
    try {
      await api.federationAcceptInvite(inviteToken.trim(), inviteLocalAgent.trim());
      showInviteForm = false;
      inviteToken = '';
      inviteLocalAgent = '';
      invitePreview = null;
      await loadConfig();
    } catch (e: any) {
      inviteError = e?.message || 'Failed to accept invite';
    }
  }

  $effect(() => { loadConfig(); });
</script>

<div class="federation-tab">
  <div class="section-header">
    <h3>Federation Links</h3>
    <div class="header-actions">
      <button class="btn-small" onclick={() => { showInviteForm = !showInviteForm; showAddForm = false; }}>
        {showInviteForm ? 'Cancel' : 'Paste Invite'}
      </button>
      <button class="btn-small" onclick={() => { showAddForm = !showAddForm; showInviteForm = false; }}>
        {showAddForm ? 'Cancel' : '+ Manual'}
      </button>
    </div>
  </div>

  {#if showInviteForm}
    <div class="add-form">
      <p class="form-hint">Paste a federation invite token from another Atrophy user</p>
      <input type="text" bind:value={inviteToken} placeholder="atrophy-fed-..." oninput={previewInvite} />
      {#if invitePreview}
        <div class="invite-preview">
          <span>Remote bot: @{invitePreview.remoteBotUsername}</span>
          <span>Group: {invitePreview.telegramGroupId}</span>
          {#if invitePreview.description}<span>{invitePreview.description}</span>{/if}
        </div>
      {/if}
      {#if inviteError}
        <p class="form-error">{inviteError}</p>
      {/if}
      <input type="text" bind:value={inviteLocalAgent} placeholder="Your agent to handle this link (e.g. xan)" />
      <button class="btn-small" onclick={acceptInvite} disabled={!invitePreview || !inviteLocalAgent}>Accept Invite</button>
    </div>
  {/if}

  {#if showAddForm}
    <div class="add-form">
      <input type="text" bind:value={newName} placeholder="Link name (e.g. sarah-companion)" />
      <input type="text" bind:value={newRemoteBot} placeholder="Remote bot username" />
      <input type="text" bind:value={newGroupId} placeholder="Telegram group ID" />
      <input type="text" bind:value={newLocalAgent} placeholder="Local agent name" />
      <input type="text" bind:value={newDescription} placeholder="Description (optional)" />
      <button class="btn-small" onclick={addLink}>Create</button>
    </div>
  {/if}

  <div class="links-list">
    {#each Object.entries(links) as [name, link]}
      <div class="link-row" class:selected={selectedLink === name} class:disabled={!link.enabled}>
        <button class="link-name" onclick={() => selectLink(name)}>
          <span class="status-dot" class:active={activePollers.includes(name)} class:muted={link.muted}></span>
          {name}
        </button>
        <span class="link-meta">@{link.remote_bot_username} - {link.local_agent}</span>
        <div class="link-actions">
          <select value={link.trust_tier} onchange={(e) => changeTier(name, (e.target as HTMLSelectElement).value)}>
            <option value="chat">Chat</option>
            <option value="query">Query</option>
            <option value="delegate">Delegate</option>
          </select>
          <button class="btn-tiny" onclick={() => toggleMuted(name)}>{link.muted ? 'Unmute' : 'Mute'}</button>
          <button class="btn-tiny" onclick={() => toggleEnabled(name)}>{link.enabled ? 'Disable' : 'Enable'}</button>
          <button class="btn-tiny danger" onclick={() => removeLinkByName(name)}>Remove</button>
        </div>
      </div>
    {/each}
    {#if Object.keys(links).length === 0}
      <p class="empty">No federation links configured. Add one to connect with another Atrophy instance.</p>
    {/if}
  </div>

  {#if selectedLink && stats}
    <div class="transcript-section">
      <h4>Transcript - {selectedLink}</h4>
      <p class="transcript-stats">{stats.messageCount} messages | Last: {stats.lastMessage || 'never'}</p>
      <div class="transcript-list">
        {#each transcript as entry}
          <div class="transcript-entry" class:inbound={entry.direction === 'inbound'} class:outbound={entry.direction === 'outbound'}>
            <span class="entry-time">{new Date(entry.timestamp).toLocaleTimeString()}</span>
            <span class="entry-direction">{entry.direction === 'inbound' ? '<-' : '->'}</span>
            <span class="entry-bot">@{entry.direction === 'inbound' ? entry.from_bot : entry.to_bot}</span>
            <span class="entry-text">{entry.text.slice(0, 200)}</span>
            {#if entry.skipped_reason}
              <span class="entry-skip">({entry.skipped_reason})</span>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .federation-tab { padding: 12px 0; }
  .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .section-header h3 { margin: 0; font-size: 14px; color: var(--text-primary); }
  .header-actions { display: flex; gap: 6px; }
  .form-hint { font-size: 12px; color: var(--text-secondary); margin: 0; }
  .form-error { font-size: 12px; color: #ef4444; margin: 0; }
  .invite-preview { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--text-secondary); padding: 8px; background: rgba(100,140,255,0.05); border-radius: 4px; }
  .add-form { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; padding: 12px; background: var(--bg-secondary); border-radius: 8px; }
  .add-form input { padding: 6px 10px; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 4px; color: var(--text-primary); font-size: 13px; }
  .links-list { display: flex; flex-direction: column; gap: 4px; }
  .link-row { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 6px; background: var(--bg-secondary); }
  .link-row.selected { border: 1px solid var(--accent); }
  .link-row.disabled { opacity: 0.5; }
  .link-name { background: none; border: none; color: var(--text-primary); font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px; }
  .link-meta { font-size: 11px; color: var(--text-secondary); flex: 1; }
  .link-actions { display: flex; gap: 4px; align-items: center; }
  .link-actions select { padding: 2px 6px; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 4px; color: var(--text-primary); font-size: 11px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #555; display: inline-block; }
  .status-dot.active { background: #4ade80; }
  .status-dot.muted { background: #f59e0b; }
  .btn-small { padding: 4px 10px; background: var(--accent); border: none; border-radius: 4px; color: var(--text-primary); font-size: 12px; cursor: pointer; }
  .btn-tiny { padding: 2px 6px; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 4px; color: var(--text-secondary); font-size: 11px; cursor: pointer; }
  .btn-tiny.danger { color: #ef4444; border-color: rgba(239,68,68,0.3); }
  .empty { color: var(--text-dim); font-size: 13px; text-align: center; padding: 20px; }
  .transcript-section { margin-top: 16px; }
  .transcript-section h4 { font-size: 13px; color: var(--text-primary); margin: 0 0 8px; }
  .transcript-stats { font-size: 11px; color: var(--text-dim); margin: 0 0 8px; }
  .transcript-list { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
  .transcript-entry { display: flex; gap: 6px; font-size: 12px; padding: 4px 8px; border-radius: 4px; }
  .transcript-entry.inbound { background: rgba(100,140,255,0.05); }
  .transcript-entry.outbound { background: rgba(100,255,140,0.05); }
  .entry-time { color: var(--text-dim); font-family: var(--font-mono); min-width: 70px; }
  .entry-direction { color: var(--text-dim); }
  .entry-bot { color: var(--text-secondary); min-width: 100px; }
  .entry-text { color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .entry-skip { color: var(--text-dim); font-style: italic; }
</style>

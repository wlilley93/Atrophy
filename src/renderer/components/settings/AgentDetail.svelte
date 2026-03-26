<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../../api';
  import JobEditor from './JobEditor.svelte';

  interface Props {
    agentName: string;
    schedule: unknown[];
    onDeleted: () => void;
    onSaved: () => void;
  }

  let { agentName, schedule, onDeleted, onSaved }: Props = $props();

  type SubTab = 'identity' | 'jobs' | 'mcp' | 'router';
  let activeSubTab = $state<SubTab>('identity');

  // Loading state
  let loading = $state(true);

  // Raw loaded data
  let manifest = $state<Record<string, unknown>>({});
  let systemPrompt = $state('');
  let soulDoc = $state('');

  // Identity fields
  let displayName = $state('');
  let role = $state('');
  let description = $state('');
  let openingLine = $state('');
  let wakeWords = $state('');
  let tier = $state<1 | 2 | 3>(1);
  let canAddressUser = $state(false);
  let canProvision = $state(false);
  let editSystemPrompt = $state('');
  let editSoulDoc = $state('');

  // Jobs (from manifest)
  let jobs = $state<Record<string, { schedule?: string; interval_seconds?: number; script: string; description?: string }>>({});

  // MCP
  let mcpInclude = $state<string[]>([]);
  let mcpExclude = $state<string[]>([]);

  // Router
  let acceptFrom = $state('');
  let rejectFrom = $state('');
  let maxQueueDepth = $state(20);
  let systemAccess = $state(false);
  let canAddressAgents = $state(false);

  // Save/delete state
  let saveStatus = $state('');
  let dirty = $state(false);
  let saving = $state(false);
  let confirmingDelete = $state(false);
  let deleting = $state(false);

  // Track original values for dirty detection
  let orig = $state<{
    displayName: string; role: string; description: string; openingLine: string;
    wakeWords: string; tier: number; canAddressUser: boolean; canProvision: boolean;
    systemPrompt: string; soulDoc: string;
    acceptFrom: string; rejectFrom: string; maxQueueDepth: number;
    systemAccess: boolean; canAddressAgents: boolean;
  }>({
    displayName: '', role: '', description: '', openingLine: '',
    wakeWords: '', tier: 1, canAddressUser: false, canProvision: false,
    systemPrompt: '', soulDoc: '',
    acceptFrom: '', rejectFrom: '', maxQueueDepth: 20,
    systemAccess: false, canAddressAgents: false,
  });

  // Watch for dirty state
  $effect(() => {
    dirty =
      displayName !== orig.displayName ||
      role !== orig.role ||
      description !== orig.description ||
      openingLine !== orig.openingLine ||
      wakeWords !== orig.wakeWords ||
      tier !== orig.tier ||
      canAddressUser !== orig.canAddressUser ||
      canProvision !== orig.canProvision ||
      editSystemPrompt !== orig.systemPrompt ||
      editSoulDoc !== orig.soulDoc ||
      acceptFrom !== orig.acceptFrom ||
      rejectFrom !== orig.rejectFrom ||
      maxQueueDepth !== orig.maxQueueDepth ||
      systemAccess !== orig.systemAccess ||
      canAddressAgents !== orig.canAddressAgents;
  });

  async function load() {
    if (!api) return;
    loading = true;
    dirty = false;
    try {
      const [mf, sys, soul] = await Promise.all([
        api.getAgentManifest(agentName),
        api.getAgentPrompt(agentName, 'system'),
        api.getAgentPrompt(agentName, 'soul'),
      ]);
      manifest = mf;

      // Identity
      displayName = (mf.display_name as string) ?? '';
      role = (mf.role as string) ?? '';
      description = (mf.description as string) ?? '';
      openingLine = (mf.opening_line as string) ?? '';
      const rawWake = mf.wake_words;
      wakeWords = Array.isArray(rawWake) ? rawWake.join(', ') : (rawWake as string) ?? '';
      tier = ((mf.tier as number) ?? 1) as 1 | 2 | 3;

      const orgCfg = (mf.org ?? {}) as Record<string, unknown>;
      canAddressUser = (orgCfg.can_address_user as boolean) ?? false;
      canProvision = (orgCfg.can_provision as boolean) ?? false;

      systemPrompt = sys ?? '';
      soulDoc = soul ?? '';
      editSystemPrompt = systemPrompt;
      editSoulDoc = soulDoc;

      // Jobs
      jobs = ((mf.jobs ?? {}) as Record<string, { schedule?: string; interval_seconds?: number; script: string; description?: string }>);

      // MCP
      const mcpCfg = (mf.mcp ?? {}) as Record<string, unknown>;
      mcpInclude = Array.isArray(mcpCfg.include) ? (mcpCfg.include as string[]) : [];
      mcpExclude = Array.isArray(mcpCfg.exclude) ? (mcpCfg.exclude as string[]) : [];

      // Router
      const routerCfg = (mf.router ?? {}) as Record<string, unknown>;
      const af = routerCfg.accept_from;
      acceptFrom = Array.isArray(af) ? af.join('\n') : (af as string) ?? '*';
      const rf = routerCfg.reject_from;
      rejectFrom = Array.isArray(rf) ? rf.join('\n') : (rf as string) ?? '';
      maxQueueDepth = (routerCfg.max_queue_depth as number) ?? 20;
      systemAccess = (routerCfg.system_access as boolean) ?? false;
      canAddressAgents = (routerCfg.can_address_agents as boolean) ?? false;

      // Snapshot for dirty detection
      orig = {
        displayName, role, description, openingLine, wakeWords,
        tier, canAddressUser, canProvision,
        systemPrompt: editSystemPrompt, soulDoc: editSoulDoc,
        acceptFrom, rejectFrom, maxQueueDepth, systemAccess, canAddressAgents,
      };
    } catch (err) {
      console.error('AgentDetail load failed:', err);
    }
    loading = false;
  }

  // Reload when agent changes
  $effect(() => {
    void agentName;
    void load();
  });

  function parseLines(text: string): string[] {
    return text.split('\n').map((l) => l.trim()).filter(Boolean);
  }

  async function save() {
    if (!api || saving) return;
    saving = true;
    saveStatus = '';
    try {
      const manifestUpdates: Record<string, unknown> = {
        display_name: displayName,
        role,
        description,
        opening_line: openingLine,
        wake_words: wakeWords.split(',').map((w) => w.trim()).filter(Boolean),
        tier,
        org: {
          ...(((manifest.org ?? {}) as Record<string, unknown>)),
          can_address_user: canAddressUser,
          can_provision: canProvision,
        },
        router: {
          accept_from: parseLines(acceptFrom),
          reject_from: parseLines(rejectFrom),
          max_queue_depth: maxQueueDepth,
          system_access: systemAccess,
          can_address_agents: canAddressAgents,
        },
        mcp: {
          include: mcpInclude,
          exclude: mcpExclude,
        },
      };

      const tasks: Promise<unknown>[] = [
        api.updateAgentManifest(agentName, manifestUpdates),
      ];

      if (editSystemPrompt !== orig.systemPrompt) {
        tasks.push(api.updateAgentPrompt(agentName, 'system', editSystemPrompt));
      }
      if (editSoulDoc !== orig.soulDoc) {
        tasks.push(api.updateAgentPrompt(agentName, 'soul', editSoulDoc));
      }

      await Promise.all(tasks);

      // Update originals
      orig = {
        displayName, role, description, openingLine, wakeWords,
        tier, canAddressUser, canProvision,
        systemPrompt: editSystemPrompt, soulDoc: editSoulDoc,
        acceptFrom, rejectFrom, maxQueueDepth, systemAccess, canAddressAgents,
      };
      dirty = false;
      saveStatus = 'Saved';
      setTimeout(() => (saveStatus = ''), 3000);
      onSaved();
    } catch {
      saveStatus = 'Error saving';
      setTimeout(() => (saveStatus = ''), 3000);
    }
    saving = false;
  }

  async function doDelete() {
    if (!api || deleting) return;
    deleting = true;
    try {
      await api.deleteAgent(agentName);
      onDeleted();
    } catch {
      saveStatus = 'Error deleting';
      setTimeout(() => (saveStatus = ''), 3000);
      deleting = false;
      confirmingDelete = false;
    }
  }

  async function handleJobsSave(updatedJobs: Record<string, unknown>) {
    jobs = updatedJobs as typeof jobs;
    try {
      await api?.updateAgentManifest(agentName, { jobs: updatedJobs });
    } catch (e) {
      saveStatus = `Error saving jobs: ${e}`;
      setTimeout(() => saveStatus = '', 3000);
    }
  }

  function toggleMcpItem(item: string, currentList: string[], otherList: string[]): void {
    if (currentList.includes(item)) {
      // Move to other list
      mcpInclude = mcpInclude.filter((i) => i !== item);
      mcpExclude = mcpExclude.filter((i) => i !== item);
      if (currentList === mcpInclude) {
        mcpExclude = [...mcpExclude, item];
      } else {
        mcpInclude = [...mcpInclude, item];
      }
    }
    dirty = true;
    void otherList; // suppress unused warning
  }
</script>

<div class="agent-detail">
  {#if loading}
    <div class="loading-state">Loading...</div>
  {:else}
    <!-- Agent heading -->
    <div class="detail-heading">
      <span class="detail-agent-name">{displayName || agentName}</span>
      <span class="detail-agent-slug">{agentName}</span>
    </div>

    <!-- Sub-tabs -->
    <div class="sub-tabs">
      <button class="sub-tab" class:active={activeSubTab === 'identity'} onclick={() => (activeSubTab = 'identity')}>Identity</button>
      <button class="sub-tab" class:active={activeSubTab === 'jobs'} onclick={() => (activeSubTab = 'jobs')}>Jobs</button>
      <button class="sub-tab" class:active={activeSubTab === 'mcp'} onclick={() => (activeSubTab = 'mcp')}>MCP</button>
      <button class="sub-tab" class:active={activeSubTab === 'router'} onclick={() => (activeSubTab = 'router')}>Router</button>
    </div>

    <!-- Tab content -->
    <div class="sub-content">

      <!-- ------------------------------------------------------------------ -->
      <!-- Identity Tab -->
      <!-- ------------------------------------------------------------------ -->
      {#if activeSubTab === 'identity'}
        <div class="form-section">
          <div class="form-row">
            <label class="form-label">Display Name</label>
            <input class="field-input" type="text" bind:value={displayName} />
          </div>
          <div class="form-row">
            <label class="form-label">Role</label>
            <input class="field-input" type="text" bind:value={role} placeholder="companion, assistant, specialist..." />
          </div>
          <div class="form-row">
            <label class="form-label">Description</label>
            <input class="field-input" type="text" bind:value={description} />
          </div>
          <div class="form-row">
            <label class="form-label">Opening Line</label>
            <input class="field-input" type="text" bind:value={openingLine} />
          </div>
          <div class="form-row">
            <label class="form-label">Wake Words (comma-separated)</label>
            <input class="field-input" type="text" bind:value={wakeWords} placeholder="hey, hello, xan..." />
          </div>
        </div>

        <div class="form-section">
          <div class="section-label">Tier</div>
          <div class="tier-radios">
            <label class="radio-label">
              <input type="radio" name="tier" value={1} bind:group={tier} />
              <span>1 - Leadership</span>
            </label>
            <label class="radio-label">
              <input type="radio" name="tier" value={2} bind:group={tier} />
              <span>2 - Specialists</span>
            </label>
            <label class="radio-label">
              <input type="radio" name="tier" value={3} bind:group={tier} />
              <span>3 - Support</span>
            </label>
          </div>
        </div>

        <div class="form-section">
          <div class="section-label">Org Permissions</div>
          <label class="checkbox-row">
            <input type="checkbox" bind:checked={canAddressUser} />
            <span class="checkbox-label">Can address user directly</span>
          </label>
          <label class="checkbox-row">
            <input type="checkbox" bind:checked={canProvision} />
            <span class="checkbox-label">Can provision new agents</span>
          </label>
        </div>

        <div class="form-section">
          <div class="form-row">
            <label class="form-label">System Prompt</label>
            <textarea class="field-textarea monospace" bind:value={editSystemPrompt} rows={10}></textarea>
          </div>
        </div>

        <div class="form-section">
          <div class="form-row">
            <label class="form-label">Soul Document</label>
            <textarea class="field-textarea monospace" bind:value={editSoulDoc} rows={8}></textarea>
          </div>
        </div>

      <!-- ------------------------------------------------------------------ -->
      <!-- Jobs Tab -->
      <!-- ------------------------------------------------------------------ -->
      {:else if activeSubTab === 'jobs'}
        <JobEditor
          {agentName}
          {jobs}
          schedule={schedule as never[]}
          onSave={handleJobsSave}
        />

      <!-- ------------------------------------------------------------------ -->
      <!-- MCP Tab -->
      <!-- ------------------------------------------------------------------ -->
      {:else if activeSubTab === 'mcp'}
        <div class="mcp-section">
          <div class="section-label">Included Servers</div>
          {#if mcpInclude.length === 0}
            <p class="empty-hint">No servers included.</p>
          {:else}
            {#each mcpInclude as srv}
              <label class="mcp-row">
                <input
                  type="checkbox"
                  checked={true}
                  onchange={() => {
                    mcpInclude = mcpInclude.filter((i) => i !== srv);
                    mcpExclude = [...mcpExclude, srv];
                    dirty = true;
                  }}
                />
                <span class="mcp-name">{srv}</span>
                <span class="mcp-badge included">included</span>
              </label>
            {/each}
          {/if}
        </div>

        <div class="mcp-section">
          <div class="section-label">Excluded Servers</div>
          {#if mcpExclude.length === 0}
            <p class="empty-hint">No servers excluded.</p>
          {:else}
            {#each mcpExclude as srv}
              <label class="mcp-row">
                <input
                  type="checkbox"
                  checked={false}
                  onchange={() => {
                    mcpExclude = mcpExclude.filter((i) => i !== srv);
                    mcpInclude = [...mcpInclude, srv];
                    dirty = true;
                  }}
                />
                <span class="mcp-name">{srv}</span>
                <span class="mcp-badge excluded">excluded</span>
              </label>
            {/each}
          {/if}
        </div>

        <div class="mcp-hint">Toggle a checkbox to move a server between include and exclude lists. Changes are saved with the main Save button.</div>

      <!-- ------------------------------------------------------------------ -->
      <!-- Router Tab -->
      <!-- ------------------------------------------------------------------ -->
      {:else if activeSubTab === 'router'}
        <div class="form-section">
          <div class="form-row">
            <label class="form-label">Accept From (one address per line)</label>
            <textarea class="field-textarea" bind:value={acceptFrom} rows={5} placeholder="*"></textarea>
          </div>
          <div class="form-row">
            <label class="form-label">Reject From (one address per line)</label>
            <textarea class="field-textarea" bind:value={rejectFrom} rows={3}></textarea>
          </div>
          <div class="form-row">
            <label class="form-label">Max Queue Depth</label>
            <input class="field-input narrow" type="number" min={1} max={200} bind:value={maxQueueDepth} />
          </div>
        </div>
        <div class="form-section">
          <div class="section-label">Permissions</div>
          <label class="checkbox-row">
            <input type="checkbox" bind:checked={systemAccess} />
            <span class="checkbox-label">System access</span>
          </label>
          <label class="checkbox-row">
            <input type="checkbox" bind:checked={canAddressAgents} />
            <span class="checkbox-label">Can address other agents</span>
          </label>
        </div>
      {/if}

    </div>

    <!-- Footer -->
    <div class="detail-footer">
      {#if saveStatus}
        <span class="save-status" class:error={saveStatus.startsWith('Error')}>{saveStatus}</span>
      {/if}

      <div class="footer-actions">
        {#if confirmingDelete}
          <span class="delete-confirm-text">Delete "{agentName}"?</span>
          <button class="footer-btn delete-confirm-btn" onclick={doDelete} disabled={deleting}>
            {deleting ? 'Deleting...' : 'Confirm Delete'}
          </button>
          <button class="footer-btn" onclick={() => (confirmingDelete = false)}>Cancel</button>
        {:else}
          <button class="footer-btn delete-btn" onclick={() => (confirmingDelete = true)}>Delete Agent</button>
          <button
            class="footer-btn save-btn"
            class:dirty={dirty}
            disabled={saving || !dirty}
            onclick={save}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .agent-detail {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }

  /* Loading */
  .loading-state {
    color: rgba(255, 255, 255, 0.3);
    font-size: 13px;
    padding: 40px;
    text-align: center;
  }

  /* Heading */
  .detail-heading {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 0 0 10px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 8px;
    flex-shrink: 0;
  }

  .detail-agent-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 15px;
    font-weight: 600;
  }

  .detail-agent-slug {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    font-family: var(--font-mono);
  }

  /* Sub-tabs */
  .sub-tabs {
    display: flex;
    gap: 3px;
    padding-bottom: 10px;
    flex-shrink: 0;
  }

  .sub-tab {
    padding: 4px 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: rgba(255, 255, 255, 0.03);
    color: rgba(255, 255, 255, 0.35);
    font-family: var(--font-sans);
    font-size: 11px;
    cursor: pointer;
    border-radius: 12px;
    transition: color 0.15s, background 0.15s;
  }

  .sub-tab:hover {
    color: rgba(255, 255, 255, 0.6);
    background: rgba(255, 255, 255, 0.06);
  }

  .sub-tab.active {
    background: rgba(100, 140, 255, 0.12);
    border-color: rgba(100, 140, 255, 0.3);
    color: rgba(100, 140, 255, 0.9);
  }

  /* Scrollable content area */
  .sub-content {
    flex: 1;
    overflow-y: auto;
    padding-right: 4px;
  }

  /* Form sections */
  .form-section {
    margin-bottom: 16px;
  }

  .section-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
  }

  .form-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 8px;
  }

  .form-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  .field-input {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.75);
    font-family: var(--font-sans);
    font-size: 12px;
    padding: 6px 8px;
    outline: none;
    transition: border-color 0.15s;
    width: 100%;
    box-sizing: border-box;
  }

  .field-input:focus {
    border-color: rgba(100, 140, 255, 0.4);
  }

  .field-input.narrow {
    width: 90px;
  }

  .field-textarea {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.75);
    font-family: var(--font-sans);
    font-size: 12px;
    padding: 7px 9px;
    outline: none;
    resize: vertical;
    transition: border-color 0.15s;
    width: 100%;
    box-sizing: border-box;
    min-height: 80px;
    line-height: 1.5;
  }

  .field-textarea:focus {
    border-color: rgba(100, 140, 255, 0.4);
  }

  .field-textarea.monospace {
    font-family: var(--font-mono);
    font-size: 11px;
    min-height: 200px;
  }

  /* Tier radio buttons */
  .tier-radios {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }

  .radio-label {
    display: flex;
    align-items: center;
    gap: 5px;
    cursor: pointer;
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
  }

  .radio-label input[type="radio"] {
    accent-color: rgba(100, 140, 255, 0.8);
    cursor: pointer;
  }

  /* Checkbox rows */
  .checkbox-row {
    display: flex;
    align-items: center;
    gap: 7px;
    cursor: pointer;
    margin-bottom: 6px;
  }

  .checkbox-row input[type="checkbox"] {
    accent-color: rgba(100, 140, 255, 0.8);
    cursor: pointer;
    width: 13px;
    height: 13px;
  }

  .checkbox-label {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
  }

  /* MCP section */
  .mcp-section {
    margin-bottom: 14px;
  }

  .mcp-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.1s;
  }

  .mcp-row:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .mcp-row input[type="checkbox"] {
    accent-color: rgba(100, 140, 255, 0.8);
    cursor: pointer;
  }

  .mcp-name {
    color: rgba(255, 255, 255, 0.7);
    font-size: 12px;
    font-family: var(--font-mono);
    flex: 1;
  }

  .mcp-badge {
    font-size: 9px;
    padding: 1px 6px;
    border-radius: 3px;
    font-weight: 600;
    letter-spacing: 0.3px;
  }

  .mcp-badge.included {
    background: rgba(92, 224, 214, 0.08);
    color: rgba(92, 224, 214, 0.5);
  }

  .mcp-badge.excluded {
    background: rgba(255, 100, 80, 0.08);
    color: rgba(255, 100, 80, 0.5);
  }

  .mcp-hint {
    color: rgba(255, 255, 255, 0.2);
    font-size: 10px;
    margin-top: 6px;
    line-height: 1.5;
  }

  .empty-hint {
    color: rgba(255, 255, 255, 0.2);
    font-size: 11px;
    padding: 6px 0;
  }

  /* Footer */
  .detail-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 0 0;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    flex-shrink: 0;
    margin-top: 8px;
    gap: 8px;
  }

  .save-status {
    color: rgba(92, 224, 214, 0.7);
    font-size: 11px;
    flex: 1;
  }

  .save-status.error {
    color: rgba(255, 100, 80, 0.7);
  }

  .footer-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .delete-confirm-text {
    color: rgba(255, 100, 80, 0.7);
    font-size: 11px;
  }

  .footer-btn {
    padding: 5px 14px;
    font-size: 12px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.45);
    border-radius: 6px;
    cursor: pointer;
    font-family: var(--font-sans);
    transition: background 0.15s, color 0.15s, border-color 0.15s;
    white-space: nowrap;
  }

  .footer-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.75);
  }

  .footer-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .footer-btn.delete-btn {
    color: rgba(255, 100, 80, 0.45);
    border-color: rgba(255, 100, 80, 0.15);
  }

  .footer-btn.delete-btn:hover:not(:disabled) {
    background: rgba(255, 100, 80, 0.08);
    color: rgba(255, 100, 80, 0.8);
    border-color: rgba(255, 100, 80, 0.25);
  }

  .footer-btn.delete-confirm-btn {
    color: rgba(255, 100, 80, 0.75);
    border-color: rgba(255, 100, 80, 0.25);
    background: rgba(255, 100, 80, 0.07);
  }

  .footer-btn.delete-confirm-btn:hover:not(:disabled) {
    background: rgba(255, 100, 80, 0.14);
    color: rgba(255, 100, 80, 1);
  }

  .footer-btn.save-btn {
    color: rgba(255, 255, 255, 0.35);
  }

  .footer-btn.save-btn.dirty {
    background: rgba(100, 140, 255, 0.1);
    border-color: rgba(100, 140, 255, 0.3);
    color: rgba(100, 140, 255, 0.9);
  }

  .footer-btn.save-btn.dirty:hover:not(:disabled) {
    background: rgba(100, 140, 255, 0.18);
    color: rgba(100, 140, 255, 1);
  }
</style>

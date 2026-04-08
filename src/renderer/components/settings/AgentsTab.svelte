<script lang="ts">
  import { api } from '../../api';
  import AgentsSidebar from './AgentsSidebar.svelte';
  import OrgChart from './OrgChart.svelte';
  import AgentEditModal from './AgentEditModal.svelte';
  import CreateOrgModal from './CreateOrgModal.svelte';
  import AddAgentModal from './AddAgentModal.svelte';

  interface AgentNode {
    name: string;
    display_name: string;
    description: string;
    role: string;
    tier: number;
    orgSlug: string | null;
    reportsTo: string | null;
    canAddressUser: boolean;
    enabled: boolean;
    topLevel: boolean;
  }

  interface Org {
    name: string;
    slug: string;
    type: string;
    purpose: string;
    created: string;
    principal: string | null;
  }

  type Selection =
    | { kind: 'agent'; name: string }
    | { kind: 'org'; slug: string }
    | null;

  // Raw data
  let orgs = $state<Org[]>([]);
  let allAgents = $state<AgentNode[]>([]);
  let schedule = $state<unknown[]>([]);

  // UI state
  let selection = $state<Selection>(null);
  let editingAgent = $state<string | null>(null);
  let modal = $state<'createOrg' | { type: 'addAgent'; orgSlug: string } | null>(null);
  let loading = $state(false);
  let loadError = $state('');

  // Primary agents = top-level (live at agents/<name>/data, not nested
  // under another agent's org). The orgSlug field is unreliable for this
  // because standalone agents like xan and companion still set internal
  // labels like 'system' or 'personal' on their org.slug.
  const primaryAgents = $derived(allAgents.filter((a) => a.topLevel));

  // Derived: agents in the currently selected org
  const agentsInSelectedOrg = $derived(
    selection?.kind === 'org'
      ? allAgents.filter((a) => a.orgSlug === selection.slug)
      : [],
  );

  // Derived: the selected org object
  const selectedOrg = $derived(
    selection?.kind === 'org' ? orgs.find((o) => o.slug === selection.slug) ?? null : null,
  );

  // Derived: the selected primary agent (if any)
  const selectedPrimaryAgent = $derived(
    selection?.kind === 'agent' ? allAgents.find((a) => a.name === selection.name) ?? null : null,
  );

  export async function load() {
    if (!api) return;
    loading = true;
    loadError = '';
    try {
      const [orgsResult, agentsResult, scheduleResult] = await Promise.all([
        api.listOrgs().catch((e: unknown) => { console.warn('listOrgs failed:', e); return []; }),
        api.listAllAgents().catch((e: unknown) => { console.warn('listAllAgents failed:', e); return []; }),
        api.getSchedule().catch((e: unknown) => { console.warn('getSchedule failed:', e); return []; }),
      ]);
      orgs = orgsResult || [];
      allAgents = (agentsResult || []) as AgentNode[];
      schedule = scheduleResult || [];
      if (allAgents.length === 0) loadError = 'No agents found';
    } catch (e) {
      loadError = `Failed to load: ${e}`;
      console.error('AgentsTab load error:', e);
    } finally {
      loading = false;
    }
  }

  async function handleRefresh() {
    await load();
    // If the selected target no longer exists, clear selection.
    if (selection?.kind === 'agent' && !allAgents.some((a) => a.name === selection.name)) {
      selection = null;
    } else if (selection?.kind === 'org' && !orgs.some((o) => o.slug === selection.slug)) {
      selection = null;
    }
  }

  function handleSelect(sel: Selection) {
    selection = sel;
    // Primary agents open the edit modal directly on click - no
    // intermediate "single agent view" page. Org agents open via the
    // OrgChart card click instead.
    if (sel?.kind === 'agent') {
      const agent = allAgents.find((a) => a.name === sel.name);
      if (agent?.topLevel) {
        editingAgent = sel.name;
      }
    }
  }

  function handleSelectAgent(name: string) {
    editingAgent = name;
  }

  function handleAddOrg() {
    modal = 'createOrg';
  }

  function handleAddAgentToOrg(orgSlug: string) {
    modal = { type: 'addAgent', orgSlug };
  }

  async function handleOrgCreated(slug: string) {
    modal = null;
    await load();
    // Focus the canvas on the new org so the user sees it immediately
    selection = { kind: 'org', slug };
  }

  async function handleAgentCreated() {
    modal = null;
    await load();
  }

  async function handleAgentEdited() {
    await load();
  }

  function closeEditModal() {
    editingAgent = null;
  }

  function closeAddModal() {
    modal = null;
  }
</script>

<div class="agents-tab">
  <!-- Sidebar -->
  <aside class="sidebar">
    {#if loading}
      <div class="loading">Loading...</div>
    {:else if loadError}
      <div class="error">{loadError}</div>
    {:else}
      <AgentsSidebar
        {primaryAgents}
        {orgs}
        {selection}
        onSelect={handleSelect}
        onAddOrg={handleAddOrg}
        onAddAgentToOrg={handleAddAgentToOrg}
      />
    {/if}
  </aside>

  <div class="divider"></div>

  <!-- Canvas -->
  <main class="canvas">
    {#if selection?.kind === 'org' && selectedOrg}
      <OrgChart
        org={selectedOrg}
        agentsInOrg={agentsInSelectedOrg}
        onSelectAgent={handleSelectAgent}
        onAddAgent={() => handleAddAgentToOrg(selectedOrg.slug)}
      />
    {:else if selection?.kind === 'agent' && selectedPrimaryAgent}
      <!-- Single primary agent: show one card with details + an inline
           "convert to org" hint via the sidebar plus button. -->
      <div class="single-agent-view">
        <header class="single-header">
          <div>
            <span class="single-name">{selectedPrimaryAgent.display_name || selectedPrimaryAgent.name}</span>
            {#if selectedPrimaryAgent.role}
              <span class="single-role">{selectedPrimaryAgent.role}</span>
            {/if}
          </div>
          <button class="edit-btn" onclick={() => handleSelectAgent(selectedPrimaryAgent.name)}>
            Edit profile
          </button>
        </header>
        {#if selectedPrimaryAgent.description}
          <p class="single-desc">{selectedPrimaryAgent.description}</p>
        {/if}
        <div class="single-hint">
          <p>This is a standalone primary agent.</p>
          <p>To give them a team of subordinates, click <strong>+ New organisation</strong> in the sidebar to spin up an org around them.</p>
        </div>
      </div>
    {:else}
      <div class="empty-canvas">
        <h3>Pick an agent or organisation</h3>
        <p>Use the sidebar on the left. Click a primary agent to view their profile, or an organisation to see its full org chart.</p>
      </div>
    {/if}
  </main>
</div>

<!-- Modals (rendered outside the layout flow) -->
{#if editingAgent}
  <AgentEditModal
    agentName={editingAgent}
    {schedule}
    onClose={closeEditModal}
    onChanged={handleAgentEdited}
  />
{/if}

{#if modal === 'createOrg'}
  <CreateOrgModal
    onCreated={handleOrgCreated}
    onCancel={closeAddModal}
  />
{:else if modal && typeof modal === 'object' && modal.type === 'addAgent'}
  {@const targetOrg = orgs.find((o) => o.slug === modal.orgSlug)}
  {#if targetOrg}
    <AddAgentModal
      org={targetOrg}
      existingAgents={allAgents.map((a) => ({
        name: a.name,
        display_name: a.display_name,
        tier: a.tier,
        orgSlug: a.orgSlug,
      }))}
      onCreated={handleAgentCreated}
      onCancel={closeAddModal}
    />
  {/if}
{/if}

<style>
  .agents-tab {
    display: flex;
    flex-direction: row;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .sidebar {
    width: 240px;
    flex-shrink: 0;
    overflow-y: auto;
    padding: 8px 4px 8px 4px;
  }

  .sidebar::-webkit-scrollbar {
    width: 4px;
  }

  .sidebar::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
  }

  .divider {
    width: 1px;
    background: rgba(255, 255, 255, 0.08);
    flex-shrink: 0;
    margin: 0 4px;
  }

  .canvas {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    padding: 8px 0 8px 12px;
    display: flex;
    flex-direction: column;
  }

  .loading,
  .error {
    color: rgba(255, 255, 255, 0.4);
    font-size: 12px;
    text-align: center;
    padding: 24px 8px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .error {
    color: rgba(255, 100, 100, 0.7);
  }

  .empty-canvas {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 32px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .empty-canvas h3 {
    color: rgba(255, 255, 255, 0.6);
    font-size: 14px;
    font-weight: 600;
    margin: 0 0 8px;
  }

  .empty-canvas p {
    color: rgba(255, 255, 255, 0.35);
    font-size: 12px;
    margin: 0;
    line-height: 1.5;
    max-width: 380px;
  }

  /* Single primary agent view */
  .single-agent-view {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 24px 32px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .single-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding-bottom: 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 18px;
  }

  .single-name {
    display: block;
    color: rgba(255, 255, 255, 0.95);
    font-size: 22px;
    font-weight: 600;
  }

  .single-role {
    display: block;
    margin-top: 4px;
    color: rgba(255, 255, 255, 0.45);
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .edit-btn {
    background: rgba(120, 160, 255, 0.12);
    border: 1px solid rgba(120, 160, 255, 0.3);
    color: rgba(170, 200, 255, 0.95);
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .edit-btn:hover {
    background: rgba(120, 160, 255, 0.2);
    border-color: rgba(120, 160, 255, 0.5);
  }

  .single-desc {
    color: rgba(255, 255, 255, 0.7);
    font-size: 13px;
    line-height: 1.55;
    margin: 0 0 24px;
    max-width: 640px;
  }

  .single-hint {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 14px 18px;
    max-width: 560px;
    color: rgba(255, 255, 255, 0.55);
    font-size: 12px;
    line-height: 1.6;
  }

  .single-hint p {
    margin: 0 0 6px;
  }

  .single-hint p:last-child {
    margin: 0;
  }

  .single-hint strong {
    color: rgba(170, 200, 255, 0.85);
    font-weight: 600;
  }
</style>

<script lang="ts">
  import { api } from '../../api';
  import OrgTree from './OrgTree.svelte';
  import AgentDetail from './AgentDetail.svelte';
  import OrgDetail from './OrgDetail.svelte';
  import AgentCreateForm from './AgentCreateForm.svelte';

  interface OrgNode {
    slug: string;
    name: string;
    type: string;
    agents: AgentNode[];
  }

  interface AgentNode {
    name: string;
    display_name: string;
    role: string;
    tier: number;
    orgSlug: string | null;
    enabled: boolean;
  }

  // Raw data
  let orgs = $state<Array<{ name: string; slug: string; type: string; purpose: string; created: string; principal: string | null }>>([]);
  let allAgents = $state<Array<{ name: string; display_name: string; description: string; role: string; tier: number; orgSlug: string | null; reportsTo: string | null; canAddressUser: boolean; enabled: boolean }>>([]);
  let schedule = $state<unknown[]>([]);

  // Tree structure
  let orgTree = $state<OrgNode[]>([]);
  let standalone = $state<AgentNode[]>([]);

  // Selection
  let selectedId = $state<string | null>(null);
  let selectedType = $state<'agent' | 'org' | 'create' | null>(null);

  // Loading
  let loading = $state(false);
  let loadError = $state('');

  function buildTree() {
    const orgMap = new Map<string, OrgNode>();
    for (const org of orgs) {
      orgMap.set(org.slug, { slug: org.slug, name: org.name, type: org.type, agents: [] });
    }

    const standaloneList: AgentNode[] = [];
    for (const agent of allAgents) {
      const node: AgentNode = {
        name: agent.name,
        display_name: agent.display_name,
        role: agent.role,
        tier: agent.tier,
        orgSlug: agent.orgSlug,
        enabled: agent.enabled,
      };
      if (agent.orgSlug && orgMap.has(agent.orgSlug)) {
        orgMap.get(agent.orgSlug)!.agents.push(node);
      } else {
        standaloneList.push(node);
      }
    }

    orgTree = [...orgMap.values()];
    standalone = standaloneList;
  }

  export async function load() {
    if (!api) return;
    loading = true;
    loadError = '';
    try {
      // Fetch independently so one failure doesn't block all
      const [orgsResult, agentsResult, scheduleResult] = await Promise.all([
        api.listOrgs().catch((e: unknown) => { console.warn('listOrgs failed:', e); return []; }),
        api.listAllAgents().catch((e: unknown) => { console.warn('listAllAgents failed:', e); return []; }),
        api.getSchedule().catch((e: unknown) => { console.warn('getSchedule failed:', e); return []; }),
      ]);
      orgs = orgsResult || [];
      allAgents = agentsResult || [];
      schedule = scheduleResult || [];
      buildTree();
      if (allAgents.length === 0) {
        loadError = 'No agents found';
      }
    } catch (e) {
      loadError = `Failed to load: ${e}`;
      console.error('AgentsTab load error:', e);
    } finally {
      loading = false;
    }
  }

  function handleSelect(id: string, type: 'agent' | 'org') {
    selectedId = id;
    selectedType = type;
  }

  function handleCreateAgent() {
    selectedId = null;
    selectedType = 'create';
  }

  function handleCreateOrg() {
    selectedId = '__new_org__';
    selectedType = 'org';
  }

  async function handleRefresh() {
    await load();
    // Reset selection if the selected item no longer exists
    if (selectedType === 'agent' && selectedId) {
      const stillExists = allAgents.some((a) => a.name === selectedId);
      if (!stillExists) {
        selectedId = null;
        selectedType = null;
      }
    } else if (selectedType === 'org' && selectedId && selectedId !== '__new_org__') {
      const stillExists = orgs.some((o) => o.slug === selectedId);
      if (!stillExists) {
        selectedId = null;
        selectedType = null;
      }
    }
  }

  // Org options for create form
  const orgOptions = $derived(orgs.map((o) => ({ slug: o.slug, name: o.name })));

  // All agents for create form (reports-to)
  const agentOptions = $derived(
    allAgents.map((a) => ({
      name: a.name,
      display_name: a.display_name,
      tier: a.tier,
      orgSlug: a.orgSlug,
    }))
  );
</script>

<div class="agents-tab">
  <!-- Left panel: tree -->
  <div class="left-panel">
    {#if loading}
      <div class="loading-hint">Loading...</div>
    {:else if loadError}
      <div class="error-hint">{loadError}</div>
    {:else}
      <OrgTree
        orgs={orgTree}
        {standalone}
        {selectedId}
        {selectedType}
        onSelect={handleSelect}
        onCreateAgent={handleCreateAgent}
        onCreateOrg={handleCreateOrg}
      />
    {/if}
  </div>

  <!-- Divider -->
  <div class="panel-divider"></div>

  <!-- Right panel: detail or form -->
  <div class="right-panel">
    {#if selectedType === 'agent' && selectedId}
      <AgentDetail
        agentName={selectedId}
        {schedule}
        onDeleted={handleRefresh}
        onSaved={handleRefresh}
      />
    {:else if selectedType === 'org' && selectedId}
      <OrgDetail
        orgSlug={selectedId}
        onDissolved={handleRefresh}
        onSaved={handleRefresh}
      />
    {:else if selectedType === 'create'}
      <AgentCreateForm
        orgs={orgOptions}
        allAgents={agentOptions}
        onCreated={handleRefresh}
        onCancel={() => { selectedType = null; selectedId = null; }}
      />
    {:else}
      <div class="empty-state">
        <p class="empty-title">Select an agent or organisation</p>
        <p class="empty-hint">Use the tree on the left to navigate, or create something new.</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .agents-tab {
    display: flex;
    flex-direction: row;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .left-panel {
    width: 280px;
    flex-shrink: 0;
    overflow-y: auto;
    padding: 8px 4px 8px 0;
  }

  .left-panel::-webkit-scrollbar {
    width: 4px;
  }

  .left-panel::-webkit-scrollbar-track {
    background: transparent;
  }

  .left-panel::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
  }

  .panel-divider {
    width: 1px;
    background: rgba(255, 255, 255, 0.08);
    flex-shrink: 0;
    margin: 0 4px;
  }

  .right-panel {
    flex: 1;
    min-width: 0;
    overflow-y: auto;
    padding: 8px 0 8px 12px;
  }

  .right-panel::-webkit-scrollbar {
    width: 4px;
  }

  .right-panel::-webkit-scrollbar-track {
    background: transparent;
  }

  .right-panel::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
  }

  .loading-hint {
    color: rgba(255, 255, 255, 0.3);
    font-size: 12px;
    text-align: center;
    padding: 24px 8px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .error-hint {
    color: rgba(255, 100, 100, 0.7);
    font-size: 12px;
    text-align: center;
    padding: 24px 8px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    padding: 32px 16px;
    text-align: center;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .empty-title {
    color: rgba(255, 255, 255, 0.4);
    font-size: 13px;
    font-weight: 500;
    margin: 0 0 8px;
  }

  .empty-hint {
    color: rgba(255, 255, 255, 0.2);
    font-size: 12px;
    margin: 0;
    line-height: 1.5;
  }
</style>

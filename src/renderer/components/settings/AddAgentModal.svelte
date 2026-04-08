<script lang="ts">
  /**
   * AddAgentModal - flow for spawning a new agent into an organisation.
   *
   * Tier picker is the centrepiece. Each tier has a description so users
   * can pick the right level without thinking about numbers. Reports-to
   * auto-populates with possible parents from the next-higher tier (lower
   * tier number = more senior).
   */
  import { api } from '../../api';

  interface AgentOption {
    name: string;
    display_name: string;
    tier: number;
    orgSlug: string | null;
  }

  interface Org {
    slug: string;
    name: string;
    type: string;
    principal: string | null;
  }

  interface Props {
    org: Org;
    existingAgents: AgentOption[];
    onCreated: () => void;
    onCancel: () => void;
  }

  let { org, existingAgents, onCreated, onCancel }: Props = $props();

  let name = $state('');
  let displayName = $state('');
  let role = $state('');
  let tier = $state<number>(2);
  let reportsTo = $state('');
  let specialism = $state('');

  let creating = $state(false);
  let errorMsg = $state('');

  // Auto-slugify name from display name as user types.
  const slug = $derived(
    name
      ? name
          .toLowerCase()
          .replace(/[\s-]+/g, '_')
          .replace(/[^a-z0-9_]/g, '')
          .replace(/_+/g, '_')
      : displayName
          .toLowerCase()
          .replace(/[\s-]+/g, '_')
          .replace(/[^a-z0-9_]/g, '')
          .replace(/_+/g, '_'),
  );

  // Possible "reports to" candidates: agents in this org with strictly
  // higher tier number = no wait, lower tier number means more senior.
  // Tier 1 reports to no one (or to the principal). Tier 2 reports to
  // someone in tier 1. Tier 3 reports to someone in tier 1 or 2.
  const reportsToOptions = $derived(
    existingAgents.filter((a) => a.orgSlug === org.slug && a.tier < tier),
  );

  // Reset reports-to when tier changes since the candidate set shifts.
  $effect(() => {
    void tier;
    if (reportsTo && !reportsToOptions.find((a) => a.name === reportsTo)) {
      reportsTo = '';
    }
  });

  const TIERS: Array<{ value: number; label: string; desc: string; color: string }> = [
    {
      value: 1,
      label: 'Leadership',
      desc: 'Reports directly to you. Sets direction. Has authority to dispatch other agents.',
      color: 'rgba(120, 160, 255, 0.85)',
    },
    {
      value: 2,
      label: 'Specialist',
      desc: 'Domain expert. Reports to a tier-1 leader. Owns a specific area of work.',
      color: 'rgba(100, 220, 140, 0.85)',
    },
    {
      value: 3,
      label: 'Worker',
      desc: 'Executes specific tasks. Reports to a tier-2 specialist. Narrow focus.',
      color: 'rgba(220, 160, 100, 0.85)',
    },
  ];

  async function handleCreate() {
    errorMsg = '';
    if (!displayName.trim()) {
      errorMsg = 'Display name is required';
      return;
    }
    if (!slug) {
      errorMsg = 'Name must contain at least one letter or digit';
      return;
    }
    if (!role.trim()) {
      errorMsg = 'Role is required';
      return;
    }
    if (tier > 1 && !reportsTo && reportsToOptions.length > 0) {
      errorMsg = `Pick who this ${TIERS.find(t => t.value === tier)?.label.toLowerCase()} reports to`;
      return;
    }
    if (!api) return;

    creating = true;
    try {
      await api.quickCreateAgent({
        name: slug,
        displayName: displayName.trim(),
        role: role.trim(),
        orgSlug: org.slug,
        tier,
        reportsTo: reportsTo || undefined,
        specialism: specialism.trim() || undefined,
      });
      onCreated();
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : 'Create failed';
    } finally {
      creating = false;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onCancel();
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleCreate();
  }
</script>

<svelte:window onkeydown={handleKeydown}/>

<div class="modal-backdrop" onclick={onCancel} role="presentation"></div>

<div class="modal" role="dialog" aria-modal="true" aria-labelledby="add-agent-title">
  <header class="modal-header">
    <h2 id="add-agent-title">
      Add agent to <span class="org-name">{org.name}</span>
    </h2>
    <button class="close-btn" onclick={onCancel} aria-label="Cancel">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <line x1="6" y1="6" x2="18" y2="18"/>
        <line x1="6" y1="18" x2="18" y2="6"/>
      </svg>
    </button>
  </header>

  <div class="modal-body">
    <div class="row-2">
      <div class="field">
        <label for="agent-display" class="field-label">Display name</label>
        <input
          id="agent-display"
          type="text"
          class="text-input"
          bind:value={displayName}
          placeholder="e.g. Henry Mancini"
        />
      </div>
      <div class="field">
        <label for="agent-name" class="field-label">Internal name</label>
        <input
          id="agent-name"
          type="text"
          class="text-input"
          bind:value={name}
          placeholder="auto from display name"
        />
        {#if slug}
          <span class="field-hint">slug: <code>{slug}</code></span>
        {/if}
      </div>
    </div>

    <div class="field">
      <label for="agent-role" class="field-label">Role / title</label>
      <input
        id="agent-role"
        type="text"
        class="text-input"
        bind:value={role}
        placeholder="e.g. Chief of Staff, Russia Desk Officer, Junior Analyst"
      />
    </div>

    <!-- Tier picker -->
    <div class="field">
      <span class="field-label">Level</span>
      <div class="tier-grid">
        {#each TIERS as t}
          <button
            type="button"
            class="tier-card"
            class:selected={tier === t.value}
            style="--tier-accent: {t.color}"
            onclick={() => tier = t.value}
          >
            <span class="tier-badge">T{t.value}</span>
            <span class="tier-label">{t.label}</span>
            <span class="tier-desc">{t.desc}</span>
          </button>
        {/each}
      </div>
    </div>

    <!-- Reports to (only relevant for tier > 1) -->
    {#if tier > 1}
      <div class="field">
        <label for="agent-reports" class="field-label">Reports to</label>
        {#if reportsToOptions.length === 0}
          <p class="empty-reports">
            No tier-{tier - 1} or higher agents exist in <strong>{org.name}</strong>
            yet. Add a leader first or pick tier 1.
          </p>
        {:else}
          <select id="agent-reports" class="text-input" bind:value={reportsTo}>
            <option value="">Select a parent...</option>
            {#each reportsToOptions as p}
              <option value={p.name}>
                {p.display_name || p.name} (T{p.tier})
              </option>
            {/each}
          </select>
        {/if}
      </div>
    {/if}

    <div class="field">
      <label for="agent-spec" class="field-label">Specialism (optional)</label>
      <input
        id="agent-spec"
        type="text"
        class="text-input"
        bind:value={specialism}
        placeholder="e.g. maritime intelligence, energy markets, dark pools"
      />
    </div>

    {#if errorMsg}
      <div class="error">{errorMsg}</div>
    {/if}
  </div>

  <footer class="modal-footer">
    <button class="btn btn-ghost" onclick={onCancel} disabled={creating}>Cancel</button>
    <button class="btn btn-primary" onclick={handleCreate} disabled={creating}>
      {creating ? 'Creating...' : 'Create agent'}
    </button>
  </footer>
</div>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 100;
  }

  .modal {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: min(640px, calc(100% - 48px));
    max-height: calc(100vh - 80px);
    background: rgba(28, 28, 32, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
    z-index: 101;
    display: flex;
    flex-direction: column;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 22px 14px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .modal-header h2 {
    margin: 0;
    color: rgba(255, 255, 255, 0.7);
    font-size: 14px;
    font-weight: 600;
  }

  .modal-header .org-name {
    color: rgba(255, 255, 255, 0.95);
  }

  .close-btn {
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
    transition: color 0.15s, background 0.15s;
  }

  .close-btn:hover {
    color: rgba(255, 255, 255, 0.85);
    background: rgba(255, 255, 255, 0.06);
  }

  .modal-body {
    padding: 18px 22px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .row-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .field-label {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .text-input {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 9px 12px;
    color: rgba(255, 255, 255, 0.92);
    font-size: 13px;
    font-family: inherit;
    width: 100%;
    box-sizing: border-box;
    transition: border-color 0.15s;
  }

  .text-input:focus {
    outline: none;
    border-color: rgba(120, 160, 255, 0.5);
  }

  .field-hint {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
  }

  .field-hint code {
    color: rgba(120, 160, 255, 0.7);
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  }

  .tier-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
  }

  .tier-card {
    --tier-accent: rgba(120, 160, 255, 0.85);
    display: flex;
    flex-direction: column;
    gap: 5px;
    align-items: flex-start;
    text-align: left;
    padding: 12px 12px 14px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    cursor: pointer;
    color: inherit;
    font-family: inherit;
    transition: background 0.15s, border-color 0.15s;
  }

  .tier-card:hover {
    background: rgba(255, 255, 255, 0.06);
    border-color: var(--tier-accent);
  }

  .tier-card.selected {
    background: color-mix(in srgb, var(--tier-accent) 10%, transparent);
    border-color: var(--tier-accent);
  }

  .tier-badge {
    color: var(--tier-accent);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
  }

  .tier-label {
    color: rgba(255, 255, 255, 0.92);
    font-size: 13px;
    font-weight: 600;
  }

  .tier-desc {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    line-height: 1.45;
  }

  .empty-reports {
    color: rgba(255, 200, 100, 0.7);
    font-size: 12px;
    padding: 10px 12px;
    background: rgba(255, 200, 100, 0.06);
    border: 1px solid rgba(255, 200, 100, 0.2);
    border-radius: 6px;
    margin: 0;
    line-height: 1.45;
  }

  .empty-reports strong {
    color: rgba(255, 220, 150, 0.9);
  }

  .error {
    color: rgba(255, 120, 120, 0.9);
    font-size: 12px;
    padding: 8px 10px;
    background: rgba(255, 120, 120, 0.08);
    border: 1px solid rgba(255, 120, 120, 0.25);
    border-radius: 6px;
  }

  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 14px 22px 18px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .btn {
    padding: 8px 16px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    border: 1px solid transparent;
    transition: background 0.15s, border-color 0.15s;
  }

  .btn-ghost {
    background: none;
    border-color: rgba(255, 255, 255, 0.15);
    color: rgba(255, 255, 255, 0.6);
  }

  .btn-ghost:hover {
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.9);
  }

  .btn-primary {
    background: rgba(120, 160, 255, 0.18);
    border-color: rgba(120, 160, 255, 0.5);
    color: rgba(180, 210, 255, 0.95);
  }

  .btn-primary:hover:not(:disabled) {
    background: rgba(120, 160, 255, 0.3);
    border-color: rgba(120, 160, 255, 0.7);
  }

  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>

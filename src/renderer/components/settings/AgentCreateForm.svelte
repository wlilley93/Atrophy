<script lang="ts">
  import { api } from '../../api';

  interface OrgOption {
    slug: string;
    name: string;
  }

  interface AgentOption {
    name: string;
    display_name: string;
    tier: number;
    orgSlug: string | null;
  }

  interface Props {
    orgs: OrgOption[];
    allAgents: AgentOption[];
    onCreated: () => void;
    onCancel: () => void;
  }

  let { orgs, allAgents, onCreated, onCancel }: Props = $props();

  // Form fields
  let name = $state('');
  let displayName = $state('');
  let role = $state('');
  let selectedOrgSlug = $state('');
  let tier = $state(2);
  let reportsTo = $state('');
  let specialism = $state('');

  let creating = $state(false);
  let errors = $state<Record<string, string>>({});

  // Auto-slugify name
  function slugifyName(input: string): string {
    return input
      .toLowerCase()
      .replace(/[\s-]+/g, '_')
      .replace(/[^a-z0-9_]/g, '')
      .replace(/_+/g, '_');
  }

  $effect(() => {
    // Sync displayName to name if displayName not yet manually edited
    if (!displayName && name) {
      displayName = name
        .split(/[\s_-]+/)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
    }
  });

  // Agents in selected org with tier lower than selected tier (for reports-to)
  const reportsToOptions = $derived.by(() => {
    if (!selectedOrgSlug) return [];
    return allAgents.filter(
      (a) => a.orgSlug === selectedOrgSlug && a.tier < tier,
    );
  });

  // Reset reportsTo when org or tier changes
  $effect(() => {
    // Read reactive deps so this effect re-runs on change
    void selectedOrgSlug;
    void tier;
    reportsTo = '';
  });

  function validate(): boolean {
    const errs: Record<string, string> = {};
    const nameVal = slugifyName(name);
    if (!nameVal) {
      errs.name = 'Name is required';
    } else if (!/^[a-z0-9_-]+$/.test(nameVal)) {
      errs.name = 'Only a-z, 0-9, _ allowed';
    }
    if (!displayName.trim()) errs.displayName = 'Display name is required';
    if (!role.trim()) errs.role = 'Role is required';
    errors = errs;
    return Object.keys(errs).length === 0;
  }

  async function handleCreate() {
    if (!validate() || !api) return;
    creating = true;
    try {
      await api.quickCreateAgent({
        name: slugifyName(name),
        displayName: displayName.trim(),
        role: role.trim(),
        orgSlug: selectedOrgSlug || undefined,
        tier: selectedOrgSlug ? tier : undefined,
        reportsTo: reportsTo || undefined,
        specialism: specialism.trim() || undefined,
      });
      onCreated();
    } catch (e) {
      errors = { _form: e instanceof Error ? e.message : 'Create failed' };
    } finally {
      creating = false;
    }
  }

  const slugPreview = $derived(slugifyName(name));
</script>

<div class="agent-create-form">
  <div class="form-header">
    <span class="form-title">New Agent</span>
  </div>

  <div class="form-body">
    <!-- Name -->
    <div class="field-group">
      <label class="field">
        <span class="field-label">Name</span>
        <input
          type="text"
          bind:value={name}
          class="field-input"
          class:has-error={!!errors.name}
          placeholder="e.g. research_fellow"
          autofocus
        />
      </label>
      {#if slugPreview && slugPreview !== name}
        <span class="slug-preview">slug: {slugPreview}</span>
      {/if}
      {#if errors.name}
        <span class="field-error">{errors.name}</span>
      {/if}
    </div>

    <!-- Display Name -->
    <div class="field-group">
      <label class="field">
        <span class="field-label">Display Name</span>
        <input
          type="text"
          bind:value={displayName}
          class="field-input"
          class:has-error={!!errors.displayName}
          placeholder="e.g. Research Fellow"
        />
      </label>
      {#if errors.displayName}
        <span class="field-error">{errors.displayName}</span>
      {/if}
    </div>

    <!-- Role -->
    <div class="field-group">
      <label class="field">
        <span class="field-label">Role</span>
        <input
          type="text"
          bind:value={role}
          class="field-input"
          class:has-error={!!errors.role}
          placeholder="e.g. Research Fellow"
        />
      </label>
      {#if errors.role}
        <span class="field-error">{errors.role}</span>
      {/if}
    </div>

    <!-- Organisation -->
    <label class="field">
      <span class="field-label">Organisation</span>
      <select bind:value={selectedOrgSlug} class="field-select">
        <option value="">None (standalone)</option>
        {#each orgs as org}
          <option value={org.slug}>{org.name}</option>
        {/each}
      </select>
    </label>

    <!-- Tier (only when org selected) -->
    {#if selectedOrgSlug}
      <label class="field">
        <span class="field-label">Tier</span>
        <select bind:value={tier} class="field-select">
          <option value={1}>1 - Leadership</option>
          <option value={2}>2 - Specialists</option>
          <option value={3}>3 - Support</option>
        </select>
      </label>

      <!-- Reports To (only when eligible agents exist) -->
      {#if reportsToOptions.length > 0}
        <label class="field">
          <span class="field-label">Reports To</span>
          <select bind:value={reportsTo} class="field-select">
            <option value="">None</option>
            {#each reportsToOptions as agent}
              <option value={agent.name}>{agent.display_name || agent.name}</option>
            {/each}
          </select>
        </label>
      {/if}
    {/if}

    <!-- Specialism -->
    <label class="field">
      <span class="field-label">Specialism</span>
      <input
        type="text"
        bind:value={specialism}
        class="field-input"
        placeholder="Optional - e.g. Molecular Biology"
      />
    </label>

    {#if errors._form}
      <p class="form-error">{errors._form}</p>
    {/if}

    <div class="action-row">
      <button
        class="btn btn-primary"
        onclick={handleCreate}
        disabled={creating}
      >
        {creating ? 'Creating...' : 'Create Agent'}
      </button>
      <button class="btn btn-ghost" onclick={onCancel} disabled={creating}>
        Cancel
      </button>
    </div>
  </div>
</div>

<style>
  .agent-create-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
    color: var(--text-primary, rgba(255, 255, 255, 0.85));
  }

  .form-header {
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .form-title {
    font-size: 14px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.85);
  }

  .form-body {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Field group (field + helper text) */
  .field-group {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  /* Field row */
  .field {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 28px;
  }

  .field-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: rgba(255, 255, 255, 0.4);
    flex-shrink: 0;
    min-width: 88px;
  }

  .field-input {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.85);
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
    font-size: 13px;
    padding: 5px 9px;
    flex: 1;
    min-width: 0;
    transition: border-color 0.15s;
    -webkit-app-region: no-drag;
  }

  .field-input:focus {
    outline: none;
    border-color: rgba(100, 140, 255, 0.5);
  }

  .field-input.has-error {
    border-color: rgba(220, 60, 60, 0.5);
  }

  .field-select {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.85);
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
    font-size: 13px;
    padding: 5px 9px;
    flex: 1;
    cursor: pointer;
    -webkit-app-region: no-drag;
  }

  .field-select:focus {
    outline: none;
    border-color: rgba(100, 140, 255, 0.5);
  }

  /* Slug preview */
  .slug-preview {
    font-size: 11px;
    font-family: var(--font-mono, 'SF Mono', monospace);
    color: rgba(255, 255, 255, 0.3);
    padding-left: 100px;
  }

  /* Field error */
  .field-error {
    font-size: 11px;
    color: rgba(255, 100, 100, 0.85);
    padding-left: 100px;
  }

  /* Form-level error */
  .form-error {
    font-size: 11px;
    color: rgba(255, 100, 100, 0.85);
    padding: 4px 0;
  }

  /* Action row */
  .action-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 6px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    margin-top: 4px;
  }

  /* Buttons */
  .btn {
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
    font-size: 12px;
    font-weight: 500;
    padding: 5px 13px;
    border-radius: 5px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
    -webkit-app-region: no-drag;
  }

  .btn:disabled {
    opacity: 0.45;
    cursor: default;
  }

  .btn-primary {
    background: rgba(100, 140, 255, 0.25);
    border: 1px solid rgba(100, 140, 255, 0.4);
    color: rgba(150, 180, 255, 0.95);
  }

  .btn-primary:not(:disabled):hover {
    background: rgba(100, 140, 255, 0.38);
    border-color: rgba(100, 140, 255, 0.6);
  }

  .btn-ghost {
    background: none;
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: rgba(255, 255, 255, 0.55);
  }

  .btn-ghost:not(:disabled):hover {
    border-color: rgba(255, 255, 255, 0.25);
    color: rgba(255, 255, 255, 0.8);
  }
</style>

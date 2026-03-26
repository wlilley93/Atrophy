<script lang="ts">
  import { api } from '../../api';

  interface RosterEntry {
    name: string;
    tier: number;
    role: string;
    reports_to: string | null;
    direct_reports: string[];
    can_address_user: boolean;
  }

  interface OrgManifest {
    name: string;
    slug: string;
    type: string;
    purpose: string;
    created: string;
    principal: string | null;
  }

  interface Props {
    orgSlug: string; // '__new_org__' for creation mode
    onDissolved: () => void;
    onSaved: () => void;
  }

  let { orgSlug, onDissolved, onSaved }: Props = $props();

  // View/edit state
  let manifest = $state<OrgManifest | null>(null);
  let roster = $state<RosterEntry[]>([]);
  let loading = $state(false);
  let error = $state('');
  let editing = $state(false);
  let saving = $state(false);
  let editName = $state('');
  let editPurpose = $state('');
  let dissolveConfirm = $state(false);
  let dissolving = $state(false);

  // Create mode state
  let createName = $state('');
  let createType = $state('government');
  let createPurpose = $state('');
  let createSlug = $state('');
  let creating = $state(false);
  let createError = $state('');

  const isCreateMode = $derived(orgSlug === '__new_org__');

  function slugify(name: string): string {
    return name
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .trim()
      .replace(/[\s]+/g, '-')
      .replace(/-+/g, '-');
  }

  $effect(() => {
    // Auto-generate slug from name in create mode
    createSlug = slugify(createName);
  });

  $effect(() => {
    if (!isCreateMode) {
      loadDetail();
    } else {
      manifest = null;
      roster = [];
      error = '';
      editing = false;
      dissolveConfirm = false;
    }
  });

  async function loadDetail() {
    if (!api) return;
    loading = true;
    error = '';
    try {
      const result = await api.getOrgDetail(orgSlug);
      manifest = result.manifest;
      roster = result.roster;
      editName = manifest.name;
      editPurpose = manifest.purpose || '';
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load organisation';
    } finally {
      loading = false;
    }
  }

  async function handleSave() {
    if (!api || !manifest) return;
    saving = true;
    try {
      await api.updateOrg(manifest.slug, { name: editName, purpose: editPurpose });
      manifest = { ...manifest, name: editName, purpose: editPurpose };
      editing = false;
      onSaved();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Save failed';
    } finally {
      saving = false;
    }
  }

  async function handleDissolve() {
    if (!api || !manifest) return;
    dissolving = true;
    try {
      await api.dissolveOrg(manifest.slug);
      onDissolved();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Dissolve failed';
      dissolving = false;
      dissolveConfirm = false;
    }
  }

  async function handleCreate() {
    if (!api) return;
    createError = '';
    if (!createName.trim()) { createError = 'Name is required'; return; }
    creating = true;
    try {
      await api.createOrg(createName.trim(), createType, createPurpose.trim());
      onSaved();
    } catch (e) {
      createError = e instanceof Error ? e.message : 'Create failed';
    } finally {
      creating = false;
    }
  }

  function groupByTier(list: RosterEntry[]): Map<number, RosterEntry[]> {
    const groups = new Map<number, RosterEntry[]>();
    for (const a of list) {
      const t = a.tier || 1;
      if (!groups.has(t)) groups.set(t, []);
      groups.get(t)!.push(a);
    }
    return new Map([...groups.entries()].sort((a, b) => a[0] - b[0]));
  }

  function tierLabel(tier: number): string {
    if (tier === 1) return 'Leadership';
    if (tier === 2) return 'Specialists';
    return `Tier ${tier}`;
  }

  function tierColor(tier: number): string {
    if (tier === 1) return 'rgba(100, 140, 255, 0.8)';
    if (tier === 2) return 'rgba(80, 200, 120, 0.8)';
    return 'rgba(180, 180, 180, 0.5)';
  }

  function typeBadgeClass(type: string): string {
    switch (type) {
      case 'government': return 'badge-government';
      case 'company': return 'badge-company';
      case 'creative': return 'badge-creative';
      case 'utility': return 'badge-utility';
      default: return 'badge-utility';
    }
  }

  const tierGroups = $derived(groupByTier(roster));

  const rosterStats = $derived(() => {
    const counts = new Map<number, number>();
    for (const a of roster) {
      const t = a.tier || 1;
      counts.set(t, (counts.get(t) || 0) + 1);
    }
    return counts;
  });
</script>

<div class="org-detail">
  {#if isCreateMode}
    <!-- ---- CREATE MODE ---- -->
    <div class="detail-header">
      <span class="detail-title">New Organisation</span>
    </div>

    <div class="form-body">
      <label class="field">
        <span class="field-label">Name</span>
        <input
          type="text"
          bind:value={createName}
          class="field-input"
          placeholder="e.g. Research Division"
          autofocus
        />
      </label>

      <div class="field">
        <span class="field-label">Slug</span>
        <span class="field-info mono">{createSlug || 'auto-generated'}</span>
      </div>

      <label class="field">
        <span class="field-label">Type</span>
        <select bind:value={createType} class="field-select">
          <option value="government">Government</option>
          <option value="company">Company</option>
          <option value="creative">Creative</option>
          <option value="utility">Utility</option>
        </select>
      </label>

      <label class="field column">
        <span class="field-label">Purpose</span>
        <textarea
          bind:value={createPurpose}
          class="field-textarea"
          rows="3"
          placeholder="Describe this organisation's purpose..."
        ></textarea>
      </label>

      {#if createError}
        <p class="form-error">{createError}</p>
      {/if}

      <div class="action-row">
        <button
          class="btn btn-primary"
          onclick={handleCreate}
          disabled={creating || !createName.trim()}
        >
          {creating ? 'Creating...' : 'Create'}
        </button>
      </div>
    </div>

  {:else if loading}
    <div class="loading-hint">Loading...</div>

  {:else if error && !manifest}
    <div class="error-hint">{error}</div>

  {:else if manifest}
    <!-- ---- VIEW / EDIT MODE ---- -->
    <div class="detail-header">
      {#if editing}
        <input
          type="text"
          bind:value={editName}
          class="field-input title-input"
          placeholder="Organisation name"
        />
      {:else}
        <span class="detail-title">{manifest.name}</span>
      {/if}
      <span class="type-badge {typeBadgeClass(manifest.type)}">{manifest.type}</span>
    </div>

    <div class="meta-row">
      <span class="meta-label">Slug</span>
      <span class="meta-value mono">{manifest.slug}</span>
    </div>

    {#if editing}
      <label class="field column">
        <span class="field-label">Purpose</span>
        <textarea
          bind:value={editPurpose}
          class="field-textarea"
          rows="3"
          placeholder="Describe this organisation's purpose..."
        ></textarea>
      </label>
    {:else if manifest.purpose}
      <p class="purpose-text">{manifest.purpose}</p>
    {/if}

    {#if error}
      <p class="form-error">{error}</p>
    {/if}

    <!-- Roster stats -->
    {#if roster.length > 0}
      <div class="roster-stats">
        {#each rosterStats() as [tier, count]}
          <span class="stat-pill" style="border-color: {tierColor(tier)}; color: {tierColor(tier)}">
            {tierLabel(tier)}: {count}
          </span>
        {/each}
        <span class="stat-total">{roster.length} total</span>
      </div>
    {/if}

    <!-- Agent roster grouped by tier -->
    {#if roster.length > 0}
      <div class="roster-section">
        <span class="section-label">Roster</span>
        {#each tierGroups as [tier, members]}
          <div class="tier-group">
            <span class="tier-heading" style="color: {tierColor(tier)}">{tierLabel(tier)}</span>
            {#each members as member}
              <div class="roster-row">
                <span class="roster-name">{member.name}</span>
                {#if member.role}
                  <span class="roster-role">{member.role}</span>
                {/if}
                {#if member.can_address_user}
                  <span class="roster-flag" title="Can address user">U</span>
                {/if}
              </div>
            {/each}
          </div>
        {/each}
      </div>
    {:else}
      <p class="empty-hint">No agents assigned</p>
    {/if}

    <!-- Actions -->
    {#if editing}
      <div class="action-row">
        <button
          class="btn btn-primary"
          onclick={handleSave}
          disabled={saving || !editName.trim()}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button
          class="btn btn-ghost"
          onclick={() => { editing = false; editName = manifest!.name; editPurpose = manifest!.purpose || ''; error = ''; }}
          disabled={saving}
        >
          Cancel
        </button>
      </div>
    {:else if dissolveConfirm}
      <div class="dissolve-confirm">
        <p class="dissolve-warning">Dissolve "{manifest.name}"? This cannot be undone. Agents will become standalone.</p>
        <div class="action-row">
          <button class="btn btn-danger" onclick={handleDissolve} disabled={dissolving}>
            {dissolving ? 'Dissolving...' : 'Confirm Dissolve'}
          </button>
          <button class="btn btn-ghost" onclick={() => dissolveConfirm = false} disabled={dissolving}>
            Cancel
          </button>
        </div>
      </div>
    {:else}
      <div class="action-row">
        <button class="btn btn-ghost" onclick={() => editing = true}>Edit</button>
        <button class="btn btn-danger-ghost" onclick={() => dissolveConfirm = true}>Dissolve</button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .org-detail {
    display: flex;
    flex-direction: column;
    gap: 12px;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
    color: var(--text-primary, rgba(255, 255, 255, 0.85));
  }

  /* Header */
  .detail-header {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .detail-title {
    font-size: 15px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.92);
    flex: 1;
    min-width: 0;
  }

  .title-input {
    flex: 1;
    min-width: 0;
    font-size: 14px;
    font-weight: 500;
  }

  /* Type badge */
  .type-badge {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 2px 8px;
    border-radius: 10px;
    flex-shrink: 0;
    border: 1px solid transparent;
  }

  .badge-government {
    background: rgba(100, 140, 255, 0.15);
    color: rgba(100, 140, 255, 0.9);
    border-color: rgba(100, 140, 255, 0.3);
  }

  .badge-company {
    background: rgba(80, 200, 120, 0.12);
    color: rgba(80, 200, 120, 0.9);
    border-color: rgba(80, 200, 120, 0.3);
  }

  .badge-creative {
    background: rgba(180, 100, 255, 0.12);
    color: rgba(180, 100, 255, 0.9);
    border-color: rgba(180, 100, 255, 0.3);
  }

  .badge-utility {
    background: rgba(160, 160, 160, 0.1);
    color: rgba(160, 160, 160, 0.7);
    border-color: rgba(160, 160, 160, 0.2);
  }

  /* Meta row */
  .meta-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .meta-label {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.35);
    text-transform: uppercase;
    letter-spacing: 0.4px;
    font-weight: 600;
    flex-shrink: 0;
  }

  .meta-value {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.5);
  }

  .mono {
    font-family: var(--font-mono, 'SF Mono', monospace);
    font-size: 11px;
  }

  /* Purpose */
  .purpose-text {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.55);
    line-height: 1.5;
    padding: 6px 0;
  }

  /* Roster stats */
  .roster-stats {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    padding: 6px 0 2px;
  }

  .stat-pill {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 8px;
    border: 1px solid;
    letter-spacing: 0.2px;
  }

  .stat-total {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.3);
    margin-left: 2px;
  }

  /* Roster section */
  .roster-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    padding-top: 10px;
  }

  .section-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: rgba(255, 255, 255, 0.35);
    margin-bottom: 2px;
  }

  .tier-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .tier-heading {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    padding: 2px 0 3px;
  }

  .roster-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 6px;
    border-radius: 4px;
    cursor: default;
    transition: background 0.1s;
  }

  .roster-row:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .roster-name {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.75);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .roster-role {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.3);
    background: rgba(255, 255, 255, 0.05);
    border-radius: 3px;
    padding: 1px 5px;
    flex-shrink: 0;
  }

  .roster-flag {
    font-size: 9px;
    font-weight: 700;
    color: rgba(100, 140, 255, 0.6);
    flex-shrink: 0;
    width: 14px;
    text-align: center;
  }

  /* Field styles (matching SettingsTab) */
  .field {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 28px;
  }

  .field.column {
    flex-direction: column;
    align-items: stretch;
    gap: 5px;
  }

  .field-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    color: rgba(255, 255, 255, 0.4);
    flex-shrink: 0;
    min-width: 72px;
  }

  .field-info {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.45);
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

  .field-textarea {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.85);
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
    font-size: 12px;
    padding: 7px 9px;
    resize: vertical;
    line-height: 1.5;
    -webkit-app-region: no-drag;
    transition: border-color 0.15s;
  }

  .field-textarea:focus {
    outline: none;
    border-color: rgba(100, 140, 255, 0.5);
  }

  /* Dissolve confirmation */
  .dissolve-confirm {
    display: flex;
    flex-direction: column;
    gap: 10px;
    background: rgba(220, 60, 60, 0.06);
    border: 1px solid rgba(220, 60, 60, 0.2);
    border-radius: 6px;
    padding: 10px 12px;
  }

  .dissolve-warning {
    font-size: 12px;
    color: rgba(220, 100, 100, 0.85);
    line-height: 1.4;
  }

  /* Action row */
  .action-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 4px;
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

  .btn-danger {
    background: rgba(220, 60, 60, 0.2);
    border: 1px solid rgba(220, 60, 60, 0.4);
    color: rgba(255, 120, 120, 0.95);
  }

  .btn-danger:not(:disabled):hover {
    background: rgba(220, 60, 60, 0.32);
    border-color: rgba(220, 60, 60, 0.6);
  }

  .btn-danger-ghost {
    background: none;
    border: 1px solid rgba(220, 60, 60, 0.2);
    color: rgba(220, 100, 100, 0.7);
  }

  .btn-danger-ghost:not(:disabled):hover {
    background: rgba(220, 60, 60, 0.08);
    border-color: rgba(220, 60, 60, 0.4);
    color: rgba(255, 120, 120, 0.9);
  }

  /* Form body */
  .form-body {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  /* Error */
  .form-error {
    font-size: 11px;
    color: rgba(255, 100, 100, 0.85);
    padding: 4px 0;
  }

  /* Loading / empty hints */
  .loading-hint,
  .error-hint,
  .empty-hint {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.3);
    padding: 8px 0;
    text-align: center;
  }

  .error-hint {
    color: rgba(255, 100, 100, 0.7);
  }
</style>

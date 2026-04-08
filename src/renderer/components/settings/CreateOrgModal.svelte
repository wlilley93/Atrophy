<script lang="ts">
  /**
   * CreateOrgModal - flow for spinning up a new organisation.
   *
   * Three fields: name, type, purpose. Slug is auto-derived from the name.
   * On success, calls onCreated with the new org's slug so the parent can
   * focus the canvas on it.
   */
  import { api } from '../../api';

  interface Props {
    onCreated: (slug: string) => void;
    onCancel: () => void;
  }

  let { onCreated, onCancel }: Props = $props();

  let name = $state('');
  let type = $state('working_group');
  let purpose = $state('');

  let creating = $state(false);
  let errorMsg = $state('');

  const slug = $derived(
    name
      .toLowerCase()
      .replace(/[\s-]+/g, '_')
      .replace(/[^a-z0-9_]/g, '')
      .replace(/_+/g, '_'),
  );

  const ORG_TYPES = [
    { value: 'working_group', label: 'Working Group', desc: 'Loose collaboration with no rigid hierarchy' },
    { value: 'team', label: 'Team', desc: 'Structured group with leadership and specialists' },
    { value: 'department', label: 'Department', desc: 'Functional unit (e.g. defence, research)' },
    { value: 'cabinet', label: 'Cabinet', desc: 'Top-tier advisors reporting directly to the principal' },
    { value: 'institute', label: 'Institute', desc: 'Long-running research organisation with sub-teams' },
  ];

  async function handleCreate() {
    errorMsg = '';
    if (!name.trim()) {
      errorMsg = 'Name is required';
      return;
    }
    if (!slug) {
      errorMsg = 'Name must contain at least one letter or digit';
      return;
    }
    if (!api) return;
    creating = true;
    try {
      const result = await api.createOrg(name.trim(), type, purpose.trim());
      onCreated(result.slug);
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

<div class="modal" role="dialog" aria-modal="true" aria-labelledby="create-org-title">
  <header class="modal-header">
    <h2 id="create-org-title">New organisation</h2>
    <button class="close-btn" onclick={onCancel} aria-label="Cancel">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <line x1="6" y1="6" x2="18" y2="18"/>
        <line x1="6" y1="18" x2="18" y2="6"/>
      </svg>
    </button>
  </header>

  <div class="modal-body">
    <div class="field">
      <label for="org-name" class="field-label">Name</label>
      <input
        id="org-name"
        type="text"
        class="text-input"
        bind:value={name}
        placeholder="e.g. Defence, Research, Trading Desk"
      />
      {#if slug}
        <span class="field-hint">slug: <code>{slug}</code></span>
      {/if}
    </div>

    <div class="field">
      <label for="org-purpose" class="field-label">Purpose</label>
      <textarea
        id="org-purpose"
        class="text-input"
        rows="2"
        bind:value={purpose}
        placeholder="What is this organisation for? One or two lines."
      ></textarea>
    </div>

    <div class="field">
      <span class="field-label">Type</span>
      <div class="type-grid">
        {#each ORG_TYPES as t}
          <button
            class="type-card"
            class:selected={type === t.value}
            onclick={() => type = t.value}
            type="button"
          >
            <span class="type-name">{t.label}</span>
            <span class="type-desc">{t.desc}</span>
          </button>
        {/each}
      </div>
    </div>

    {#if errorMsg}
      <div class="error">{errorMsg}</div>
    {/if}
  </div>

  <footer class="modal-footer">
    <button class="btn btn-ghost" onclick={onCancel} disabled={creating}>Cancel</button>
    <button class="btn btn-primary" onclick={handleCreate} disabled={creating || !name.trim()}>
      {creating ? 'Creating...' : 'Create organisation'}
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
    width: min(560px, calc(100% - 48px));
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
    color: rgba(255, 255, 255, 0.95);
    font-size: 15px;
    font-weight: 600;
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
    gap: 18px;
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
    resize: vertical;
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

  .type-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .type-card {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
    text-align: left;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    cursor: pointer;
    color: inherit;
    font-family: inherit;
    transition: background 0.15s, border-color 0.15s;
  }

  .type-card:hover {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.16);
  }

  .type-card.selected {
    background: rgba(120, 160, 255, 0.1);
    border-color: rgba(120, 160, 255, 0.5);
  }

  .type-name {
    color: rgba(255, 255, 255, 0.92);
    font-size: 12px;
    font-weight: 600;
  }

  .type-desc {
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    line-height: 1.4;
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

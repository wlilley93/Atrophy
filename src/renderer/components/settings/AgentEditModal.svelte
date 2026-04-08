<script lang="ts">
  /**
   * AgentEditModal - thin modal frame around the existing AgentDetail
   * editor. Triggered from clicking a node in the OrgChart or sidebar.
   * Closing the modal preserves the current selection in the parent.
   */
  import AgentDetail from './AgentDetail.svelte';

  interface Props {
    agentName: string;
    schedule: unknown[];
    onClose: () => void;
    onChanged: () => void;
  }

  let { agentName, schedule, onClose, onChanged }: Props = $props();

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }

  function handleSaved() {
    onChanged();
  }

  function handleDeleted() {
    onChanged();
    onClose();
  }
</script>

<svelte:window onkeydown={handleKeydown}/>

<div class="modal-backdrop" onclick={onClose} role="presentation"></div>

<div class="modal" role="dialog" aria-modal="true" aria-labelledby="edit-agent-title">
  <header class="modal-header">
    <h2 id="edit-agent-title">{agentName}</h2>
    <button class="close-btn" onclick={onClose} aria-label="Close">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <line x1="6" y1="6" x2="18" y2="18"/>
        <line x1="6" y1="18" x2="18" y2="6"/>
      </svg>
    </button>
  </header>

  <div class="modal-body">
    <AgentDetail
      {agentName}
      {schedule}
      onSaved={handleSaved}
      onDeleted={handleDeleted}
    />
  </div>
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
    width: min(960px, calc(100% - 48px));
    height: min(820px, calc(100vh - 80px));
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
    padding: 16px 22px 12px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    flex-shrink: 0;
  }

  .modal-header h2 {
    margin: 0;
    color: rgba(255, 255, 255, 0.95);
    font-size: 14px;
    font-weight: 600;
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
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
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 16px 22px 22px;
  }

  .modal-body::-webkit-scrollbar {
    width: 6px;
  }

  .modal-body::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
  }
</style>

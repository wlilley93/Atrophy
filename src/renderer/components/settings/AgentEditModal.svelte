<script lang="ts">
  /**
   * AgentEditModal - playing-card style modal around the existing
   * AgentDetail editor.
   *
   * The header is the visual centrepiece: a large card with a circular
   * avatar, the agent's display name, role, and tier badge. Avatar falls
   * back to a generic user silhouette SVG if no image asset is found
   * for that agent yet.
   */
  import { onMount } from 'svelte';
  import { api } from '../../api';
  import AgentDetail from './AgentDetail.svelte';

  interface Props {
    agentName: string;
    schedule: unknown[];
    onClose: () => void;
    onChanged: () => void;
  }

  let { agentName, schedule, onClose, onChanged }: Props = $props();

  let avatarUrl = $state<string | null>(null);
  let displayName = $state(agentName);
  let role = $state('');
  let tier = $state<number | null>(null);
  let orgSlug = $state<string | null>(null);
  let loaded = $state(false);

  async function loadHeader() {
    if (!api) return;
    try {
      const [still, manifest] = await Promise.all([
        api.getAgentAvatarStill(agentName),
        api.getAgentManifest(agentName),
      ]);
      avatarUrl = still;
      if (manifest) {
        displayName = (manifest.display_name as string) || agentName;
        role = (manifest.role as string) || '';
        const orgCfg = (manifest.org as Record<string, unknown> | undefined) ?? {};
        tier = (orgCfg.tier as number) ?? null;
        orgSlug = (orgCfg.slug as string) ?? null;
      }
    } catch (err) {
      console.warn('AgentEditModal header load failed:', err);
    } finally {
      loaded = true;
    }
  }

  onMount(loadHeader);

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }

  function handleSaved() {
    onChanged();
    // Re-fetch header in case display name or role changed
    loadHeader();
  }

  function handleDeleted() {
    onChanged();
    onClose();
  }

  function tierLabel(t: number | null): string {
    if (t === 0) return 'Principal';
    if (t === 1) return 'Leadership';
    if (t === 2) return 'Specialist';
    if (t === 3) return 'Worker';
    if (t == null) return 'Standalone';
    return `Tier ${t}`;
  }

  function tierColor(t: number | null): string {
    if (t === 0) return 'rgba(255, 200, 100, 0.85)';
    if (t === 1) return 'rgba(120, 160, 255, 0.85)';
    if (t === 2) return 'rgba(100, 220, 140, 0.85)';
    if (t === 3) return 'rgba(220, 160, 100, 0.85)';
    return 'rgba(180, 180, 200, 0.7)';
  }
</script>

<svelte:window onkeydown={handleKeydown}/>

<div class="modal-backdrop" onclick={onClose} role="presentation"></div>

<div class="modal" role="dialog" aria-modal="true" aria-labelledby="edit-agent-title">
  <!-- Card-style header with avatar -->
  <header class="card-header">
    <div class="avatar-wrap" style="--tier-accent: {tierColor(tier)}">
      {#if avatarUrl}
        <img class="avatar-img" src={avatarUrl} alt="{displayName} avatar"/>
      {:else}
        <!-- Generic user silhouette fallback -->
        <svg class="avatar-fallback" viewBox="0 0 64 64" fill="none" aria-hidden="true">
          <circle cx="32" cy="22" r="11" fill="rgba(255,255,255,0.15)"/>
          <path d="M10 56 C 10 42, 22 36, 32 36 C 42 36, 54 42, 54 56 Z"
                fill="rgba(255,255,255,0.15)"/>
        </svg>
      {/if}
    </div>
    <div class="header-text">
      <h2 id="edit-agent-title">{displayName}</h2>
      {#if role}
        <p class="header-role">{role}</p>
      {/if}
      <div class="header-meta">
        <span class="tier-pill" style="--tier-accent: {tierColor(tier)}">{tierLabel(tier)}</span>
        {#if orgSlug}
          <span class="org-pill">{orgSlug}</span>
        {/if}
        <span class="name-pill">{agentName}</span>
      </div>
    </div>
    <button class="close-btn" onclick={onClose} aria-label="Close">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <line x1="6" y1="6" x2="18" y2="18"/>
        <line x1="6" y1="18" x2="18" y2="6"/>
      </svg>
    </button>
  </header>

  <!-- The actual editor (existing AgentDetail component) -->
  <div class="modal-body">
    {#if loaded}
      <AgentDetail
        {agentName}
        {schedule}
        onSaved={handleSaved}
        onDeleted={handleDeleted}
      />
    {/if}
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
    width: min(1040px, calc(100% - 48px));
    height: min(820px, calc(100vh - 60px));
    background: rgba(28, 28, 32, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.7);
    z-index: 101;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  /* Card-style header */
  .card-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 22px 26px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    background:
      radial-gradient(ellipse 800px 200px at 20% 0%,
        rgba(120, 160, 255, 0.06),
        transparent 60%),
      linear-gradient(180deg,
        rgba(255, 255, 255, 0.025),
        transparent);
    flex-shrink: 0;
  }

  .avatar-wrap {
    --tier-accent: rgba(120, 160, 255, 0.85);
    width: 76px;
    height: 76px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.04);
    border: 2px solid var(--tier-accent);
    box-shadow: 0 0 24px color-mix(in srgb, var(--tier-accent) 25%, transparent);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    user-select: none;
    -webkit-user-drag: none;
  }

  .avatar-fallback {
    width: 60%;
    height: 60%;
  }

  .header-text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .header-text h2 {
    margin: 0;
    color: rgba(255, 255, 255, 0.95);
    font-size: 22px;
    font-weight: 600;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-role {
    margin: 0;
    color: rgba(255, 255, 255, 0.55);
    font-size: 13px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
    flex-wrap: wrap;
  }

  .tier-pill {
    --tier-accent: rgba(120, 160, 255, 0.85);
    padding: 2px 9px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    background: color-mix(in srgb, var(--tier-accent) 12%, transparent);
    color: var(--tier-accent);
    border: 1px solid color-mix(in srgb, var(--tier-accent) 35%, transparent);
  }

  .org-pill,
  .name-pill {
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.4px;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .name-pill {
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
    font-weight: 500;
  }

  .close-btn {
    position: absolute;
    top: 14px;
    right: 14px;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.55);
    cursor: pointer;
    padding: 6px;
    border-radius: 6px;
    transition: color 0.15s, background 0.15s, border-color 0.15s;
    display: inline-flex;
  }

  .close-btn:hover {
    color: rgba(255, 255, 255, 0.95);
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.18);
  }

  /* Body */
  .modal-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 18px 26px 26px;
  }

  .modal-body::-webkit-scrollbar {
    width: 6px;
  }

  .modal-body::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
  }
</style>

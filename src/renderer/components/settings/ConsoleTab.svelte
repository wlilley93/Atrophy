<script lang="ts">
  import { api } from '../../api';

  interface LogEntry { timestamp: number; level: string; tag: string; message: string }
  let logEntries = $state<LogEntry[]>([]);
  let logFilter = $state('');
  let logAutoScroll = $state(true);
  let logCleanup: (() => void) | null = null;

  export async function load() {
    const buffer = await api?.getLogBuffer();
    if (buffer) logEntries = buffer;
    scrollConsole();
    // Subscribe to live entries
    if (logCleanup) logCleanup();
    logCleanup = api?.onLogEntry((entry) => {
      logEntries = [...logEntries, entry];
      if (logEntries.length > 500) logEntries = logEntries.slice(-500);
      scrollConsole();
    }) || null;
  }

  export function cleanup() {
    if (logCleanup) {
      logCleanup();
      logCleanup = null;
    }
  }

  function scrollConsole() {
    if (!logAutoScroll) return;
    requestAnimationFrame(() => {
      const el = document.getElementById('console-scroll');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
</script>

<div class="console-wrap">
<div class="console-controls">
  <input
    type="text"
    class="console-filter"
    placeholder="Filter (tag or text)..."
    bind:value={logFilter}
  />
  <label class="console-autoscroll">
    <input type="checkbox" bind:checked={logAutoScroll} />
    Auto-scroll
  </label>
  <button class="daemon-btn" onclick={() => { logEntries = []; }}>Clear</button>
</div>
<div
  class="console-output"
  id="console-scroll"
>
  {#each logEntries.filter(e => !logFilter || e.tag.includes(logFilter) || e.message.toLowerCase().includes(logFilter.toLowerCase())) as entry}
    <div class="console-line level-{entry.level}">
      <span class="console-time">{new Date(entry.timestamp).toLocaleTimeString('en-GB', { hour12: false })}</span>
      <span class="console-level">{entry.level.slice(0, 4).toUpperCase()}</span>
      <span class="console-tag">[{entry.tag}]</span>
      <span class="console-msg">{entry.message}</span>
    </div>
  {/each}
</div>
</div><!-- end console-wrap -->

<style>
  .console-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .console-controls {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 0 8px;
  }
  .console-filter {
    flex: 1;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 4px 8px;
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .console-autoscroll {
    font-size: 11px;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }
  .console-output {
    flex: 1;
    overflow-y: auto;
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 8px;
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 1.5;
    min-height: 300px;
  }
  .console-line {
    white-space: pre-wrap;
    word-break: break-all;
  }
  .console-time {
    color: var(--text-dim);
    margin-right: 6px;
  }
  .console-level {
    margin-right: 4px;
    font-weight: 600;
    min-width: 36px;
    display: inline-block;
  }
  .console-tag {
    color: var(--text-secondary);
    margin-right: 4px;
  }
  .console-msg {
    color: var(--text-primary);
  }
  .level-debug .console-level { color: var(--text-dim); }
  .level-info .console-level { color: #5ce0d6; }
  .level-warn .console-level { color: #f0c060; }
  .level-error .console-level { color: #ff6b6b; }
  .level-error .console-msg { color: #ff6b6b; }

  .daemon-btn {
    padding: 4px 14px;
    font-size: 11px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    transition: background 0.15s;
  }

  .daemon-btn:hover {
    background: rgba(255, 255, 255, 0.14);
  }
</style>

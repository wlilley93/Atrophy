<script lang="ts">
  import { api } from '../../api';

  interface LogEntry { timestamp: number; level: string; tag: string; message: string }
  let logEntries = $state<LogEntry[]>([]);
  let logFilter = $state('');
  let logAutoScroll = $state(true);
  let logCleanup: (() => void) | null = null;
  let consoleScrollEl: HTMLDivElement;

  // Source toggle: 'live' = ring buffer + streaming, 'file' = current log file, 'prev' = previous boot
  let logSource = $state<'live' | 'file' | 'prev'>('live');
  let fileEntries = $state<LogEntry[]>([]);
  let loadingFile = $state(false);

  export async function load() {
    await loadLive();
  }

  async function loadLive() {
    logSource = 'live';
    fileEntries = [];
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

  async function loadFromFile(which: 'file' | 'prev') {
    logSource = which;
    loadingFile = true;
    // Pause live streaming while viewing file
    if (logCleanup) { logCleanup(); logCleanup = null; }
    const mySource = which; // capture before awaits to detect superseded calls
    try {
      const contents = which === 'file'
        ? await api?.readLogFile()
        : await api?.readPrevLogFile();
      if (logSource !== mySource) return; // superseded by another tab click
      if (contents) {
        const parsed = await api?.parseLogFile(contents);
        if (logSource !== mySource) return; // superseded
        fileEntries = parsed || [];
      } else {
        fileEntries = [];
      }
    } catch {
      if (logSource !== mySource) return;
      fileEntries = [];
    }
    loadingFile = false;
    scrollConsole();
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
      if (consoleScrollEl) consoleScrollEl.scrollTop = consoleScrollEl.scrollHeight;
    });
  }

  let displayEntries = $derived(logSource === 'live' ? logEntries : fileEntries);
  let filteredEntries = $derived(
    displayEntries.filter(e =>
      !logFilter
      || e.tag.includes(logFilter)
      || e.message.toLowerCase().includes(logFilter.toLowerCase())
    )
  );
</script>

<div class="console-wrap">
<div class="console-controls">
  <div class="source-tabs">
    <button
      class="source-tab"
      class:active={logSource === 'live'}
      onclick={() => loadLive()}
    >Live</button>
    <button
      class="source-tab"
      class:active={logSource === 'file'}
      onclick={() => loadFromFile('file')}
    >Log file</button>
    <button
      class="source-tab"
      class:active={logSource === 'prev'}
      onclick={() => loadFromFile('prev')}
    >Prev boot</button>
  </div>
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
  <button class="daemon-btn" onclick={() => { logEntries = []; fileEntries = []; }}>Clear</button>
</div>
<div
  class="console-output"
  bind:this={consoleScrollEl}
>
  {#if loadingFile}
    <div class="console-line level-info">
      <span class="console-msg">Loading log file...</span>
    </div>
  {:else if filteredEntries.length === 0}
    <div class="console-line level-info">
      <span class="console-msg">{logSource === 'prev' ? 'No previous boot log found.' : 'No log entries.'}</span>
    </div>
  {:else}
    {#each filteredEntries as entry}
      <div class="console-line level-{entry.level}">
        <span class="console-time">{new Date(entry.timestamp).toLocaleTimeString('en-GB', { hour12: false })}</span>
        <span class="console-level">{entry.level.slice(0, 4).toUpperCase()}</span>
        <span class="console-tag">[{entry.tag}]</span>
        <span class="console-msg">{entry.message}</span>
      </div>
    {/each}
  {/if}
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
    flex-wrap: wrap;
  }

  .source-tabs {
    display: flex;
    gap: 2px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 5px;
    padding: 2px;
  }
  .source-tab {
    padding: 3px 10px;
    font-size: 10px;
    background: transparent;
    border: none;
    border-radius: 3px;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }
  .source-tab:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.06);
  }
  .source-tab.active {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.1);
  }

  .console-filter {
    flex: 1;
    min-width: 100px;
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

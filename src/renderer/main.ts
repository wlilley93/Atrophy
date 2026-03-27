import './styles/global.css';
import { api } from './api';

// ---------------------------------------------------------------------------
// Early error capture - catches errors before and during Svelte mount.
// Forwards to the main process log file via the preload bridge so they
// survive crashes and appear in the Console tab.
// ---------------------------------------------------------------------------

function rlog(level: string, msg: string): void {
  try { api?.log(level, 'renderer:boot', msg); } catch { /* preload may not be ready */ }
  if (level === 'error') console.error(`[renderer:boot] ${msg}`);
  else console.log(`[renderer:boot] ${msg}`);
}

window.addEventListener('error', (event) => {
  rlog('error', `uncaught: ${event.message} at ${event.filename}:${event.lineno}:${event.colno}`);
});

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason instanceof Error
    ? `${event.reason.message}\n${event.reason.stack}`
    : String(event.reason);
  rlog('error', `unhandledRejection: ${reason}`);
});

// ---------------------------------------------------------------------------
// Svelte mount
// ---------------------------------------------------------------------------

rlog('info', 'renderer entry loaded, mounting Svelte app');

import App from './App.svelte';
import { mount } from 'svelte';

let app: ReturnType<typeof mount> | undefined;
try {
  app = mount(App, {
    target: document.getElementById('app')!,
  });
  rlog('info', 'Svelte app mounted');
} catch (err) {
  rlog('error', `Svelte mount failed: ${err instanceof Error ? err.message : String(err)}`);
  throw err;
}

export default app;

<script lang="ts">
  import Window from './components/Window.svelte';
  import { agents } from './stores/agents.svelte';
  import { settings } from './stores/settings.svelte';
  import { session } from './stores/session.svelte';

  import { api } from './api';

  // Load initial config from main process
  async function init() {
    if (!api) return;

    const cfg = await api.getConfig();
    settings.userName = cfg.userName || 'User';
    settings.version = cfg.version || '0.0.0';
    settings.avatarEnabled = cfg.avatarEnabled || false;
    settings.ttsBackend = cfg.ttsBackend || 'elevenlabs';
    settings.inputMode = cfg.inputMode || 'dual';
    settings.loaded = true;

    agents.current = cfg.agentName || 'xan';
    agents.displayName = cfg.agentDisplayName || 'Xan';

    const agentList = await api.getAgents();
    agents.list = agentList;

    session.phase = 'boot';
  }

  init();
</script>

<Window />

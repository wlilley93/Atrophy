<script lang="ts">
  /**
   * SystemTab - Settings > System tab.
   *
   * Renders the hub-and-spoke SystemMap inline (not as an overlay).
   * The same topology visualization is also accessible standalone via
   * Cmd+Shift+M from the main window.
   */
  import SystemMap from '../SystemMap.svelte';

  export async function load() {
    // SystemMap handles its own data fetching on mount.
    // This method exists so Settings.svelte can call it uniformly.
  }
</script>

<div class="system-tab">
  <SystemMap onClose={() => {}} inline />
</div>

<style>
  .system-tab {
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }
</style>

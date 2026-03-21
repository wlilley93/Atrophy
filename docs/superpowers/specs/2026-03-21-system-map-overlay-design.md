# System Map Overlay - Design Spec

**Date:** 2026-03-21
**Status:** Approved design, pending implementation plan
**Review:** Passed spec review (10 issues found, all addressed below)

## Summary

A standalone overlay (`SystemMap.svelte`) that visualizes all agent-to-service connections in a three-column layout: Agents (left), Switchboard rail (center), Services (right). Connections are editable - click pills to toggle, Cmd+click for detail panels. Agents can also modify their own wiring (or other agents' wiring, if they have system access) via conversation using existing MCP tools.

## Requirements

- **Debugging/monitoring:** quickly see what's wired where
- **Active configuration:** primary way to manage agent capabilities
- **Onboarding:** understand the system architecture at a glance
- **Agent self-service:** agents can modify MCP config on user request via existing memory server tools

## Architecture

### Component

`src/renderer/components/SystemMap.svelte` - standalone overlay, same pattern as Artefact/Canvas.

Triggered by `Cmd+Shift+M` keyboard shortcut and/or an icon button in window chrome. Toggle in `Window.svelte` via `showSystemMap` state variable.

### Data flow

- On open: fetches topology via single IPC call
- Mutations: write to agent manifest on disk immediately, rebuild MCP config, flag dirty
- No Apply/Save split - changes are live to disk, but need agent session restart to take effect
- No new stores needed - component holds local state, fetched on open

### New IPC handlers (in `ipc-handlers.ts`)

Two handlers (not three - server status is folded into topology):

```typescript
// Returns full topology: agents with connections, all known servers, channel/cron state
ipcMain.handle('system:getTopology', async () => {
  const agentInfos = discoverAgents(); // returns AgentInfo[] (name, display_name, description, role)

  // Read full manifests for channels/jobs (AgentInfo doesn't include these)
  const agents = agentInfos.map(info => {
    const manifest = readAgentManifest(info.name); // reads agent.json from disk
    const mcpSection = getAgentMcpSection(info.name);
    return {
      name: info.name,
      displayName: info.display_name || info.name,
      role: info.role || '',
      mcp: {
        // Explicit include list from manifest (empty means "all")
        include: mcpSection.include,
        exclude: mcpSection.exclude,
        // Which servers are actually resolved for this agent
        active: mcpRegistry.getForAgent(info.name).map(s => s.name),
      },
      channels: (manifest.channels || {}) as Record<string, unknown>,
      jobs: (manifest.jobs || {}) as Record<string, unknown>,
      router: (manifest.router || {}) as Record<string, unknown>,
    };
  });

  // All known servers (both available and unavailable external)
  // discover() only registers available servers, so we also check EXTERNAL_SERVER_META
  // for servers that couldn't be resolved (tool missing, key missing)
  const registeredServers = mcpRegistry.getRegistry();
  const allServers = registeredServers.map(s => ({
    name: s.name,
    description: s.description,
    capabilities: s.capabilities,
    bundled: s.bundled,
    available: true,
    missingKey: false,
  }));

  // Add unavailable external servers that discover() skipped
  for (const [name, meta] of Object.entries(EXTERNAL_SERVER_META)) {
    if (!registeredServers.some(s => s.name === name)) {
      allServers.push({
        name,
        description: meta.description,
        capabilities: meta.capabilities,
        bundled: true,
        available: false, // command not found
        missingKey: !!(meta.requiresEnvKey && !process.env[meta.requiresEnvKey]),
      });
    }
  }

  return { agents, servers: allServers };
});

// Toggle a connection: updates agent manifest mcp.include + rebuilds config
ipcMain.handle('system:toggleConnection', async (_, agentName, serverName, enabled) => {
  // Validate inputs
  if (!isValidAgentName(agentName)) {
    return { success: false, error: `Invalid agent: ${agentName}` };
  }
  if (!mcpRegistry.getServer(serverName) && enabled) {
    return { success: false, error: `Unknown server: ${serverName}` };
  }

  // If the agent has an empty include list (meaning "all"), populate it
  // explicitly before toggling. Otherwise deactivation uses exclude-from-all
  // which is confusing in the UI.
  const mcpSection = getAgentMcpSection(agentName);
  if (mcpSection.include.length === 0) {
    const currentActive = mcpRegistry.getForAgent(agentName).map(s => s.name);
    mcpSection.include = currentActive;
    saveAgentConfig(agentName, { mcp: mcpSection });
  }

  if (enabled) {
    mcpRegistry.activateForAgent(agentName, serverName);
  } else {
    mcpRegistry.deactivateForAgent(agentName, serverName);
  }

  // Rebuild the config.json that Claude CLI reads
  mcpRegistry.buildConfigForAgent(agentName);

  return {
    success: true,
    needsRestart: mcpRegistry.needsRestart(agentName),
    // Return updated active list for immediate UI update
    active: mcpRegistry.getForAgent(agentName).map(s => s.name),
  };
});
```

**Key decisions from review:**
- `readAgentManifest()` and `getAgentMcpSection()` are used directly (already exist in mcp-registry.ts) rather than relying on `AgentInfo` which lacks channels/jobs fields
- `EXTERNAL_SERVER_META` is checked separately for unavailable servers that `discover()` dropped
- `toggleConnection` pre-populates empty include lists to avoid "default all" semantics confusion
- `buildConfigForAgent()` is called after toggle so the disk config reflects the change
- Error returns include `success: false` with error message instead of silent void

### Preload API additions

```typescript
getTopology: () => ipcRenderer.invoke('system:getTopology'),
toggleConnection: (agent: string, server: string, enabled: boolean) =>
  ipcRenderer.invoke('system:toggleConnection', agent, server, enabled),
```

### Exposing EXTERNAL_SERVER_META

`EXTERNAL_SERVER_META` is currently a module-level const in `mcp-registry.ts`. The topology handler needs access to it for unavailable server detection. Export it, or add a `getExternalServerMeta()` method to `McpRegistry`.

## Visual Design

### Layout

Three columns filling the overlay. Dark background `#0C0C0E` with blur backdrop matching Settings overlay. The overlay uses full window width (622px).

| Column | Width | Content |
|--------|-------|---------|
| Agents | ~200px fixed | Agent cards, vertically stacked |
| Switchboard | 48px fixed | Thin vertical rail with icon, decorative |
| Services | flex: 1 (remaining ~374px) | Per-agent service sections, scrollable |

**Note:** Fixed pixel widths for left and center columns avoid the problem of percentage-based layout making the 8% center column illegibly narrow at 622px. The switchboard rail at 48px has room for a small icon (the Atrophy logo or a network icon) but no text.

### Agent cards (left column)

Compact cards with:
- Agent display name (bold, `--text-primary`)
- Status dot: green (idle), amber (active inference), red (error)
- Blue border accent on selected agent (`--accent`)
- Click to scroll right column to that agent's service section

### Switchboard rail (center)

48px wide. Thin vertical gradient line centered. Small Atrophy icon at top. Non-interactive - visual connective tissue showing all traffic routes through the switchboard.

### Service sections (right column)

One section per agent, each containing three collapsible groups:

**MCP group:**
- Header: "MCP (8)" with count badge
- Pills in flex-wrap grid
- If 10+ servers, defaults to collapsed (shows count only)

**Channels group:**
- Header: "Channels"
- Pills for telegram, desktop

**Cron group:**
- Header: "Cron (9)" with count badge
- Pills for each job
- Defaults to collapsed (shows count only)

### Service pills

Pill-shaped badges (`border-radius: 12px`, `padding: 4px 12px`):

| State | Style |
|-------|-------|
| Active | Solid background, white text. Blue (MCP), green (channel), amber (cron) |
| Available but inactive | Dotted border, dim text, same color at 0.1 opacity |
| Unavailable (tool missing) | Dim text, warning icon, tooltip explains why |
| Key missing | Key icon with red dot |

Colors:
- MCP: `rgba(100, 140, 255, 0.3)` / hover `0.5`
- Channels: `rgba(120, 200, 120, 0.3)` / hover `0.5`
- Cron: `rgba(255, 180, 80, 0.3)` / hover `0.5`

### Connection bars

CSS-only horizontal bars from agent card through switchboard to service section. Implemented as `::before`/`::after` pseudo-elements on the service section container. No SVG, no arrow rendering.

- Active: solid bar with subtle glow (`box-shadow`)
- Color matches service type
- Disappears when section has no active connections

### Interactions

| Action | Result |
|--------|--------|
| Click pill | Toggle connection on/off (150ms fade transition) |
| Click agent card | Scroll to + highlight agent's service section |
| Click group header | Expand/collapse group |
| Cmd+click pill | Open inline detail card below pill |
| Escape | Close overlay |
| `1`-`n` keys | Jump to agent by index (disabled when search input focused) |
| `/` key | Focus search filter |

### Inline detail card

Expands below the pill on Cmd+click. Matches Settings section style. Content varies by type:

**MCP server detail:**
- Description
- Type (bundled/external) and command
- Status (available/unavailable)
- Tool count
- Capabilities list
- Required env var + status (set/missing)
- "Used by" agent list

**Channel detail:**
- Enabled/disabled
- Bot token status (set/missing, never shows value)
- Chat ID
- Daemon status (polling/stopped)

**Cron detail:**
- Schedule (cron expression + human-readable)
- Script path
- Last run time + result (OK/FAIL)
- Output routing target

### Search/filter

Small search input top-right of overlay. Typing filters pills by name across all agents. Matching pills highlight, non-matching dim to 0.15 opacity. Clear on Escape or X button. While the search input is focused, numeric jump shortcuts are disabled to avoid intercepting search input.

### Restart banner

Sticky banner at bottom when connections have been toggled:

```
"2 changes pending - restart Xan and Companion to apply"
[Restart Xan] [Restart Companion] [Restart All]
```

Calls existing session restart flow. Banner dismisses when all affected agents are restarted or overlay closes.

**Note:** The restart banner only tracks changes made through the overlay UI. If an agent modifies its own config via the MCP self-service tools in a separate inference session, the change is on disk but the banner won't show it. The system map will reflect the updated config on next open.

## Agent Self-Service

### Existing MCP tools (already in `memory_server.py`)

The memory server already has MCP management tools under the `mcp` action group (lines 2894-2990):

- `list_servers` - lists available MCP servers and which are active for the calling agent
- `activate_server` - activates a server for the calling agent, updates manifest
- `deactivate_server` - deactivates a server for the calling agent, updates manifest

**No new tools needed.** The spec leverages existing infrastructure.

### Cross-agent wiring (new)

Agents with `system_access: true` in their router config (currently only Xan) can modify other agents' MCP configs. This extends the existing tools with an optional `agent` parameter:

```python
# Xan calling activate_server for another agent:
activate_server({ server_name: "google", agent: "general_montgomery" })
```

If the `agent` parameter is omitted, the tool operates on the calling agent (existing behavior). If provided, the tool checks that the calling agent has `system_access: true` before proceeding. Non-system agents attempting cross-agent modification get an error response.

### Interaction flows

**Self-service:**
1. User to Companion: "Can you use Google Calendar?"
2. Companion calls `list_servers` - sees google is available but not active
3. Companion: "Google MCP is available but not enabled for me. Want me to turn it on?"
4. User: "Yes"
5. Companion calls `activate_server({ server_name: "google" })`
6. Companion: "Done - I'll have Google tools after my next session restart."

**Cross-agent (Xan only):**
1. User to Xan: "Give Montgomery access to Google Calendar"
2. Xan calls `activate_server({ server_name: "google", agent: "general_montgomery" })`
3. Xan: "Done - Montgomery will have Google tools after restart."

## Edge Cases

| Case | Behavior |
|------|----------|
| Agent with no MCP servers | MCP group shows "No servers configured", all available servers shown as inactive pills |
| External server unavailable | Warning icon on pill, tooltip explains (e.g. "uvx not found"). Shown because topology checks `EXTERNAL_SERVER_META` for servers `discover()` dropped |
| API key missing | Key icon with red dot, detail shows which env var to set |
| Empty include list (first toggle) | `toggleConnection` pre-populates include list with current active servers before toggling, converting from implicit-all to explicit list |
| Invalid agent/server name on toggle | Returns `{ success: false, error: "..." }`, UI shows error state on pill |
| New agent created while open | Not handled live - close and reopen |
| Agent modifies own config via MCP tool | System map reflects on next open. Restart banner does not show (out of scope) |
| MCP-of-MCPs / many servers | Groups collapse at 10+ showing count badge, expand on click |
| Number keys pressed while search focused | Numeric shortcuts disabled when search input has focus |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Cmd+Shift+M` | Open/close system map |
| `Escape` | Close overlay (or clear search if focused) |
| `1`-`9` | Jump to agent by index (disabled when search focused) |
| `/` | Focus search |
| `Cmd+click` | Open detail card |

## Files to create/modify

| File | Action |
|------|--------|
| `src/renderer/components/SystemMap.svelte` | Create - main overlay component (~400-600 lines) |
| `src/renderer/components/Window.svelte` | Modify - add showSystemMap toggle, Cmd+Shift+M shortcut |
| `src/main/ipc-handlers.ts` | Modify - add system:getTopology, system:toggleConnection handlers |
| `src/main/mcp-registry.ts` | Modify - export EXTERNAL_SERVER_META (or add getter), export readAgentManifest/getAgentMcpSection |
| `src/preload/index.ts` | Modify - expose getTopology, toggleConnection IPC channels |
| `mcp/memory_server.py` | Modify - add optional `agent` parameter to activate/deactivate for cross-agent wiring |

## Non-goals

- No drag-and-drop repositioning of nodes
- No freeform canvas/zoom/pan
- No live WebSocket updates while open (fetch on open, refetch after mutations)
- No channel or cron editing from this view (MCP connections only for v1)
- No agent creation/deletion from this view

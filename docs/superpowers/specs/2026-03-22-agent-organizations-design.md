# Agent Organizations - Design Spec

**Date:** 2026-03-22
**Status:** Approved design, pending implementation plan
**Review:** Passed spec review (10 issues found, all addressed)

## Summary

A layered organizational system for agents. Organizations are persistent entities with identity and institutional memory. Agents belong to orgs at different tiers (principal, staff, ephemeral) with hierarchical reporting lines. The user is sovereign. Xan (Chief of Staff) provisions and restructures orgs conversationally. The system supports multiple org types - government, company, creative studio, utility - running in parallel.

## Requirements

- **Organizational structure:** agents grouped into orgs with hierarchy, reporting lines, and communication policies
- **Tiered provisioning:** tier determines what infrastructure an agent gets (voice, Telegram, avatar, memory)
- **Institutional memory:** orgs have their own memory DB that persists across agent changes
- **Conversational creation:** user describes a need, Xan proposes an org structure, user approves, Xan creates it
- **Visual hierarchy:** System Map shows orgs as clusters with reporting lines as edges
- **Agent manifests as source of truth:** org membership, tier, reporting all live in agent.json
- **User-agnostic:** use dynamic user name from config, never hardcode

## Architecture

### Tier Model

| Tier | Name | Provisioning | User Access | Persistence |
|------|------|-------------|-------------|-------------|
| 0 | System | Full + system_access + can_provision | Yes | Permanent |
| 1 | Principal | Full: voice, avatar, Telegram, Obsidian, own memory DB | Yes | Permanent |
| 2 | Staff | Memory DB + prompts. No voice, no avatar, no Telegram | No (switchboard only) | Permanent |
| 3+ | Ephemeral | No persistence. Context from creator, destroyed on task completion | No | None |

### Organization Types

Semantic, not technically enforced. Give meaning and defaults:

| Type | Examples | Character |
|------|----------|-----------|
| `government` | Defence, Legal, Treasury | Advisory, formal, civil service |
| `company` | Acme Ltd, StartupCo | Commercial, output-focused |
| `creative` | MusicCo, Design Studio | Artistic, expressive |
| `utility` | File Manager, Backup System | Functional, quiet |

`personal` and `system` are **not org types** - they are values for `org.slug` on agents that exist outside any organization (Companion, Mirror, Xan). These agents have no `org.json` file and appear in dedicated sections of the System Map topology.

### Data Model

#### Organization manifest (`~/.atrophy/orgs/<slug>/org.json`)

Lightweight index. Only created for real orgs (government, company, creative, utility). Roster and reporting derived from agent manifests - never stored here.

```json
{
  "name": "Defence Bureau",
  "slug": "defence",
  "type": "government",
  "purpose": "National security, intelligence analysis, threat assessment",
  "created": "2026-03-22T00:00:00Z",
  "principal": "general_montgomery",
  "communication": {
    "cross_org": ["government"]
  }
}
```

#### Organization memory (`~/.atrophy/orgs/<slug>/memory.db`)

SQLite database for institutional knowledge. Same schema as agent memory but scoped to the org. Survives individual agent turnover - when a minister is replaced, the department's institutional knowledge stays.

**Wiring:** `buildServerEnv()` in `mcp-registry.ts` injects `ORG_DB` env var pointing to `~/.atrophy/orgs/<slug>/memory.db` when the agent has an `org.slug` that maps to a real org (one with an `org.json`). The memory server reads `ORG_DB` alongside `COMPANION_DB` and exposes org-scoped memory tools (`org_observe`, `org_recall`, etc.) when set.

#### Agent manifest extensions (`agent.json`)

Every agent gains an `org` section. The top-level `role` field is **display-only** (shown in UI, no logic depends on it). `org.tier` replaces the old `role === 'system'` sorting key in `discoverAgents()`.

```json
{
  "name": "intel_analyst_1",
  "display_name": "Analyst Webb",
  "description": "Senior intelligence analyst specialising in OSINT",
  "role": "Senior Analyst",

  "org": {
    "slug": "defence",
    "tier": 2,
    "role": "Senior Analyst",
    "reports_to": "general_montgomery",
    "direct_reports": ["osint_worker"],
    "can_address_user": false
  },

  "mcp": { "include": ["memory", "shell", "worldmonitor"] },
  "channels": {},
  "jobs": {},
  "router": {
    "accept_from": ["general_montgomery", "osint_worker"],
    "can_address_agents": true,
    "system_access": false
  }
}
```

**Tier 1 Principal example (General Montgomery):**

```json
{
  "name": "general_montgomery",
  "display_name": "General Montgomery",
  "description": "Secretary of Defence, intelligence and security",
  "role": "Secretary of Defence",

  "org": {
    "slug": "defence",
    "tier": 1,
    "role": "Secretary of Defence",
    "reports_to": null,
    "direct_reports": ["intel_analyst_1"],
    "can_address_user": true
  },

  "voice": { "elevenlabs_voice_id": "0z5GDPjj5mWa..." },
  "channels": { "telegram": { "enabled": true, "bot_token_env": "TELEGRAM_BOT_TOKEN_MONTGOMERY", "chat_id_env": "TELEGRAM_CHAT_ID_MONTGOMERY" } },
  "mcp": { "include": ["memory", "shell", "worldmonitor", "elevenlabs", "fal"] }
}
```

**System agent (Xan) - no org.json, uses slug for topology grouping:**

```json
{
  "name": "xan",
  "display_name": "Xan",
  "role": "Chief of Staff",

  "org": {
    "slug": "system",
    "tier": 0,
    "role": "Chief of Staff",
    "reports_to": null,
    "direct_reports": [],
    "can_address_user": true,
    "can_provision": true
  }
}
```

**Personal agents (Companion, Mirror) - no org.json:**

```json
{
  "org": {
    "slug": "personal",
    "tier": 1,
    "role": "Special Adviser",
    "reports_to": null,
    "direct_reports": [],
    "can_address_user": true
  }
}
```

### Roster Derivation

The org roster is never stored in `org.json`. It is built dynamically by scanning agent manifests.

**Performance:** `discoverAgents()` does a full `readdirSync` scan on every call. `readAgentManifest()` reads from disk with no cache. For the current scale (4-20 agents) this is fine. Phase 1 adds a simple in-memory manifest cache to `org-manager.ts` with a `clearCache()` method called on agent creation/deletion. This avoids O(orgs * agents) filesystem reads when listing all orgs.

```typescript
function getOrgRoster(orgSlug: string): OrgAgent[] {
  return getAllManifests() // cached scan
    .filter(m => m.org?.slug === orgSlug)
    .map(m => ({
      name: m.name,
      tier: m.org.tier,
      role: m.org.role,
      reports_to: m.org.reports_to,
      direct_reports: m.org.direct_reports,
      can_address_user: m.org.can_address_user,
    }));
}
```

### Communication Rules

Enforced at the **agent-router layer**, not the switchboard itself. The switchboard is a dumb pipe - it routes envelopes to registered addresses. The agent-router (`agent-router.ts`) filters inbound messages based on `router.accept_from` before they reach inference.

This means: if code calls `switchboard.route()` directly (e.g. an MCP tool or cron runner), it bypasses tier-based filtering. This is by design - system-level routing (job output, MCP responses) should not be blocked by org hierarchy. Only agent-to-agent conversational messages pass through the agent-router filter.

| Tier | Can message (via agent-router) |
|------|------|
| 0 (System) | Anyone |
| 1 (Principal) | User, Xan, other tier 1 in same org, cross-org principals (if allowed), own reports |
| 2 (Staff) | `reports_to` agent, own direct reports |
| 3+ (Ephemeral) | Creator only |

When `create-agent.ts` provisions an agent, it auto-generates `router.accept_from` from the org hierarchy:
- Tier 0-1 accepts from: `["*"]` (can receive from anyone)
- Tier 2 accepts from: their `reports_to` + their `direct_reports`
- Tier 3 accepts from: their creator only

### Agent Sorting

`discoverAgents()` currently sorts by `role === 'system'`. This changes to sort by `org.tier`:
- Tier 0 agents first (Xan)
- Then tier 1 alphabetically
- Then tier 2+

The top-level `role` field becomes display-only and is no longer used for sorting.

### Org Manager (`src/main/org-manager.ts`)

New module. Core operations:

```typescript
// Create
createOrg(name: string, type: OrgType, purpose: string): OrgManifest
addAgentToOrg(orgSlug: string, agentName: string, role: string, tier: number, reportsTo: string | null): void
createAgentInOrg(orgSlug: string, opts: CreateAgentOpts): AgentInfo  // creates + assigns in one step

// Read (uses manifest cache)
listOrgs(): OrgManifest[]
getOrgDetail(slug: string): { manifest: OrgManifest; roster: OrgAgent[]; tree: OrgTree }
getOrgTree(slug: string): OrgTree  // hierarchical tree for visualization

// Modify
restructureOrg(slug: string, changes: RestructureOpts): void  // batch role/tier/reporting changes
removeAgentFromOrg(agentName: string): void  // unassign from org, agent persists

// Delete
dissolveOrg(slug: string): void  // remove org.json + memory.db, unassign all agents
```

**Note:** `promoteAgent()` and `destroyAgents` are deferred to Phase 3 where tier-based provisioning is implemented. In Phase 1, tier is set at agent creation time only. Restructuring can change role and reporting lines but not tier.

### MCP Tools for Xan

Added to memory server under a new `org` action group.

**Security:** The `org` action group is gated on `can_provision`. On startup, the memory server reads the agent manifest for the `AGENT` env var and checks `org.can_provision`. If false (or absent), all `org:*` tool calls return an error: "Only agents with provisioning access can manage organizations."

```
org:create_org          - create a new organization
org:dissolve_org        - remove an organization (unassigns agents, does not delete them)
org:list_orgs           - show all organizations with rosters
org:get_org_detail      - full org topology and purpose
org:add_agent           - create an agent and assign to org in one step
org:remove_agent        - remove an agent from org (agent persists)
org:restructure         - change reporting lines and roles (not tier - Phase 3)
org:set_purpose         - update org purpose/description
```

### Conversational Creation Flow

1. User: "I need someone managing my music and playlists"
2. Xan calls `org:list_orgs` - checks no music org exists
3. Xan proposes: "I'll create a MusicCo org (type: creative) with a DJ Bot as principal. They'll handle Shazam-to-download pipeline, playlist curation, and music discovery. Approve?"
4. User: "Yes, and give them a junior for research"
5. Xan calls:
   - `org:create_org({ name: "MusicCo", type: "creative", purpose: "Music discovery, playlist curation, download management" })`
   - `org:add_agent({ org: "musicco", name: "dj_bot", display_name: "DJ Bot", role: "Music Director", tier: 1 })`
   - `org:add_agent({ org: "musicco", name: "music_researcher", display_name: "Scout", role: "Music Researcher", tier: 2, reports_to: "dj_bot" })`
6. DJ Bot gets full provisioning (Telegram, voice). Scout gets memory + prompts only.
7. Both appear in System Map under MusicCo cluster.

### Restructuring Flow

1. User: "Move the analyst from Defence to a new Intelligence org"
2. Xan proposes the restructure, user approves
3. Xan calls:
   - `org:create_org({ name: "Intelligence Bureau", type: "government", purpose: "..." })`
   - `org:remove_agent({ agent: "intel_analyst_1" })` (from Defence)
   - `org:add_agent({ org: "intelligence", name: "intel_analyst_1", role: "Director", tier: 1, reports_to: null })`
4. Analyst's tier changes from 2 to 1 (provisioning upgrade deferred to Phase 3)
5. Manifest updates immediately, full provisioning adjustment in Phase 3

### System Map Integration

`buildTopology()` gains org awareness:

```typescript
interface OrgTopology {
  orgs: Array<{
    slug: string;
    name: string;
    type: string;
    purpose: string;
    agents: Array<{
      name: string;
      displayName: string;
      tier: number;
      role: string;
      reportsTo: string | null;
      directReports: string[];
      canAddressUser: boolean;
    }>;
  }>;
  personal: TopologyAgent[];  // agents with org.slug === 'personal'
  system: TopologyAgent[];    // agents with org.slug === 'system'
}
```

The System Map renders orgs as collapsible clusters. Within each cluster, agents are positioned by tier (principal at top, staff below, ephemeral at bottom). `reports_to` edges are drawn as subtle lines within the cluster. Cross-org communication links shown as dotted lines between principals.

### Existing Agent Migration

**Order matters:** migrate agent manifests first, then create org directories.

**Step 1:** Add `org` sections to existing agent manifests:

| Agent | `org.slug` | Tier | Role | Has org.json? |
|-------|-----------|------|------|---------------|
| `xan` | `system` | 0 | Chief of Staff | No |
| `companion` | `personal` | 1 | Special Adviser | No |
| `general_montgomery` | `defence` | 1 | Secretary of Defence | Yes |
| `mirror` | `personal` | 1 | Personal | No |

**Step 2:** Create org directory and manifest for `defence` only:

```
~/.atrophy/orgs/
  defence/
    org.json     # { name: "Defence Bureau", type: "government", ... }
    memory.db    # empty, schema applied
```

**Step 3:** Update `discoverAgents()` sorting to use `org.tier` instead of `role === 'system'`.

No behavioral change. Everything works exactly as before. The org fields are additive metadata.

## Implementation Phases

### Phase 1: Data model + org-manager + MCP tools + manifest migration
- Create `src/main/org-manager.ts` with manifest cache
- Create `~/.atrophy/orgs/` directory structure
- Migrate existing agent manifests (add `org` sections) - **before** creating org dirs
- Create `defence` org manifest and empty memory.db
- Add org MCP tools to `memory_server.py` with `can_provision` gate
- Add `ORG_DB` env var to `buildServerEnv()` in `mcp-registry.ts`
- Update `discoverAgents()` sorting to use `org.tier`
- Create org memory DB schema (`db/org-schema.sql`)
- Tests for org-manager
- **Not in Phase 1:** `org:promote` (needs provisioning), `destroyAgents` (needs lifecycle), tier changes post-creation

### Phase 2: System Map org view
- Update `buildTopology()` for org-aware data
- Update `SystemMap.svelte` to render org clusters with hierarchy
- Reporting line visualization within clusters
- Cross-org communication lines

### Phase 3: Tier-based provisioning + lifecycle
- `create-agent.ts` reads tier to decide what to provision
- `promoteAgent()` - changes tier and adjusts provisioning (add/remove Telegram, voice, avatar)
- Auto-generate `router.accept_from` from hierarchy
- Auto-skip voice/Telegram/avatar setup for tier 2+
- Ephemeral agent lifecycle (create, task, destroy)
- `dissolveOrg` gains `destroyAgents` option

### Phase 4: Conversational org management via Xan
- Xan's prompts updated to understand org structure
- Xan proposes org creation/restructuring in conversation
- User approves, Xan executes via MCP tools

## Non-goals

- No inter-org governance (voting, consensus) - Xan orchestrates, user decides
- No agent-to-agent real-time collaboration (shared context windows)
- No visual org editor (drag agents between orgs) - conversational via Xan, toggles via System Map
- No autonomous org creation by Xan without user approval (Phase 4 is approval-gated)
- No financial/billing tracking per org (GDP is metaphorical)

## Known Limitations

- **Roster derivation scans filesystem** - mitigated by manifest cache in org-manager, but still O(agents) per call
- **Communication enforcement at agent-router only** - direct switchboard.route() calls bypass tier filtering (by design for system-level routing)
- **Phase 1 tier is set-once** - changing tier after creation requires Phase 3 provisioning logic
- **No multi-org membership** - an agent belongs to exactly one org (or personal/system). If needed later, `org.slug` could become `org.slugs[]`

## Files to create/modify

| File | Action | Phase |
|------|--------|-------|
| `src/main/org-manager.ts` | Create | 1 |
| `src/main/mcp-registry.ts` | Modify (add ORG_DB to buildServerEnv) | 1 |
| `src/main/system-topology.ts` | Modify | 1 (types), 2 (org-aware build) |
| `src/main/agent-manager.ts` | Modify (tier-based sorting) | 1 |
| `src/main/ipc/system.ts` | Modify (org IPC handlers) | 1 |
| `src/preload/index.ts` | Modify (org IPC channels) | 1 |
| `mcp/memory_server.py` | Modify (org action group + can_provision gate) | 1 |
| `src/main/create-agent.ts` | Modify | 1 (org context), 3 (tier provisioning) |
| `~/.atrophy/agents/*/data/agent.json` | Modify (add org sections) | 1 |
| `~/.atrophy/orgs/defence/org.json` | Create | 1 |
| `db/org-schema.sql` | Create | 1 |
| `src/renderer/components/SystemMap.svelte` | Modify | 2 (org clusters) |
| `src/main/__tests__/org-manager.test.ts` | Create | 1 |

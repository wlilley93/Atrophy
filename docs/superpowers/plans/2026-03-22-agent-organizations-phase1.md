# Agent Organizations Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add organizational structure to agents - org data model, org-manager module, MCP tools for Xan to create/manage orgs, manifest migration for existing agents, and ORG_DB wiring.

**Architecture:** Organizations are lightweight manifests at `~/.atrophy/orgs/<slug>/` with institutional memory DBs. Agent manifests gain an `org` section (slug, tier, role, reports_to, direct_reports). Roster is derived dynamically from scanning agent manifests. Xan manages orgs via MCP tools gated on `can_provision`.

**Tech Stack:** TypeScript (org-manager, IPC), Python (MCP tools), SQLite (org memory), Vitest (tests)

**Spec:** `docs/superpowers/specs/2026-03-22-agent-organizations-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `db/org-schema.sql` | Create | Org institutional memory DB schema |
| `src/main/org-manager.ts` | Create | Org CRUD, roster derivation, manifest cache |
| `src/main/__tests__/org-manager.test.ts` | Create | Tests for org-manager |
| `src/main/agent-manager.ts` | Modify | Tier-based sorting in discoverAgents() |
| `src/main/mcp-registry.ts` | Modify | Add ORG_DB env var to buildServerEnv() |
| `src/main/ipc/system.ts` | Modify | Add org IPC handlers |
| `src/preload/index.ts` | Modify | Expose org IPC channels |
| `mcp/memory_server.py` | Modify | Add org action group with can_provision gate |
| `~/.atrophy/agents/*/data/agent.json` | Modify | Add org sections to 4 existing agents |

---

### Task 1: Create org memory schema

**Files:**
- Create: `db/org-schema.sql`

- [ ] **Step 1: Create schema file** with tables for observations, threads, thread_entries, decisions, and sessions scoped to organizational institutional knowledge.

- [ ] **Step 2: Commit**

---

### Task 2: Create org-manager with tests (TDD)

**Files:**
- Create: `src/main/__tests__/org-manager.test.ts`
- Create: `src/main/org-manager.ts`

The org-manager module provides: `createOrg`, `listOrgs`, `getOrgDetail`, `getOrgRoster`, `addAgentToOrg`, `removeAgentFromOrg`, `dissolveOrg`, `clearCache`.

Key behaviors:
- `createOrg(name, type, purpose)` - creates `~/.atrophy/orgs/<slug>/org.json` + `memory.db`, validates type is one of: government, company, creative, utility
- `listOrgs()` - scans `~/.atrophy/orgs/` for org.json files
- `getOrgRoster(slug)` - scans agent manifests via cached `getAllManifests()`, filters by `org.slug`
- `addAgentToOrg(slug, name, role, tier, reportsTo)` - updates agent manifest org section, updates parent's direct_reports
- `removeAgentFromOrg(name)` - removes org section, updates parent's direct_reports, clears org principal if needed
- `dissolveOrg(slug)` - unassigns all agents, removes org directory
- `clearCache()` - invalidates manifest cache

Uses `readAgentManifest` from mcp-registry.ts, `saveAgentConfig` and `isValidAgentName` from config.ts, `discoverAgents` from agent-manager.ts.

Tests should cover: create, duplicate rejection, list empty/populated, roster derivation, dissolve, and invalid input handling.

- [ ] **Step 1: Write test file**
- [ ] **Step 2: Run tests - verify fail (module missing)**
- [ ] **Step 3: Implement org-manager.ts**
- [ ] **Step 4: Run tests - verify pass**
- [ ] **Step 5: Type-check:** `npx tsc --noEmit`
- [ ] **Step 6: Commit**

---

### Task 3: Add ORG_DB to MCP server env

**Files:**
- Modify: `src/main/mcp-registry.ts`

In `buildServerEnv()`, inside the `case 'memory':` block, after existing env vars, read the agent's `org.slug` from manifest. If the slug maps to a real org (not 'personal' or 'system') and `~/.atrophy/orgs/<slug>/memory.db` exists, set `env.ORG_DB` and `env.ORG_SLUG`.

- [ ] **Step 1: Add ORG_DB resolution to case 'memory' block**
- [ ] **Step 2: Type-check**
- [ ] **Step 3: Commit**

---

### Task 4: Update agent sorting to use org.tier

**Files:**
- Modify: `src/main/agent-manager.ts`

- Add `tier: number` to `AgentInfo` interface
- Read `org.tier` from manifest in discovery loop, default to 1
- Replace sorting comparator: sort by tier ascending (lower = higher priority), then alphabetical. Remove the `role === 'system'` check and `xan` pin.

- [ ] **Step 1: Update AgentInfo interface**
- [ ] **Step 2: Populate tier in discovery loop**
- [ ] **Step 3: Replace sorting logic**
- [ ] **Step 4: Run tests:** `npx vitest run`
- [ ] **Step 5: Commit**

---

### Task 5: Add org MCP tools to memory_server.py

**Files:**
- Modify: `mcp/memory_server.py`

Add an `org` tool with actions: create_org, dissolve_org, list_orgs, get_org_detail, add_agent, remove_agent, restructure, set_purpose.

Key implementation details:
- `_has_provision_access()` checks `org.can_provision` in the calling agent's manifest. All org actions are gated on this.
- Org manifests at `~/.atrophy/orgs/<slug>/org.json`
- Roster derived by scanning `~/.atrophy/agents/*/data/agent.json` for matching `org.slug`
- `add_agent` creates minimal agent directory if agent doesn't exist, or updates existing agent's org section
- `restructure` takes a changes map of `{agent_name: {role, reports_to}}` and batch-updates manifests
- `dissolve_org` unassigns all agents and removes org directory
- Import `datetime` for timestamps, `sqlite3` for DB init

- [ ] **Step 1: Add org tool schema definition**
- [ ] **Step 2: Add `_has_provision_access()` helper**
- [ ] **Step 3: Add handler functions**
- [ ] **Step 4: Add dispatch entry**
- [ ] **Step 5: Syntax check:** `python3 -c "import py_compile; py_compile.compile('mcp/memory_server.py', doraise=True)"`
- [ ] **Step 6: Commit**

---

### Task 6: Add org IPC handlers and preload

**Files:**
- Modify: `src/main/ipc/system.ts`
- Modify: `src/preload/index.ts`

IPC channels: `org:list`, `org:detail`, `org:create`, `org:dissolve`, `org:addAgent`, `org:removeAgent`

Each handler delegates to the corresponding org-manager function.

Preload API additions: `listOrgs`, `getOrgDetail`, `createOrg`, `dissolveOrg`, `addAgentToOrg`, `removeAgentFromOrg`

- [ ] **Step 1: Add imports and handlers to system.ts**
- [ ] **Step 2: Add interface properties and implementations to preload**
- [ ] **Step 3: Type-check**
- [ ] **Step 4: Commit**

---

### Task 7: Migrate existing agent manifests

**Files:**
- Modify: `~/.atrophy/agents/xan/data/agent.json` - add org: {slug: 'system', tier: 0, role: 'Chief of Staff', can_provision: true}
- Modify: `~/.atrophy/agents/companion/data/agent.json` - add org: {slug: 'personal', tier: 1, role: 'Special Adviser'}
- Modify: `~/.atrophy/agents/general_montgomery/data/agent.json` - add org: {slug: 'defence', tier: 1, role: 'Secretary of Defence'}
- Modify: `~/.atrophy/agents/mirror/data/agent.json` - add org: {slug: 'personal', tier: 1, role: 'Personal'}
- Create: `~/.atrophy/orgs/defence/org.json` - Defence Bureau manifest
- Create: `~/.atrophy/orgs/defence/memory.db` - initialized with org-schema.sql

Order: manifests first, then org directory.

- [ ] **Step 1: Add org sections to all 4 agent manifests**
- [ ] **Step 2: Create defence org directory and manifest**
- [ ] **Step 3: Initialize defence org memory DB from schema**
- [ ] **Step 4: Verify all manifests read correctly**
- [ ] **Step 5: Commit schema file**

---

### Task 8: Build, test, notarize, push

- [ ] **Step 1: Run all tests:** `npx vitest run`
- [ ] **Step 2: Type-check:** `npx tsc --noEmit`
- [ ] **Step 3: Bump version and build:** `npm version patch --no-git-tag-version && pnpm run dist:mac`
- [ ] **Step 4: Notarize DMG and zip**
- [ ] **Step 5: Staple DMG**
- [ ] **Step 6: Install locally and relaunch**
- [ ] **Step 7: Commit and push**

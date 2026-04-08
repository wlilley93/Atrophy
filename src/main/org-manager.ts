/**
 * Org manager - CRUD for agent organizations, roster derivation, manifest cache.
 *
 * Organizations are lightweight manifests at ~/.atrophy/orgs/<slug>/ with
 * institutional memory DBs. Roster is derived dynamically from scanning
 * agent manifests. Agents belong to exactly one org (or personal/system).
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { USER_DATA, BUNDLE_ROOT, isValidAgentName, saveAgentConfig } from './config';
import { readAgentManifest } from './mcp-registry';
import { discoverAgents, getAgentDir } from './agent-manager';
import { createLogger } from './logger';

const log = createLogger('org-manager');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Valid organization types. */
export type OrgType = 'government' | 'company' | 'creative' | 'utility';

const VALID_ORG_TYPES: readonly OrgType[] = ['government', 'company', 'creative', 'utility'];

/** Organization manifest stored at ~/.atrophy/orgs/<slug>/org.json. */
export interface OrgManifest {
  name: string;
  slug: string;
  type: OrgType;
  purpose: string;
  created: string;
  principal: string | null;
  communication?: {
    cross_org?: string[];
  };
}

/** Agent entry within an org roster. */
export interface OrgAgent {
  name: string;
  tier: number;
  role: string;
  reports_to: string | null;
  direct_reports: string[];
  can_address_user: boolean;
}

/** Agent manifest org section. */
export interface AgentOrgSection {
  slug: string;
  tier: number;
  role: string;
  reports_to?: string | null;
  direct_reports?: string[];
  can_address_user?: boolean;
  can_provision?: boolean;
}

/** Full org detail returned by getOrgDetail. */
export interface OrgDetail {
  manifest: OrgManifest;
  roster: OrgAgent[];
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

function orgsDir(): string {
  return path.join(USER_DATA, 'orgs');
}

function orgDir(slug: string): string {
  return path.join(orgsDir(), slug);
}

function orgManifestPath(slug: string): string {
  return path.join(orgDir(slug), 'org.json');
}

function orgDbPath(slug: string): string {
  return path.join(orgDir(slug), 'memory.db');
}

// ---------------------------------------------------------------------------
// Slug generation
// ---------------------------------------------------------------------------

/**
 * Generate a URL-safe slug from an org name.
 * Lowercases, replaces non-alphanumeric runs with hyphens, trims.
 */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// ---------------------------------------------------------------------------
// Manifest cache
// ---------------------------------------------------------------------------

/**
 * Simple in-memory cache for agent manifests to avoid O(orgs * agents)
 * filesystem reads when listing all orgs. Invalidated on agent creation,
 * deletion, or org membership changes via clearCache().
 */
let _manifestCache: Array<{ name: string; manifest: Record<string, unknown> }> | null = null;

/**
 * Get all agent manifests, using cache if available.
 * Each entry contains the agent name and parsed manifest.
 */
function getAllManifests(): Array<{ name: string; manifest: Record<string, unknown> }> {
  if (_manifestCache !== null) return _manifestCache;

  const agents = discoverAgents();
  _manifestCache = agents.map(a => ({
    name: a.name,
    manifest: readAgentManifest(a.name),
  }));

  return _manifestCache;
}

/**
 * Invalidate the manifest cache. Call after agent creation, deletion,
 * or any org membership change.
 */
export function clearCache(): void {
  _manifestCache = null;
}

// ---------------------------------------------------------------------------
// Org CRUD
// ---------------------------------------------------------------------------

/**
 * Create a new organization.
 *
 * Creates the org directory, writes org.json, and initializes memory.db
 * with the org schema. Validates that the slug is unique and the type is valid.
 *
 * @throws If org already exists, type is invalid, or name is empty.
 */
export function createOrg(name: string, type: OrgType, purpose: string): OrgManifest {
  if (!name || !name.trim()) {
    throw new Error('Org name cannot be empty');
  }

  if (!VALID_ORG_TYPES.includes(type)) {
    throw new Error(`Invalid org type "${type}" - must be one of: ${VALID_ORG_TYPES.join(', ')}`);
  }

  const slug = slugify(name);
  if (!slug) {
    throw new Error('Org name produces an empty slug');
  }

  const dir = orgDir(slug);
  if (fs.existsSync(dir)) {
    throw new Error(`Org "${slug}" already exists`);
  }

  // Create directory
  fs.mkdirSync(dir, { recursive: true });

  // Write manifest
  const manifest: OrgManifest = {
    name,
    slug,
    type,
    purpose,
    created: new Date().toISOString(),
    principal: null,
  };

  fs.writeFileSync(orgManifestPath(slug), JSON.stringify(manifest, null, 2));

  // Initialize memory.db with org schema
  const schemaPath = path.join(BUNDLE_ROOT, 'db', 'org-schema.sql');
  if (fs.existsSync(schemaPath)) {
    const schema = fs.readFileSync(schemaPath, 'utf-8');
    const db = new Database(orgDbPath(slug));
    db.exec(schema);
    db.close();
  } else {
    // Create empty DB if schema not found
    log.warn(`Org schema not found at ${schemaPath} - creating empty memory.db`);
    const db = new Database(orgDbPath(slug));
    db.close();
  }

  log.info(`Created org "${name}" (${type}) at ${dir}`);
  return manifest;
}

/**
 * List all organizations by scanning ~/.atrophy/orgs/ for org.json files.
 */
export function listOrgs(): OrgManifest[] {
  const dir = orgsDir();
  if (!fs.existsSync(dir)) return [];

  const orgs: OrgManifest[] = [];

  for (const entry of fs.readdirSync(dir)) {
    const manifestPath = orgManifestPath(entry);
    if (fs.existsSync(manifestPath)) {
      try {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as OrgManifest;
        orgs.push(manifest);
      } catch (e) {
        log.warn(`Failed to read org manifest at ${manifestPath}: ${e}`);
      }
    }
  }

  return orgs;
}

/**
 * Get full org details including manifest and derived roster.
 *
 * @throws If org does not exist.
 */
export function getOrgDetail(slug: string): OrgDetail {
  const manifestPath = orgManifestPath(slug);
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Org "${slug}" not found`);
  }

  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as OrgManifest;
  const roster = getOrgRoster(slug);

  return { manifest, roster };
}

/**
 * Get the roster for an org by scanning agent manifests.
 * Returns agents whose org.slug matches the given slug.
 */
export function getOrgRoster(slug: string): OrgAgent[] {
  return getAllManifests()
    .filter(entry => {
      const org = entry.manifest.org as AgentOrgSection | undefined;
      return org?.slug === slug;
    })
    .map(entry => {
      const org = entry.manifest.org as AgentOrgSection;
      return {
        name: entry.name,
        tier: org.tier ?? 1,
        role: org.role ?? '',
        reports_to: org.reports_to ?? null,
        direct_reports: org.direct_reports ?? [],
        can_address_user: org.can_address_user ?? false,
      };
    });
}

/**
 * Add an agent to an organization.
 *
 * Updates the agent's manifest with an org section. If reportsTo is provided,
 * also updates the parent agent's direct_reports array. If the agent is tier 1
 * and no principal exists, sets the agent as org principal.
 *
 * @throws If org does not exist, agent name is invalid.
 */
export function addAgentToOrg(
  orgSlug: string,
  agentName: string,
  role: string,
  tier: number,
  reportsTo: string | null,
): void {
  if (!isValidAgentName(agentName)) {
    throw new Error(`Invalid agent name "${agentName}"`);
  }

  const manifestPath = orgManifestPath(orgSlug);
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Org "${orgSlug}" not found`);
  }

  // Update agent manifest with org section
  const orgSection: AgentOrgSection = {
    slug: orgSlug,
    tier,
    role,
    reports_to: reportsTo,
    direct_reports: [],
    can_address_user: tier <= 1,
  };

  saveAgentConfig(agentName, { org: orgSection });

  // Update parent's direct_reports if reportsTo is set
  if (reportsTo && isValidAgentName(reportsTo)) {
    const parentManifest = readAgentManifest(reportsTo);
    const parentOrg = parentManifest.org as AgentOrgSection | undefined;
    if (parentOrg) {
      const directReports = [...(parentOrg.direct_reports || [])];
      if (!directReports.includes(agentName)) {
        directReports.push(agentName);
      }
      saveAgentConfig(reportsTo, {
        org: { ...parentOrg, direct_reports: directReports },
      });
    }
  }

  // Set as org principal if tier 1 and no principal exists
  if (tier === 1) {
    const orgManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as OrgManifest;
    if (!orgManifest.principal) {
      orgManifest.principal = agentName;
      fs.writeFileSync(manifestPath, JSON.stringify(orgManifest, null, 2));
    }
  }

  // Invalidate cache since membership changed
  clearCache();

  log.info(`Added agent "${agentName}" to org "${orgSlug}" as ${role} (tier ${tier})`);
}

/**
 * Remove an agent from its organization.
 *
 * Removes the org section from the agent's manifest. If the agent has
 * a reports_to, removes the agent from the parent's direct_reports.
 * If the agent was the org principal, clears the principal field.
 *
 * @throws If agent name is invalid.
 */
export function removeAgentFromOrg(agentName: string): void {
  if (!isValidAgentName(agentName)) {
    throw new Error(`Invalid agent name "${agentName}"`);
  }

  const manifest = readAgentManifest(agentName);
  const org = manifest.org as AgentOrgSection | undefined;
  if (!org) {
    log.warn(`Agent "${agentName}" is not in any org`);
    return;
  }

  const orgSlug = org.slug;
  const reportsTo = org.reports_to;

  // Remove from parent's direct_reports
  if (reportsTo && isValidAgentName(reportsTo)) {
    const parentManifest = readAgentManifest(reportsTo);
    const parentOrg = parentManifest.org as AgentOrgSection | undefined;
    if (parentOrg) {
      const directReports = (parentOrg.direct_reports || []).filter(
        (r: string) => r !== agentName,
      );
      saveAgentConfig(reportsTo, {
        org: { ...parentOrg, direct_reports: directReports },
      });
    }
  }

  // Clear org principal if this agent was it
  const orgManPath = orgManifestPath(orgSlug);
  if (fs.existsSync(orgManPath)) {
    const orgManifest = JSON.parse(fs.readFileSync(orgManPath, 'utf-8')) as OrgManifest;
    if (orgManifest.principal === agentName) {
      orgManifest.principal = null;
      fs.writeFileSync(orgManPath, JSON.stringify(orgManifest, null, 2));
    }
  }

  // Remove org section from agent - write manifest without org key
  // saveAgentConfig merges, so we need to explicitly set org to undefined
  // by reading and rewriting the full manifest
  const agentJsonPath = path.join(getAgentDir(agentName), 'data', 'agent.json');
  if (fs.existsSync(agentJsonPath)) {
    const fullManifest = JSON.parse(fs.readFileSync(agentJsonPath, 'utf-8'));
    delete fullManifest.org;
    fs.writeFileSync(agentJsonPath, JSON.stringify(fullManifest, null, 2));
  }

  // Invalidate cache
  clearCache();

  log.info(`Removed agent "${agentName}" from org "${orgSlug}"`);
}

/**
 * Update org metadata (name and/or purpose).
 *
 * @throws If org does not exist.
 */
export function updateOrg(slug: string, updates: { name?: string; purpose?: string }): void {
  const manifestPath = orgManifestPath(slug);
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Org '${slug}' not found`);
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as OrgManifest;
  if (updates.name !== undefined && updates.name.trim()) manifest.name = updates.name;
  if (updates.purpose !== undefined) manifest.purpose = updates.purpose;
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  clearCache();
  log.info(`Updated org "${slug}"`);
}

/**
 * Dissolve an organization.
 *
 * Unassigns all agents from the org, then removes the org directory
 * (org.json and memory.db).
 *
 * @throws If org does not exist.
 */
export function dissolveOrg(slug: string): void {
  const dir = orgDir(slug);
  if (!fs.existsSync(dir)) {
    throw new Error(`Org "${slug}" not found`);
  }

  // Unassign all agents in this org
  const roster = getOrgRoster(slug);
  for (const agent of roster) {
    removeAgentFromOrg(agent.name);
  }

  // Remove org directory
  fs.rmSync(dir, { recursive: true, force: true });

  // Invalidate cache
  clearCache();

  log.info(`Dissolved org "${slug}" (${roster.length} agents unassigned)`);
}

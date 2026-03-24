/**
 * Hierarchy enforcement for agent provisioning.
 * Pure validation - checks whether a leader can create an underling
 * with the requested capabilities. No fs, no side effects.
 */

import { getScopeForTier } from './provisioning-scope';

export interface HierarchyViolation {
  field: string;
  reason: string;
}

export interface ProvisioningRequest {
  targetName: string;
  targetTier: number;
  targetOrg: string;
  mcpServers: string[];
  jobTypes: string[];
  hasTelegram: boolean;
  hasVoice: boolean;
  hasAvatar: boolean;
  personality?: Record<string, number>;
}

interface LeaderOrg {
  slug: string;
  tier: number;
  can_provision?: boolean;
}

/**
 * Validate that a provisioning request is within the leader's scope.
 * Returns an array of violations - empty means approved.
 */
export function validateProvisioningRequest(
  leaderName: string,
  leaderManifest: Record<string, unknown>,
  request: ProvisioningRequest,
): HierarchyViolation[] {
  const violations: HierarchyViolation[] = [];

  const leaderOrg = leaderManifest.org as LeaderOrg | undefined;

  // Must have provisioning rights
  if (!leaderOrg?.can_provision) {
    violations.push({
      field: 'can_provision',
      reason: `${leaderName} does not have provisioning rights`,
    });
    return violations; // no point checking further
  }

  const leaderTier = leaderOrg.tier;
  const leaderSlug = leaderOrg.slug;

  // Cannot create agents at same or higher tier (only Xan at tier 0 is exempt)
  if (leaderTier > 0 && request.targetTier <= leaderTier) {
    violations.push({
      field: 'targetTier',
      reason: `tier-${leaderTier} leader cannot create tier-${request.targetTier} agent (must be higher number)`,
    });
  }

  // Tier-0 (Xan) can create across orgs. Everyone else must stay in their own org.
  if (leaderTier > 0 && request.targetOrg !== leaderSlug) {
    violations.push({
      field: 'targetOrg',
      reason: `${leaderName} (org: ${leaderSlug}) cannot create agents in org: ${request.targetOrg}`,
    });
  }

  // Check MCP servers against what the leader's tier permits
  const leaderScope = getScopeForTier(leaderTier);
  const leaderMcp = (leaderManifest.mcp as { include?: string[] })?.include ?? leaderScope.allowedMcpServers;
  for (const server of request.mcpServers) {
    if (!leaderMcp.includes(server)) {
      violations.push({
        field: 'mcpServers',
        reason: `${leaderName} cannot grant MCP server "${server}" (not in their own scope)`,
      });
    }
  }

  // Check job types
  for (const job of request.jobTypes) {
    if (!leaderScope.allowedJobTypes.includes(job)) {
      violations.push({
        field: 'jobTypes',
        reason: `${leaderName} cannot grant job type "${job}" (not permitted at tier ${leaderTier})`,
      });
    }
  }

  // Channel escalation checks
  if (request.hasTelegram && !leaderScope.hasTelegram) {
    violations.push({
      field: 'hasTelegram',
      reason: `${leaderName} cannot grant Telegram access (not in their tier scope)`,
    });
  }

  if (request.hasVoice && !leaderScope.hasVoice) {
    violations.push({
      field: 'hasVoice',
      reason: `${leaderName} cannot grant voice synthesis (not in their tier scope)`,
    });
  }

  if (request.hasAvatar && !leaderScope.hasAvatar) {
    violations.push({
      field: 'hasAvatar',
      reason: `${leaderName} cannot grant avatar generation (not in their tier scope)`,
    });
  }

  return violations;
}

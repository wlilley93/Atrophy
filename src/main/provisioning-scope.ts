/**
 * Tier-to-capability mapping for the org hierarchy system.
 * Pure functions, no side effects - used by create-agent.ts and hierarchy-guard.ts.
 *
 * Tiers:
 *   0 - System (Xan). Full access, creates orgs and principals.
 *   1 - Org principal. Full feature set, can provision tier 2+.
 *   2 - Staff. Memory + shell, switchboard only, no user-facing channels.
 *   3+ - Ephemeral. Creator-scoped, no persistence.
 */

export interface ProvisioningScope {
  hasTelegram: boolean;
  hasDesktop: boolean;
  hasVoice: boolean;
  hasAvatar: boolean;
  allowedMcpServers: string[];
  allowedJobTypes: string[];
  canAddressUser: boolean;
  canAddressAgents: boolean;
  canProvision: boolean;
  systemAccess: boolean;
  maxQueueDepth: number;
}

const TIER_0_SCOPE: ProvisioningScope = {
  hasTelegram: true,
  hasDesktop: true,
  hasVoice: true,
  hasAvatar: true,
  allowedMcpServers: ['memory', 'shell', 'github', 'google', 'worldmonitor', 'puppeteer', 'elevenlabs', 'fal'],
  allowedJobTypes: ['heartbeat', 'observer', 'morning_brief', 'sleep_cycle', 'check_reminders', 'introspect', 'evolve'],
  canAddressUser: true,
  canAddressAgents: true,
  canProvision: true,
  systemAccess: true,
  maxQueueDepth: 20,
};

const TIER_1_SCOPE: ProvisioningScope = {
  hasTelegram: true,
  hasDesktop: true,
  hasVoice: true,
  hasAvatar: true,
  allowedMcpServers: ['memory', 'shell', 'github', 'elevenlabs', 'fal'],
  allowedJobTypes: ['heartbeat', 'observer', 'morning_brief', 'sleep_cycle', 'check_reminders'],
  canAddressUser: true,
  canAddressAgents: true,
  canProvision: true,
  systemAccess: false,
  maxQueueDepth: 10,
};

const TIER_2_SCOPE: ProvisioningScope = {
  hasTelegram: false,
  hasDesktop: false,
  hasVoice: false,
  hasAvatar: false,
  allowedMcpServers: ['memory', 'shell'],
  allowedJobTypes: ['observer'],
  canAddressUser: false,
  canAddressAgents: true,
  canProvision: false,
  systemAccess: false,
  maxQueueDepth: 5,
};

const TIER_3_SCOPE: ProvisioningScope = {
  hasTelegram: false,
  hasDesktop: false,
  hasVoice: false,
  hasAvatar: false,
  allowedMcpServers: ['memory'],
  allowedJobTypes: [],
  canAddressUser: false,
  canAddressAgents: false,
  canProvision: false,
  systemAccess: false,
  maxQueueDepth: 3,
};

export function getScopeForTier(tier: number): ProvisioningScope {
  if (tier === 0) return { ...TIER_0_SCOPE, allowedMcpServers: [...TIER_0_SCOPE.allowedMcpServers], allowedJobTypes: [...TIER_0_SCOPE.allowedJobTypes] };
  if (tier === 1) return { ...TIER_1_SCOPE, allowedMcpServers: [...TIER_1_SCOPE.allowedMcpServers], allowedJobTypes: [...TIER_1_SCOPE.allowedJobTypes] };
  if (tier === 2) return { ...TIER_2_SCOPE, allowedMcpServers: [...TIER_2_SCOPE.allowedMcpServers], allowedJobTypes: [...TIER_2_SCOPE.allowedJobTypes] };
  return { ...TIER_3_SCOPE, allowedMcpServers: [...TIER_3_SCOPE.allowedMcpServers], allowedJobTypes: [...TIER_3_SCOPE.allowedJobTypes] };
}

/**
 * Intersect a requested scope with what the leader is permitted to grant.
 * The leader can only delegate capabilities they themselves have.
 * Returns the more restrictive of: the target tier's base scope vs what the
 * leader can grant from their own manifest.
 */
export function intersectScope(
  requested: Partial<ProvisioningScope>,
  leaderScope: ProvisioningScope,
  targetTier: number,
): ProvisioningScope {
  const base = getScopeForTier(targetTier);
  return {
    hasTelegram: base.hasTelegram && (requested.hasTelegram ?? false) && leaderScope.hasTelegram,
    hasDesktop: base.hasDesktop && (requested.hasDesktop ?? base.hasDesktop) && leaderScope.hasDesktop,
    hasVoice: base.hasVoice && (requested.hasVoice ?? false) && leaderScope.hasVoice,
    hasAvatar: base.hasAvatar && (requested.hasAvatar ?? false) && leaderScope.hasAvatar,
    allowedMcpServers: base.allowedMcpServers.filter(s =>
      leaderScope.allowedMcpServers.includes(s) &&
      (requested.allowedMcpServers ?? base.allowedMcpServers).includes(s),
    ),
    allowedJobTypes: base.allowedJobTypes.filter(j =>
      leaderScope.allowedJobTypes.includes(j) &&
      (requested.allowedJobTypes ?? base.allowedJobTypes).includes(j),
    ),
    canAddressUser: base.canAddressUser && leaderScope.canAddressUser,
    canAddressAgents: base.canAddressAgents && leaderScope.canAddressAgents,
    canProvision: base.canProvision && leaderScope.canProvision,
    systemAccess: false, // never delegated
    maxQueueDepth: Math.min(base.maxQueueDepth, leaderScope.maxQueueDepth),
  };
}

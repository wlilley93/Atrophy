import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { USER_DATA } from '../../config';
import { createLogger } from '../../logger';

const log = createLogger('federation-config');

export type TrustTier = 'chat' | 'query' | 'delegate';

export interface FederationLink {
  remote_bot_username: string;
  telegram_group_id: string;
  local_agent: string;
  trust_tier: TrustTier;
  enabled: boolean;
  muted: boolean;
  description: string;
  rate_limit_per_hour: number;
  created_at: string;
}

export interface FederationConfig {
  version: number;
  links: Record<string, FederationLink>;
}

const CONFIG_PATH = path.join(USER_DATA, 'federation.json');

const DEFAULT_LINK: Partial<FederationLink> = {
  trust_tier: 'chat',
  enabled: true,
  muted: false,
  rate_limit_per_hour: 20,
};

export function loadFederationConfig(): FederationConfig {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
      if (raw.version === 1 && raw.links && typeof raw.links === 'object') {
        return raw as FederationConfig;
      }
      log.warn('federation.json has unexpected format - using empty config');
    }
  } catch (e) {
    log.error(`Failed to load federation.json: ${e}`);
  }
  return { version: 1, links: {} };
}

export function saveFederationConfig(config: FederationConfig): void {
  const dir = path.dirname(CONFIG_PATH);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = CONFIG_PATH + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(config, null, 2), { mode: 0o600 });
  fs.renameSync(tmp, CONFIG_PATH);
  log.info(`Saved federation config: ${Object.keys(config.links).length} link(s)`);
}

export function getEnabledLinks(): [string, FederationLink][] {
  const config = loadFederationConfig();
  return Object.entries(config.links).filter(([, link]) => link.enabled);
}

export function getFederationGroupIds(): Set<string> {
  const config = loadFederationConfig();
  const ids = new Set<string>();
  for (const link of Object.values(config.links)) {
    if (link.enabled) ids.add(link.telegram_group_id);
  }
  return ids;
}

export function updateLink(name: string, updates: Partial<FederationLink>): void {
  const config = loadFederationConfig();
  if (!config.links[name]) {
    throw new Error(`Federation link "${name}" not found`);
  }
  config.links[name] = { ...config.links[name], ...updates };
  saveFederationConfig(config);
}

export function addLink(name: string, link: Partial<FederationLink> & Pick<FederationLink, 'remote_bot_username' | 'telegram_group_id' | 'local_agent'>): void {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name)) {
    throw new Error(`Invalid link name: "${name}"`);
  }
  const config = loadFederationConfig();
  if (config.links[name]) {
    throw new Error(`Federation link "${name}" already exists`);
  }
  config.links[name] = {
    ...DEFAULT_LINK,
    description: '',
    created_at: new Date().toISOString(),
    ...link,
  } as FederationLink;
  saveFederationConfig(config);
}

export function removeLink(name: string): void {
  const config = loadFederationConfig();
  if (!config.links[name]) {
    throw new Error(`Federation link "${name}" not found`);
  }
  delete config.links[name];
  saveFederationConfig(config);
}

// ---------------------------------------------------------------------------
// Invite tokens
// ---------------------------------------------------------------------------

const TOKEN_EXPIRY_MS = 24 * 60 * 60 * 1000; // 24 hours
const TOKEN_VERSION = 1;

interface InvitePayload {
  v: number;
  bot: string;       // local bot username
  group: string;     // telegram group chat ID
  agent: string;     // local agent name
  desc: string;      // description
  exp: number;       // expiry timestamp (ms)
  nonce: string;     // one-time random
}

/**
 * Generate a federation invite token.
 *
 * The token encodes the local bot username, group chat ID, agent name,
 * and an expiry timestamp. It is base64url-encoded JSON with an HMAC
 * signature appended. The HMAC key is derived from the bot token
 * (which both parties know once the remote bot is added to the group).
 *
 * The token is single-use by convention - after acceptance, the nonce
 * can be stored to prevent replay. Expires after 24 hours.
 */
export function generateInviteToken(
  localBotUsername: string,
  telegramGroupId: string,
  localAgent: string,
  description: string,
  botToken: string,
): string {
  const payload: InvitePayload = {
    v: TOKEN_VERSION,
    bot: localBotUsername,
    group: telegramGroupId,
    agent: localAgent,
    desc: description,
    exp: Date.now() + TOKEN_EXPIRY_MS,
    nonce: crypto.randomBytes(16).toString('hex'),
  };

  const payloadB64 = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const hmac = crypto.createHmac('sha256', botToken).update(payloadB64).digest('base64url');

  return `atrophy-fed-${payloadB64}.${hmac}`;
}

/**
 * Parse and validate a federation invite token.
 *
 * Returns the decoded payload if valid, or throws with a human-readable
 * error message. Does NOT verify the HMAC - that requires the remote
 * bot token which the accepting party may not have yet. The HMAC is
 * verified by the generating party's instance if needed.
 *
 * Validation checks: format, version, expiry, required fields.
 */
export function parseInviteToken(token: string): {
  remoteBotUsername: string;
  telegramGroupId: string;
  remoteAgent: string;
  description: string;
  expiresAt: number;
} {
  if (!token.startsWith('atrophy-fed-')) {
    throw new Error('Invalid token format - must start with atrophy-fed-');
  }

  const body = token.slice('atrophy-fed-'.length);
  const dotIdx = body.lastIndexOf('.');
  if (dotIdx < 0) {
    throw new Error('Invalid token format - missing signature');
  }

  const payloadB64 = body.slice(0, dotIdx);

  let payload: InvitePayload;
  try {
    payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString('utf-8'));
  } catch {
    throw new Error('Invalid token - corrupted payload');
  }

  if (payload.v !== TOKEN_VERSION) {
    throw new Error(`Unsupported token version: ${payload.v}`);
  }

  if (!payload.bot || !payload.group || !payload.agent) {
    throw new Error('Invalid token - missing required fields');
  }

  if (payload.exp < Date.now()) {
    throw new Error('Token has expired');
  }

  return {
    remoteBotUsername: payload.bot,
    telegramGroupId: payload.group,
    remoteAgent: payload.agent,
    description: payload.desc || '',
    expiresAt: payload.exp,
  };
}

/**
 * Accept a federation invite token - parses it and creates a link.
 * Returns the link name that was created.
 */
export function acceptInviteToken(token: string, localAgent: string): string {
  const parsed = parseInviteToken(token);

  // Generate a link name from the remote bot username
  const linkName = parsed.remoteBotUsername.replace(/_bot$/, '').replace(/[^a-zA-Z0-9_-]/g, '-');

  addLink(linkName, {
    remote_bot_username: parsed.remoteBotUsername,
    telegram_group_id: parsed.telegramGroupId,
    local_agent: localAgent,
    description: parsed.description || `Link from @${parsed.remoteBotUsername}`,
  });

  log.info(`Accepted federation invite: ${linkName} (remote: @${parsed.remoteBotUsername})`);
  return linkName;
}

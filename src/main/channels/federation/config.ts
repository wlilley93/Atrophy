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

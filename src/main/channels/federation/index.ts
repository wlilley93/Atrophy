// src/main/channels/federation/index.ts
import { switchboard } from '../switchboard';
import { createLogger } from '../../logger';
import { getEnabledLinks, getFederationGroupIds, type FederationLink } from './config';
import { startPoller, stopPoller, stopAllPollers, sendFederationResponse, getActivePollers } from './poller';
import { loadFederationConfig } from './config';

const log = createLogger('federation');

let _started = false;

/**
 * Start the federation layer. Called during app boot after startDaemon().
 */
export async function startFederation(): Promise<void> {
  if (_started) return;
  _started = true;

  const links = getEnabledLinks();
  if (links.length === 0) {
    log.info('Federation: no enabled links');
    return;
  }

  for (const [name, link] of links) {
    try {
      // Register the federation response handler with switchboard
      registerFederationHandler(name, link);
      // Start the poller
      await startPoller(name, link);
    } catch (e) {
      log.error(`[${name}] Failed to start federation link: ${e}`);
    }
  }

  log.info(`Federation: ${links.length} link(s) active (${links.map(([n]) => n).join(', ')})`);
}

/**
 * Stop the federation layer. Called during app shutdown.
 */
export function stopFederation(): void {
  if (!_started) return;
  _started = false;

  stopAllPollers();

  // Unregister all federation handlers
  for (const addr of switchboard.getRegisteredAddresses()) {
    if (addr.startsWith('federation:')) {
      switchboard.unregister(addr);
    }
  }

  log.info('Federation stopped');
}

/**
 * Register a switchboard handler for a federation link.
 * When an agent responds to a federation envelope, the response
 * is routed back here and sent to the shared Telegram group.
 */
function registerFederationHandler(linkName: string, link: FederationLink): void {
  const address = `federation:${linkName}`;

  switchboard.register(address, async (envelope) => {
    // This handler receives response envelopes from the agent.
    // The envelope.from is "agent:<name>", envelope.to is "federation:<link>".
    if (!envelope.text) return;

    const replyToId = envelope.metadata?.inReplyTo
      ? (envelope.metadata.telegramMessageId as number | undefined)
      : undefined;

    await sendFederationResponse(linkName, envelope.text, replyToId);
  }, {
    type: 'channel',
    description: `Federation link: ${link.description || linkName}`,
    capabilities: ['federation', 'outbound'],
  });
}

/**
 * Start or restart a single federation link. Used by IPC handlers when
 * links are added or modified via the Settings UI (avoids full app restart).
 */
export async function restartLink(linkName: string): Promise<void> {
  // Stop existing poller if running
  stopPoller(linkName);
  switchboard.unregister(`federation:${linkName}`);

  // Reload config and start if enabled
  const config = loadFederationConfig();
  const link = config.links[linkName];
  if (!link || !link.enabled) {
    log.info(`[${linkName}] Link not found or disabled - not starting poller`);
    return;
  }

  try {
    registerFederationHandler(linkName, link);
    await startPoller(linkName, link);
    _started = true; // Ensure the started flag is set
    log.info(`[${linkName}] Link restarted`);
  } catch (e) {
    log.error(`[${linkName}] Failed to restart link: ${e}`);
  }
}

/**
 * Get the set of Telegram group IDs used by federation.
 * The Telegram daemon should exclude these from its polling.
 */
export { getFederationGroupIds } from './config';

// Re-export for convenience
export { getActivePollers } from './poller';
export {
  loadFederationConfig,
  saveFederationConfig,
  updateLink,
  addLink,
  removeLink,
  type FederationLink,
  type FederationConfig,
  type TrustTier,
} from './config';
export { readTranscript, getTranscriptStats } from './transcript';

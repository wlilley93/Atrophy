/**
 * Per-agent message router.
 *
 * One instance per agent. Sits between the switchboard and the agent's
 * inference engine. Handles inbound filtering (accept/reject), queue
 * depth limits, and outbound permission checks.
 *
 * This is DIFFERENT from agent-manager.ts - the agent-manager handles
 * agent lifecycle (discovery, switching, state). The agent-router handles
 * MESSAGE routing for a specific agent.
 */

import { switchboard, type Envelope } from './switchboard';
import { createLogger } from '../logger';

const log = createLogger('agent-router');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentRouterConfig {
  acceptFrom: string[];       // addresses to accept ("*" = all)
  rejectFrom: string[];       // addresses to block (checked before accept)
  maxQueueDepth: number;      // how many pending messages before rejecting
  systemAccess: boolean;      // can send system commands
  canAddressAgents: boolean;  // can message other agents
}

/**
 * Callback invoked when a message passes filtering and should be processed.
 * Returns the response text (or void for fire-and-forget messages like
 * system context injections).
 */
export type AgentMessageCallback = (envelope: Envelope) => Promise<string | void>;

// ---------------------------------------------------------------------------
// Default configs by agent role
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG: AgentRouterConfig = {
  acceptFrom: ['*'],
  rejectFrom: [],
  maxQueueDepth: 10,
  systemAccess: false,
  canAddressAgents: true,
};

/**
 * Build a router config for a known agent. Xan gets elevated privileges.
 * Other agents get sensible defaults that can be overridden via agent.json.
 */
export function defaultConfigForAgent(agentName: string): AgentRouterConfig {
  if (agentName === 'xan') {
    return {
      acceptFrom: ['*'],
      rejectFrom: [],
      maxQueueDepth: 20,
      systemAccess: true,
      canAddressAgents: true,
    };
  }
  return { ...DEFAULT_CONFIG };
}

// ---------------------------------------------------------------------------
// AgentRouter
// ---------------------------------------------------------------------------

export class AgentRouter {
  private address: string;
  private queueDepth = 0;

  constructor(
    private agentName: string,
    private config: AgentRouterConfig,
    private onMessage: AgentMessageCallback,
  ) {
    this.address = `agent:${agentName}`;

    // Register with switchboard
    switchboard.register(this.address, this.handleInbound.bind(this));

    log.info(
      `[${agentName}] Router created - accept: [${config.acceptFrom.join(', ')}], ` +
      `system: ${config.systemAccess}, agents: ${config.canAddressAgents}`,
    );
  }

  /**
   * Handle an inbound envelope from the switchboard.
   */
  private async handleInbound(envelope: Envelope): Promise<void> {
    // Check reject list first (takes priority over accept)
    if (this.isRejected(envelope.from)) {
      log.debug(`[${this.agentName}] Rejected message from ${envelope.from}`);
      return;
    }

    // Check accept list
    if (!this.isAccepted(envelope.from)) {
      log.debug(`[${this.agentName}] Not accepted from ${envelope.from}`);
      return;
    }

    // Check queue depth
    if (this.queueDepth >= this.config.maxQueueDepth) {
      log.warn(`[${this.agentName}] Queue full (${this.queueDepth}/${this.config.maxQueueDepth}), dropping message from ${envelope.from}`);
      return;
    }

    // System messages are injected as context - don't run inference
    if (envelope.type === 'system') {
      log.debug(`[${this.agentName}] System message from ${envelope.from}: "${envelope.text.slice(0, 80)}"`);
      // Fire-and-forget - the callback decides how to inject as context
      try {
        await this.onMessage(envelope);
      } catch (err) {
        log.error(`[${this.agentName}] System message handler error: ${err}`);
      }
      return;
    }

    // User or agent message - run inference
    this.queueDepth++;
    try {
      const response = await this.onMessage(envelope);

      // Route response back via switchboard using envelope.replyTo
      if (response && envelope.replyTo) {
        const responseEnvelope = switchboard.createEnvelope(
          this.address,
          envelope.replyTo,
          response,
          {
            type: 'agent',
            priority: 'normal',
            metadata: {
              inReplyTo: envelope.id,
              agentName: this.agentName,
            },
          },
        );
        await switchboard.route(responseEnvelope);
      }
    } catch (err) {
      log.error(`[${this.agentName}] Message handler error: ${err}`);
    } finally {
      this.queueDepth--;
    }
  }

  /**
   * Send a message from this agent to another address.
   */
  async sendMessage(to: string, text: string, type: Envelope['type'] = 'agent'): Promise<void> {
    // Check if this agent has permission to address other agents
    if (to.startsWith('agent:') && !this.config.canAddressAgents) {
      log.warn(`[${this.agentName}] Not permitted to address agents (tried: ${to})`);
      return;
    }

    // Check if this agent can send system messages
    if (to === 'system' && !this.config.systemAccess) {
      log.warn(`[${this.agentName}] Not permitted to send system messages`);
      return;
    }

    const envelope = switchboard.createEnvelope(
      this.address,
      to,
      text,
      {
        type,
        priority: type === 'system' ? 'system' : 'normal',
        replyTo: this.address,
      },
    );

    await switchboard.route(envelope);
  }

  /**
   * Broadcast a message to all agents. Only permitted if systemAccess is true.
   */
  async broadcast(text: string): Promise<void> {
    if (!this.config.systemAccess) {
      log.warn(`[${this.agentName}] Not permitted to broadcast (no systemAccess)`);
      return;
    }

    const envelope = switchboard.createEnvelope(
      this.address,
      'agent:*',
      text,
      {
        type: 'system',
        priority: 'system',
      },
    );

    await switchboard.route(envelope);
  }

  /**
   * Tear down this router - unregister from switchboard.
   */
  destroy(): void {
    switchboard.unregister(this.address);
    log.info(`[${this.agentName}] Router destroyed`);
  }

  // ── Permission checks ──

  private isRejected(from: string): boolean {
    for (const pattern of this.config.rejectFrom) {
      if (this.matchAddress(pattern, from)) return true;
    }
    return false;
  }

  private isAccepted(from: string): boolean {
    for (const pattern of this.config.acceptFrom) {
      if (this.matchAddress(pattern, from)) return true;
    }
    return false;
  }

  /**
   * Match an address against a pattern.
   * "*" matches everything.
   * "agent:*" matches any address starting with "agent:".
   * "cron:*" matches any address starting with "cron:".
   * Exact match otherwise.
   */
  private matchAddress(pattern: string, address: string): boolean {
    if (pattern === '*') return true;
    if (pattern.endsWith(':*')) {
      return address.startsWith(pattern.slice(0, -1));
    }
    return pattern === address;
  }
}

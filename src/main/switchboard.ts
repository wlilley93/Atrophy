/**
 * Central message switchboard - all messages flow through here.
 *
 * Every message is wrapped in an Envelope with source/destination addresses.
 * Handlers register for address patterns. The switchboard routes envelopes
 * to matching handlers, supports wildcards for broadcast, and logs
 * everything for debugging.
 *
 * Singleton - import { switchboard } from './switchboard'.
 */

import { v4 as uuidv4 } from 'uuid';
import { createLogger } from './logger';

const log = createLogger('switchboard');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Envelope {
  id: string;            // unique message ID (uuid)
  from: string;          // source address (e.g. "telegram:xan", "desktop:companion")
  to: string;            // destination address (e.g. "agent:xan", "agent:*")
  text: string;          // message content
  type: 'user' | 'agent' | 'system';
  priority: 'normal' | 'high' | 'system';
  replyTo?: string;      // where to send response
  timestamp: number;     // Date.now()
  metadata?: Record<string, unknown>;
}

export type MessageHandler = (envelope: Envelope) => Promise<void>;

// ---------------------------------------------------------------------------
// Switchboard
// ---------------------------------------------------------------------------

const MAX_LOG_SIZE = 200;

class Switchboard {
  private handlers: Map<string, MessageHandler> = new Map();
  private messageLog: Envelope[] = [];

  /**
   * Register a handler for an address pattern.
   * Supports exact match ("agent:xan") and wildcard patterns ("agent:*").
   * Wildcard handlers are invoked when a message targets a broadcast
   * address like "agent:*", or when no exact match is found.
   */
  register(address: string, handler: MessageHandler): void {
    if (this.handlers.has(address)) {
      log.warn(`Overwriting existing handler for ${address}`);
    }
    this.handlers.set(address, handler);
    log.info(`Registered handler: ${address}`);
  }

  /**
   * Remove a handler for an address.
   */
  unregister(address: string): void {
    if (this.handlers.delete(address)) {
      log.info(`Unregistered handler: ${address}`);
    }
  }

  /**
   * Route an envelope to its destination handler(s).
   *
   * Routing logic:
   * - Exact match: "agent:xan" matches handler registered as "agent:xan"
   * - Broadcast: "agent:*" delivers to ALL handlers whose address starts
   *   with "agent:" (excluding the sender)
   * - System messages to "system" are handled by the system handler if
   *   one is registered
   */
  async route(envelope: Envelope): Promise<void> {
    // Log the message
    this.messageLog.push(envelope);
    if (this.messageLog.length > MAX_LOG_SIZE) {
      this.messageLog = this.messageLog.slice(-MAX_LOG_SIZE);
    }

    log.debug(
      `Route: ${envelope.from} -> ${envelope.to} [${envelope.type}/${envelope.priority}] "${envelope.text.slice(0, 80)}"`,
    );

    const target = envelope.to;

    // Broadcast - deliver to all matching handlers
    if (target.endsWith(':*')) {
      const prefix = target.slice(0, -1); // "agent:*" -> "agent:"
      const delivered: string[] = [];

      for (const [address, handler] of this.handlers) {
        // Match handlers that start with the prefix (e.g. "agent:xan" matches "agent:")
        // Skip the sender to prevent echo loops
        if (address.startsWith(prefix) && address !== envelope.from) {
          try {
            await handler(envelope);
            delivered.push(address);
          } catch (err) {
            log.error(`Handler error for ${address}: ${err}`);
          }
        }
      }

      if (delivered.length === 0) {
        log.warn(`No handlers matched broadcast ${target}`);
      } else {
        log.debug(`Broadcast ${target} delivered to: ${delivered.join(', ')}`);
      }
      return;
    }

    // Exact match
    const handler = this.handlers.get(target);
    if (handler) {
      try {
        await handler(envelope);
      } catch (err) {
        log.error(`Handler error for ${target}: ${err}`);
      }
      return;
    }

    log.warn(`No handler for address: ${target}`);
  }

  /**
   * Record an envelope in the message log without delivering it.
   * Useful when the caller handles delivery directly (e.g. desktop GUI
   * inference) but still wants the message recorded for observability.
   */
  record(envelope: Envelope): void {
    this.messageLog.push(envelope);
    if (this.messageLog.length > MAX_LOG_SIZE) {
      this.messageLog = this.messageLog.slice(-MAX_LOG_SIZE);
    }
    log.debug(
      `Record: ${envelope.from} -> ${envelope.to} [${envelope.type}] "${envelope.text.slice(0, 80)}"`,
    );
  }

  /**
   * Helper to create an Envelope with sensible defaults.
   */
  createEnvelope(
    from: string,
    to: string,
    text: string,
    opts?: Partial<Envelope>,
  ): Envelope {
    return {
      id: uuidv4(),
      from,
      to,
      text,
      type: opts?.type || 'user',
      priority: opts?.priority || 'normal',
      replyTo: opts?.replyTo || from,
      timestamp: Date.now(),
      metadata: opts?.metadata,
    };
  }

  /**
   * Get recent messages for debugging/inspection.
   */
  getRecentMessages(count?: number): Envelope[] {
    return this.messageLog.slice(-(count || 50));
  }

  /**
   * Check if a handler is registered for a given address.
   */
  hasHandler(address: string): boolean {
    return this.handlers.has(address);
  }

  /**
   * Get all registered handler addresses.
   */
  getRegisteredAddresses(): string[] {
    return Array.from(this.handlers.keys());
  }
}

export const switchboard = new Switchboard();

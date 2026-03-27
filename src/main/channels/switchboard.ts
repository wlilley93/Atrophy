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
import { USER_DATA } from '../config';
import { createLogger } from '../logger';

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

/**
 * Service directory entry - metadata about a registered handler.
 * Agents can query the directory to discover available channels,
 * other agents, and system services.
 */
export interface ServiceEntry {
  address: string;       // e.g. "telegram:xan", "agent:companion"
  type: 'channel' | 'agent' | 'system' | 'webhook' | 'mcp';
  description: string;   // human-readable description
  capabilities?: string[]; // what this service can do
  registeredAt: number;  // timestamp
}

// ---------------------------------------------------------------------------
// Switchboard
// ---------------------------------------------------------------------------

const MAX_LOG_SIZE = 200;
const QUEUE_POLL_INTERVAL = 2000; // ms

class Switchboard {
  private handlers: Map<string, MessageHandler> = new Map();
  private directory: Map<string, ServiceEntry> = new Map();
  private messageLog: Envelope[] = [];
  private queuePollTimer: ReturnType<typeof setInterval> | null = null;

  /**
   * Register a handler for an address with service metadata.
   * Supports exact match ("agent:xan") and wildcard patterns ("agent:*").
   */
  register(address: string, handler: MessageHandler, meta?: Partial<ServiceEntry>): void {
    if (this.handlers.has(address)) {
      log.warn(`Overwriting existing handler for ${address}`);
    }
    this.handlers.set(address, handler);

    // Infer service type from address prefix
    const inferType = (): ServiceEntry['type'] => {
      if (address.startsWith('agent:')) return 'agent';
      if (address.startsWith('telegram:') || address.startsWith('desktop:')) return 'channel';
      if (address.startsWith('webhook:')) return 'webhook';
      if (address.startsWith('mcp:')) return 'mcp';
      return 'system';
    };

    this.directory.set(address, {
      address,
      type: meta?.type || inferType(),
      description: meta?.description || address,
      capabilities: meta?.capabilities,
      registeredAt: Date.now(),
    });

    log.info(`Registered handler: ${address} (${this.directory.get(address)!.type})`);
  }

  /**
   * Remove a handler for an address.
   */
  unregister(address: string): void {
    if (this.handlers.delete(address)) {
      this.directory.delete(address);
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

  // -----------------------------------------------------------------------
  // Service directory - agents can discover available channels and services
  // -----------------------------------------------------------------------

  /**
   * Get the full service directory. Agents call this via MCP to discover
   * what channels, agents, and services are available for routing.
   */
  getDirectory(): ServiceEntry[] {
    return Array.from(this.directory.values());
  }

  /**
   * Get directory entries filtered by type.
   */
  getDirectoryByType(type: ServiceEntry['type']): ServiceEntry[] {
    return this.getDirectory().filter(e => e.type === type);
  }

  /**
   * Get a single service entry by address.
   */
  getService(address: string): ServiceEntry | undefined {
    return this.directory.get(address);
  }

  // -----------------------------------------------------------------------
  // MCP queue polling - processes envelopes from Python MCP servers
  // -----------------------------------------------------------------------

  /**
   * Start polling the MCP queue file for envelopes from agent MCP tools.
   * The MCP memory server (Python) writes to ~/.atrophy/.switchboard_queue.json
   * and this polls it every 2 seconds.
   */
  startQueuePolling(): void {
    if (this.queuePollTimer) return;

    const fs = require('fs');
    const path = require('path');
    const queuePath = path.join(
      USER_DATA,
      '.switchboard_queue.json',
    );

    this.queuePollTimer = setInterval(async () => {
      try {
        if (!fs.existsSync(queuePath)) return;

        // Atomic read-and-clear: rename the queue file to a temp path,
        // then restore an empty queue. This prevents a TOCTOU race where
        // the Python MCP server appends envelopes between our read and
        // our clear, which would silently drop those messages.
        const tmpPath = queuePath + `.poll-${process.pid}-${Date.now()}`;
        try {
          fs.renameSync(queuePath, tmpPath);
        } catch {
          // File may have been removed between existsSync and rename
          return;
        }
        // Restore empty queue immediately so MCP servers can keep writing
        fs.writeFileSync(queuePath, '[]');

        const raw = fs.readFileSync(tmpPath, 'utf8');
        try { fs.unlinkSync(tmpPath); } catch { /* best-effort cleanup */ }

        let envelopes: Envelope[];
        try {
          envelopes = JSON.parse(raw);
        } catch (parseErr) {
          log.error(`Queue file contained malformed JSON - ${raw.length} bytes dropped: ${parseErr}`);
          log.error(`Queue raw content (first 500 chars): ${raw.slice(0, 500)}`);
          return;
        }
        if (envelopes.length === 0) return;

        // Process each envelope - only allow mcp:* and cron:* origins from queue
        for (const env of envelopes) {
          if (env.from && !env.from.startsWith('mcp:') && !env.from.startsWith('cron:')) {
            log.warn(`Queue: rejected envelope with non-MCP origin: ${env.from}`);
            continue;
          }
          log.info(`Queue: ${env.from} -> ${env.to} "${env.text?.slice(0, 60)}"`);
          try {
            await this.route(env);
          } catch (err) {
            log.error(`Queue envelope error: ${err}`);
          }
        }
      } catch {
        // File might be locked or malformed - skip this cycle
      }
    }, QUEUE_POLL_INTERVAL);

    log.info('Started MCP queue polling');
  }

  /**
   * Stop queue polling.
   */
  stopQueuePolling(): void {
    if (this.queuePollTimer) {
      clearInterval(this.queuePollTimer);
      this.queuePollTimer = null;
      log.info('Stopped MCP queue polling');
    }
  }

  /**
   * Write the service directory and recent message log to disk so MCP
   * servers can read them for query_status and discover actions.
   */
  writeStateForMCP(): void {
    const fs = require('fs');
    const path = require('path');
    const stateDir = USER_DATA;

    // Write directory
    const dirPath = path.join(stateDir, '.switchboard_directory.json');
    try {
      fs.writeFileSync(dirPath, JSON.stringify(this.getDirectory(), null, 2));
    } catch {
      // Non-fatal
    }

    // Write recent log
    const logPath = path.join(stateDir, '.switchboard_log.json');
    try {
      const recent = this.messageLog.slice(-50).map(e => ({
        from: e.from,
        to: e.to,
        text: e.text.slice(0, 120),
        type: e.type,
        timestamp: e.timestamp,
      }));
      fs.writeFileSync(logPath, JSON.stringify(recent, null, 2));
    } catch {
      // Non-fatal
    }
  }
}

export const switchboard = new Switchboard();

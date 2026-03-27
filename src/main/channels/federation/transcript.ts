import * as fs from 'fs';
import * as path from 'path';
import { USER_DATA } from '../../config';
import { createLogger } from '../../logger';

const log = createLogger('federation-transcript');

const FEDERATION_DIR = path.join(USER_DATA, 'federation');
const MAX_SIZE_BYTES = 10 * 1024 * 1024; // 10MB

export interface TranscriptEntry {
  timestamp: string;
  direction: 'inbound' | 'outbound';
  from_bot: string;
  to_bot: string;
  text: string;
  telegram_message_id?: number;
  inference_triggered: boolean;
  response_text?: string;
  trust_tier: string;
  skipped_reason?: string;
}

function transcriptPath(linkName: string): string {
  return path.join(FEDERATION_DIR, linkName, 'transcript.jsonl');
}

function ensureDir(linkName: string): void {
  fs.mkdirSync(path.join(FEDERATION_DIR, linkName), { recursive: true });
}

export function appendTranscript(linkName: string, entry: TranscriptEntry): void {
  ensureDir(linkName);
  const fp = transcriptPath(linkName);

  // Rotate if over size limit
  try {
    if (fs.existsSync(fp)) {
      const stat = fs.statSync(fp);
      if (stat.size > MAX_SIZE_BYTES) {
        const prev = fp + '.prev';
        try { fs.unlinkSync(prev); } catch { /* ok */ }
        fs.renameSync(fp, prev);
        log.info(`Rotated transcript for ${linkName}`);
      }
    }
  } catch { /* non-fatal */ }

  const line = JSON.stringify(entry) + '\n';
  fs.appendFileSync(fp, line);
}

export function readTranscript(linkName: string, limit = 100, offset = 0): TranscriptEntry[] {
  const fp = transcriptPath(linkName);
  if (!fs.existsSync(fp)) return [];

  try {
    const lines = fs.readFileSync(fp, 'utf-8').trim().split('\n');
    const entries: TranscriptEntry[] = [];
    const start = Math.max(0, lines.length - offset - limit);
    const end = lines.length - offset;
    for (let i = start; i < end; i++) {
      try {
        entries.push(JSON.parse(lines[i]));
      } catch { /* skip malformed lines */ }
    }
    return entries;
  } catch {
    return [];
  }
}

export function getTranscriptStats(linkName: string): { messageCount: number; lastMessage: string | null; sizeBytes: number } {
  const fp = transcriptPath(linkName);
  if (!fs.existsSync(fp)) return { messageCount: 0, lastMessage: null, sizeBytes: 0 };
  try {
    const stat = fs.statSync(fp);
    const lines = fs.readFileSync(fp, 'utf-8').trim().split('\n').filter(Boolean);
    const last = lines.length > 0 ? JSON.parse(lines[lines.length - 1]) : null;
    return {
      messageCount: lines.length,
      lastMessage: last?.timestamp || null,
      sizeBytes: stat.size,
    };
  } catch {
    return { messageCount: 0, lastMessage: null, sizeBytes: 0 };
  }
}

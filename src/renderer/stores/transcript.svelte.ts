/**
 * Message history for the transcript display.
 */

export interface Message {
  id: number;
  role: 'user' | 'agent' | 'system' | 'divider';
  content: string;
  timestamp: number;
  revealed: number; // chars revealed so far (for animation)
  complete: boolean;
}

let _nextId = 0;

export const transcript = $state({
  messages: [] as Message[],
  autoScroll: true,
});

export function addMessage(role: Message['role'], content: string): Message {
  const msg: Message = {
    id: _nextId++,
    role,
    content,
    timestamp: Date.now(),
    revealed: role === 'agent' ? 0 : content.length,
    complete: role !== 'agent',
  };
  transcript.messages.push(msg);
  return msg;
}

export function appendToLast(text: string): void {
  const msgs = transcript.messages;
  if (msgs.length === 0) return;
  const last = msgs[msgs.length - 1];
  if (last.role === 'agent' && !last.complete) {
    last.content += text;
  }
}

export function completeLast(): void {
  const msgs = transcript.messages;
  if (msgs.length === 0) return;
  const last = msgs[msgs.length - 1];
  last.complete = true;
  last.revealed = last.content.length;
}

export function addDivider(text: string): void {
  addMessage('divider', text);
}

export function clearTranscript(): void {
  transcript.messages = [];
  transcript.autoScroll = true;
}

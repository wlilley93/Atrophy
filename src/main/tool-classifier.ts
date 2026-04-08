/**
 * Keyword-based classifier that predicts which MCP tool categories
 * a user message will need. Pure regex - no model calls.
 *
 * Used by the inference path to filter MCP tools per turn,
 * reducing tool token overhead from ~5000 to ~800 tokens.
 */

import type { ToolCategory } from './mcp-registry';

export const TOTAL_CATEGORIES = 9;

export function predictToolCategories(userMessage: string): Set<ToolCategory> {
  const cats = new Set<ToolCategory>(['memory', 'meta']);

  const msg = userMessage.toLowerCase();

  if (/\b(meeting|calendar|schedule|appointment|event|tomorrow|today|this week|next week|morning|afternoon|busy|free|available)\b/.test(msg)) {
    cats.add('calendar');
  }

  if (/\b(email|mail|inbox|send|draft|reply|forward|gmail|message to)\b/.test(msg)) {
    cats.add('email');
  }

  if (/\b(run|execute|command|terminal|shell|script|process|file|directory|folder|install|pip|npm|brew)\b/.test(msg)) {
    cats.add('shell');
  }

  if (/\b(github|git|repo|repository|pull request|pr\b|issue|commit|branch|merge|code review)\b/.test(msg)) {
    cats.add('github');
  }

  if (/\b(browse|website|web|url|navigate|scrape|page|screenshot|click|download)\b/.test(msg)) {
    cats.add('browser');
  }

  if (/\b(intel|intelligence|brief|assessment|conflict|military|defence|defense|ontology|entity|signal|maritime|ship|threat|geopolitical|sanctions|weapon|nuclear|missile)\b/.test(msg)) {
    cats.add('intel');
  }

  if (/\b(contact|contacts|phone|address|person|people|who is)\b/.test(msg)) {
    cats.add('contacts');
  }

  return cats;
}

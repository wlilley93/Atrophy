/**
 * Four-tier prompt resolution: Obsidian skills -> local skills -> user prompts -> bundle prompts.
 * Port of core/prompts.py.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig, BUNDLE_ROOT } from './config';

// ---------------------------------------------------------------------------
// Search directories (resolved lazily)
// ---------------------------------------------------------------------------

function getSearchDirs(): string[] {
  const config = getConfig();
  const dirs: string[] = [];

  // Tier 1: Obsidian skills
  if (config.OBSIDIAN_AVAILABLE) {
    const obsSkills = path.join(config.OBSIDIAN_AGENT_DIR, 'skills');
    if (fs.existsSync(obsSkills)) dirs.push(obsSkills);
  }

  // Tier 2: Local skills (~/.atrophy/agents/<name>/skills/)
  const localSkills = path.join(config.DATA_DIR, '..', 'skills');
  if (fs.existsSync(localSkills)) dirs.push(localSkills);

  // Tier 3: User prompts (~/.atrophy/agents/<name>/prompts/)
  const userPrompts = path.join(config.DATA_DIR, '..', 'prompts');
  if (fs.existsSync(userPrompts)) dirs.push(userPrompts);

  // Tier 4: Bundle prompts (agents/<name>/prompts/)
  // AGENT_DIR may be the user dir if user has agent.json, so also check BUNDLE_ROOT
  const agentDirPrompts = path.join(config.AGENT_DIR, 'prompts');
  if (fs.existsSync(agentDirPrompts)) dirs.push(agentDirPrompts);
  const bundlePrompts = path.join(BUNDLE_ROOT, 'agents', config.AGENT_NAME, 'prompts');
  if (bundlePrompts !== agentDirPrompts && fs.existsSync(bundlePrompts)) dirs.push(bundlePrompts);

  // Tier 5: Personal agents (agents-personal/<name>/prompts/)
  // Personal agents keep bundled prompts separate from the standard agents/ dir
  const personalPrompts = path.join(BUNDLE_ROOT, 'agents-personal', config.AGENT_NAME, 'prompts');
  if (personalPrompts !== agentDirPrompts && personalPrompts !== bundlePrompts
      && fs.existsSync(personalPrompts)) {
    dirs.push(personalPrompts);
  }

  return dirs;
}

// ---------------------------------------------------------------------------
// Load prompt by name
// ---------------------------------------------------------------------------

export function loadPrompt(name: string, fallback = ''): string {
  const dirs = getSearchDirs();

  // Try with and without .md extension
  const candidates = name.endsWith('.md') ? [name] : [`${name}.md`, name];

  for (const dir of dirs) {
    for (const candidate of candidates) {
      const filePath = path.join(dir, candidate);
      try {
        if (fs.existsSync(filePath)) {
          const content = fs.readFileSync(filePath, 'utf-8').trim();
          if (content) return content;
        }
      } catch { /* skip */ }
    }
  }

  return fallback;
}

// ---------------------------------------------------------------------------
// Load all skill files from a directory
// ---------------------------------------------------------------------------

export function loadSkillFiles(exclude = ['system.md', 'system_prompt.md']): string[] {
  const dirs = getSearchDirs();
  const loaded = new Set<string>();
  const results: string[] = [];

  for (const dir of dirs) {
    try {
      for (const file of fs.readdirSync(dir)) {
        if (!file.endsWith('.md')) continue;
        if (exclude.includes(file)) continue;
        if (loaded.has(file)) continue;

        const content = fs.readFileSync(path.join(dir, file), 'utf-8').trim();
        if (content) {
          results.push(content);
          loaded.add(file);
        }
      }
    } catch { /* skip */ }
  }

  return results;
}

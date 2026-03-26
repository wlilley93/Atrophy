# Defence Org Upgrade and Agent Reliability Infrastructure

**Date:** 2026-03-26
**Status:** In Progress

## Overview

Three-part upgrade covering agent reliability infrastructure (prevents bugs when agents bootstrap their own tools), Defence org operational activation (Montgomery's full capability), and system-wide patterns for all tier 1 org principals.

---

## Part 1: Completed - Agent Reliability Infrastructure

### Script Template System
- Created `scripts/agents/shared/template.py` - correct boilerplate for all new agent scripts
- Provides: portable path resolution, shared utility imports, logging, error handling
- Agents creating scripts should copy this template

### Shared Utilities Created
- `scripts/agents/shared/credentials.py` - Telegram auth from env vars (not manifest parsing)
- `scripts/agents/shared/telegram_utils.py` - send_telegram(), send_voice_note() with message splitting
- `scripts/agents/shared/claude_cli.py` - unified Claude CLI wrapper (pre-existing)

### Credential Fix
- Fixed 16 scripts across 8 agent directories that read non-existent keys from agent.json
- All now use the shared credentials module

### Hardcoded Path Fix
- Fixed 19 scripts with /Users/williamlilley hardcoded
- All now use Path(__file__).resolve() chains and shutil.which()

---

## Part 2: Completed - Montgomery Job Registration

Montgomery had 14 scripts but only 3 registered as jobs. Now all operational scripts are registered:

### Sensor Grid (interval-based, always running)
| Job | Interval | Script | Purpose |
|-----|----------|--------|---------|
| worldmonitor_fast | 15m | worldmonitor_poll.py --tier fast | High-priority: flights, vessels, alerts, GPS |
| worldmonitor_medium | 45m | worldmonitor_poll.py --tier medium | Secondary: bootstrap, conflicts, thermal |
| worldmonitor_slow | 4h | worldmonitor_poll.py --tier slow | Deep: economic, trade, displacement |
| ship_track_alert | 15m | ship_track_alert.py | AIS maritime: 5 vector chokepoint tracking |

### Situational Awareness (interval-based)
| Job | Interval | Script | Purpose |
|-----|----------|--------|---------|
| three_hour_update | 3h | three_hour_update.py | Regular posture check-in |
| dashboard_brief | 4h | dashboard_brief.py --mode send | Full Claude-driven assessment |
| commission_dispatcher | 4h | commission_dispatcher.py | Process open research commissions |

### Scheduled Reports (cron-based)
| Job | Schedule | Script | Purpose |
|-----|----------|--------|---------|
| parliamentary_monitor | Weekdays 08:00 | parliamentary_monitor.py | UK Hansard defence/foreign affairs |
| competitor_scan | Weekdays 09:00 | competitor_scan.py | Think tank publication monitoring |
| weekly_digest | Monday 07:00 | weekly_digest.py | Full Meridian Institute weekly |
| weekly_conflicts | Wednesday 08:00 | weekly_conflicts.py | Rotating conflict deep-dive |
| track_record | Friday 10:00 | track_record.py extract | Prediction extraction |
| process_audit | 1st Monday 10:00 | process_audit.py | Monthly self-assessment |

### Shared Agent Jobs (added from Companion/Xan baseline)
| Job | Schedule/Interval | Script | Purpose |
|-----|-------------------|--------|---------|
| observer | 15m interval | shared/observer.py | Fact extraction from conversation |
| heartbeat | 30m interval | shared/heartbeat.py | Proactive check-in evaluation |
| sleep_cycle | 03:00 daily | shared/sleep_cycle.py | Nightly memory reconciliation |
| introspect | 03:33 daily | shared/introspect.py | Journal reflection to Obsidian |
| evolve | 03:00 1st of month | shared/evolve.py | Monthly soul/system prompt revision |

### Not Registered (intentionally)
- `flash_report.py` - event-triggered by WorldMonitor CRITICAL items, not cron-schedulable
- `competitor_synthesis.py` - called by competitor_scan.py as a follow-up step
- `commissioning.py` - utility script for manual commission management

---

## Part 3: Future Work - Defence Org Sub-Agent Activation

### Current State
Montgomery is the sole active agent in the defence org. He references 11 sub-agents in his commissioning pipeline and ambassador polling, but none are instantiated as real agents.

### Sub-Agents to Activate

**Tier 2 Regional Research Fellows:**
- rf_russia_ukraine - Daily battlefield reporting
- rf_gulf_iran_israel - Monthly deep-dive papers
- rf_european_security - Weekly European security assessment
- rf_indo_pacific - Weekly Indo-Pacific assessment
- rf_eu_nordic_monitor - Comprehensive EU/Nordic monitoring

**Tier 2 Specialists:**
- economic_io - Friday economic intelligence (sanctions, trade, energy)
- sigint_analyst - 15-min SIGINT cycle (flights, jamming, AIS dark events)
- librarian - Entity taxonomy maintenance in intelligence.db

**Tier 2 Quality Assurance:**
- red_team - Monday devil's advocate review of assessments
- chief_of_staff - Daily triage + contradiction checking

**Tier 3 (ephemeral):**
- ambassador agents (10) - Diplomatic signal polling, stateless

### Activation Sequence
1. Create each sub-agent via `agent:create` with correct org assignment
2. Each gets: memory MCP, defence_sources MCP (regional fellows also get worldmonitor)
3. Register their scripts as jobs
4. Wire them into the switchboard with Montgomery as their principal
5. Commission dispatcher routes work to them automatically

### What This Enables
- Montgomery synthesizes across tracks instead of doing everything himself
- Research Fellows produce regional assessments that feed into the weekly digest
- Red Team challenges assessments before they reach Will
- Chief of Staff handles coordination overhead
- The commission pipeline actually routes to real agents instead of falling back to Montgomery
- Track record system can measure accuracy per analyst, not just Montgomery

---

## Part 4: Future Work - Org Owner System Prompt Injection

When an agent has `can_provision: true`, their system prompt should include:

```
## Script Creation Guidelines

When creating scripts for your organisation:
1. Use the template at scripts/agents/shared/template.py
2. Load credentials via: from shared.credentials import load_telegram_credentials
3. Send Telegram via: from shared.telegram_utils import send_telegram
4. Call Claude via: from shared.claude_cli import call_claude
5. NEVER read agent.json directly for credentials
6. NEVER hardcode absolute paths
7. ALWAYS register scripts as jobs in your manifest

Available shared utilities:
- shared/credentials.py - Telegram auth
- shared/telegram_utils.py - Message sending
- shared/claude_cli.py - Claude inference
- shared/template.py - Script boilerplate
```

This prevents the class of bugs found in Montgomery's self-bootstrapped scripts.

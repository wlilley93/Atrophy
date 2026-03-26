# Meridian Intelligence Institute - System Handover

**Current state as of 25 March 2026**

---

## What This Is

The Meridian Intelligence Institute is the analytical operation running inside the General Montgomery agent. It is not a news aggregator. Its founding objective is multi-plane synthesis: taking raw intelligence from six research tracks and producing interpretation - positions defended with evidence, not summaries.

The six tracks are:
1. UK Defence Posture
2. European Security Architecture
3. Russia-Ukraine
4. Gulf-Iran-Israel
5. Indo-Pacific Tilt
6. Economic Security

---

## Agents and Their Roles

### General Montgomery (Tier 1, Secretary of Defence)
The principal analyst. Runs in Telegram topic. Handles all direct interaction.
- Config: `~/.atrophy/agents/general_montgomery/data/agent.json`
- DB: `~/.atrophy/agents/general_montgomery/data/intelligence.db`
- Scripts: `scripts/agents/general_montgomery/`

### Chief of Staff
Oversight and contradiction detection. No persistent conversation - fires scheduled scripts only.
- Scripts: `scripts/agents/chief_of_staff/`

### Librarian
Entity enrichment and taxonomy. Runs silently in background.
- Scripts: `scripts/agents/librarian/`

### Red Team
Adversarial challenge layer. Reviews weekly digest every Monday and argues the opposing case.
- Scripts: `scripts/agents/red_team/`

### Economic I/O
Economic intelligence track. Sanctions, trade corridors, energy prices.
- Scripts: `scripts/agents/economic_io/`

### Ambassadors
Country desk updates. Polls each watched country weekly for standing assessment.
- Scripts: `scripts/agents/ambassadors/`

### Research Fellows (RF agents)
One per track. Produce weekly (or monthly) assessments from WorldMonitor data + DB context.

| Agent | Track | Cadence |
|-------|-------|---------|
| `rf_uk_defence` | Track 1: UK Defence | Weekly (Thursday 06:00) |
| `rf_european_security` | Track 2: European Security | Weekly (Thursday 06:00) |
| `rf_russia_ukraine` | Track 3: Russia-Ukraine | Daily |
| `rf_gulf_iran_israel` | Track 4: Gulf-Iran-Israel | Monthly |
| `rf_indo_pacific` | Track 5: Indo-Pacific | Weekly (Friday 06:00) |

### Viz Agent
PNG chart generation for Telegram mobile delivery. Matplotlib/networkx.
- Scripts: `scripts/agents/viz_agent/`

---

## Full Job Schedule

All jobs run via the Atrophy cron runner. Times are local (Europe/London assumed).

### Continuous / Interval

| Job | Interval | Script | Purpose |
|-----|----------|--------|---------|
| `worldmonitor_fast` | 15 min | `worldmonitor_poll.py --tier fast` | High-priority source polling |
| `worldmonitor_medium` | 45 min | `worldmonitor_poll.py --tier medium` | Secondary source analysis |
| `worldmonitor_slow` | 4 hr | `worldmonitor_poll.py --tier slow` | Deep pattern review |
| `dashboard_refresh` | 15 min | `dashboard_brief.py --mode refresh` | Updates brief data, fires only on breaking threshold |
| `dashboard_brief` | 4 hr | `dashboard_brief.py --mode send` | Full brief with LLM assessment |
| `ship_track_alert` | 30 min | `ship_track_alert.py` | Five-vector AIS monitoring (Hormuz, CENTCOM, Black Sea, grain corridor, Red Sea) |
| `flash_report` | 15 min | `flash_report.py` | Event-triggered flash on CRITICAL/OREF surge |

### Cron

| Job | Schedule | Script | Purpose |
|-----|----------|--------|---------|
| `weekly_digest` | Mon 07:00 | `weekly_digest.py` | Full week across all six tracks + week-ahead |
| `track_record_extract` | Mon 07:30 | `track_record.py extract` | Extract predictions from new briefs |
| `weekly_conflicts` | Mon 08:00 | `weekly_conflicts.py` | Rotates through conflict watchlist |
| `parliamentary_monitor` | Weekdays 08:00 | `parliamentary_monitor.py` | Hansard scrape, defence/foreign affairs |
| `competitor_scan` | Weekdays 09:00 | `competitor_scan.py` | RSS from think tanks, synthesis layer |
| `process_audit` | First Mon 10:00 | `process_audit.py` | Monthly institutional self-assessment |
| `track_record_review` | First Mon 10:30 | `track_record.py review` | Review predictions older than 30 days |
| `economic_weekly` | Friday 16:00 | `economic_weekly.py` | Sanctions, trade, energy prices |

### RF Agent Schedule (separate agent.json files)

| Job | Schedule | Script |
|-----|----------|--------|
| RF UK Defence weekly | Thursday 06:00 | `rf_uk_defence/weekly_posture.py` |
| RF European Security weekly | Thursday 06:00 | `rf_european_security/weekly_security.py` |
| RF Russia-Ukraine daily | Weekdays 06:30 | `rf_russia_ukraine/daily_battlefield.py` |
| RF Gulf-Iran-Israel monthly | 1st of month 07:00 | `rf_gulf_iran_israel/monthly_paper.py` |
| RF Indo-Pacific weekly | Friday 06:00 | `rf_indo_pacific/weekly_indopacific.py` |

### Chief of Staff Schedule

| Job | Schedule | Script |
|-----|----------|--------|
| Daily triage | Daily 05:30 | `chief_of_staff/daily_triage.py` |
| Contradiction check | Daily 12:00 | `chief_of_staff/contradiction_check.py` |

### Librarian Schedule

| Job | Schedule | Script |
|-----|----------|--------|
| Entity enrichment | Daily 03:00 | `librarian/entity_enrichment.py` |

---

## Database Schema (`intelligence.db`)

SQLite at `~/.atrophy/agents/general_montgomery/data/intelligence.db`.

### Core Tables

**`briefs`** - All intelligence output. Central table.
```
id, conflict_id, date, title, content, requested_by, sources, created_at
```
- `requested_by`: agent name or user (e.g. `henry`, `general_montgomery`, `economic_io`)

**`conflicts`** - Active conflict watchlist.
```
id, name, slug, region, status, started_at, description, created_at
```
Watchlist: Sudan, Ukraine, Iran-Israel, Taiwan Strait, Sahel, Yemen, South China Sea, Kosovo

**`entities`** - Named actors.
```
id, name, aliases, type, subtype, parent_id, description, status, created_at, updated_at
```
- `type`: country, organization, person, faction

**`relationships`** - Actor relationships.
```
id, from_id, to_id, type, conflict_id, confidence, notes, source, valid_from, valid_to, created_at
```

**`conflict_actors`** - Who is on which side.
```
id, conflict_id, entity_id, alignment, side, notes
```

**`positions`** - Named individual roles.
```
id, person_id, org_id, title, start_date, end_date, notes, created_at
```

### Intelligence Tables

**`signals`** - Raw intelligence signals before assessment.
```
id, agent, signal_type, title, content, region, severity, source, created_at
```

**`commissions`** - Gap intelligence commissions (auto-filed by competitor synthesis).
```
id, title, brief, requestor, priority, assigned_to, status, output, submitted_at, completed_at
```

### Tracking Tables

**`assessment_outcomes`** - Prediction accuracy tracking.
```
id, brief_id, prediction, predicted_by, predicted_at, outcome, outcome_notes,
reviewed_at, reviewed_by, confidence_at_prediction, created_at
```
- `outcome`: PENDING, CORRECT, INCORRECT, PARTIAL
- Populated by `track_record.py extract` / `track_record.py review`

**`economic_history`** - Time-series economic data.
```
id, metric, value, unit, region, recorded_at, source
```

**`maritime_history`** - AIS chokepoint time series.
```
id, chokepoint, change_pct, severity, vessel_count, recorded_at, source
```

---

## Monday Operational Cycle

The full Monday sequence (all cron):

| Time | Job | Output |
|------|-----|--------|
| 07:00 | Weekly digest | Full six-track brief to Telegram |
| 07:30 | Track record extract | Predictions logged from new briefs |
| 08:00 | Weekly conflicts | One conflict from watchlist |
| 08:00 | Parliamentary monitor | Hansard alerts if relevant debates |
| 09:00 | Competitor scan + synthesis | CONFIRM/DIVERGE/GAP vs think tanks |

First Monday of month adds:
| 10:00 | Process audit | Institutional self-assessment to Obsidian + Telegram |
| 10:30 | Track record review | Outcomes recorded for 30-day-old predictions |

---

## Claude API Integration

All LLM calls use the Claude CLI on the local machine (`/Users/williamlilley/.local/bin/claude`). No direct Anthropic SDK or API key required. The `call_claude(system, prompt, model)` helper in each script calls:

```
claude -p --model <model> --system-prompt <system> --no-session-persistence --output-format text
```

Model used per script:
- `haiku` - high-volume triage (taxonomy_filing, competitor_synthesis, track_record extract/review, ambassador_poll)
- `sonnet` - primary analysis (all weekly/monthly assessments, red team, process audit, flash report)

---

## WorldMonitor Integration

WorldMonitor MCP server provides live data. All scripts use:
```python
from worldmonitor_server import WorldMonitorClient
client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
data, delta = client.fetch_cached("api/endpoint")
```

Active endpoints used:
- `api/ais-snapshot` - vessel tracking
- `api/oref-alerts` - Israeli missile alerts
- `api/military-flights` - military aviation
- `api/gpsjam` - GPS jamming
- `api/conflict/v1/list-acled-events` - conflict events
- `api/economic/v1/get-energy-prices` - energy prices
- `api/trade/v1/get-trade-restrictions` - trade restrictions

---

## Competitor Intelligence

**RSS feeds monitored** (daily 09:00):
- CSIS (`csis.org`)
- Atlantic Council (`atlanticcouncil.org`)
- The Diplomat (`thediplomat.com`)
- ECFR (`ecfr.eu`)
- Bellingcat (`bellingcat.com`)
- Carnegie Endowment (`carnegieendowment.org`)

Blocked/non-functional: RUSI, ISW, IISS, Chatham House, RAND (all return 403/404 on RSS).

**Synthesis logic** (`competitor_synthesis.py`): For each new article, Claude Haiku compares against Meridian DB content and returns CONFIRM / DIVERGE / GAP. GAPs are auto-filed to the `commissions` table.

---

## Remaining / Outstanding Work

### High Priority

1. **Primary sources** - All competitor feeds are aggregators. Reuters/AP/AFP API access or UN document feeds would give genuine primary source coverage. Currently no mechanism for this.

2. **`atrophy.app` subdomain hosting** - Deferred. Once subdomain is live, full D3.js HTML dashboard delivery can replace PNG/Telegram workaround. All HTML rendering code is in place (`dashboard_brief.py`, viz scripts); just needs a hosting target.

### Medium Priority

3. **`economic_history.unit` column** - Not populated by `economic_weekly.py`. Currently inserts NULL. Should be populated with the unit string (e.g. "USD/barrel", "USD/MWh").

4. **RSS state persistence** - `competitor_scan.py` uses a state file to track seen articles. First run returned 0 new items (correct, as state file was empty). Will populate naturally on next cycle.

5. **RF agents first run** - `rf_european_security` and `rf_indo_pacific` crons are set (Thursday/Friday 06:00) but neither has run yet. First outputs will appear at those times.

### Architecture Notes

- All scripts that call Claude do so via CLI subprocess, not SDK. If `claude` binary path changes, update `CLAUDE_BIN` in each script (currently hardcoded to `/Users/williamlilley/.local/bin/claude`).
- `assessment_outcomes` table is populated but empty until Monday 07:30 first runs prediction extraction against actual digest content.
- The red team upgraded from a 150-word paragraph to a four-part structured challenge (evidential, alternative actor, historical counter, verdict).

---

## Obsidian Mirror

Project documentation in Obsidian vault:
```
The Atrophied Mind/Projects/General Montgomery/
  Output SOP.md              - Voice rules, brief format, Telegram SOP, QC criteria
  MERIDIAN-HANDOVER.md       - This document (mirrored)
  Process Audits/            - Monthly institutional self-assessment records
  Conflicts/                 - Per-conflict brief archive
```

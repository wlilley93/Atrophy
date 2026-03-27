# Vibeaudit Security Audit - Atrophy App Electron

**Scan date:** 2026-03-27
**Scope:** `src/` directory (118 files, 114 code regions extracted)
**Method:** vibeaudit extraction + manual deep analysis (Anthropic API key not available in environment for automated LLM analysis)
**Vulnerability classes scanned:** 18 (idor, auth_bypass, mass_assignment, race_condition, broken_access_control, jwt_misconfig, ssrf, path_traversal, crypto_weakness, data_exposure, command_injection, xxe, graphql, prototype_pollution, insecure_defaults, timing_attacks, missing_rate_limit, ai_prompt_injection)

---

## Executive Summary

The codebase demonstrates **strong security awareness** across most modules. Authentication uses timing-safe comparison, the Electron renderer is properly sandboxed (`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`), CSP headers are applied, env var loading is whitelist-gated, agent names are validated at IPC boundaries, and prototype pollution is blocked in deep merge. However, several findings warrant attention.

**Critical:** 0
**High:** 2
**Medium:** 5
**Low:** 5
**Informational:** 4

---

## HIGH Severity

### H-1: SQL Injection via VACUUM INTO in backup.ts

**File:** `src/main/backup.ts:118`
**Class:** command_injection / sql_injection

```typescript
db.exec(`VACUUM INTO '${dbDst.replace(/'/g, "''")}'`);
```

The `dbDst` path is constructed from `USER_DATA + 'agents' + agentDir + 'data' + 'memory.db'`. While the agent directory names are validated elsewhere, the backup destination path (`BACKUP_DIR + today + 'agents'`) is not user-controlled under normal circumstances. However, the single-quote escaping via `replace(/'/g, "''")` is the only defense against SQL injection in this string interpolation. If an agent name or path segment ever contains SQL metacharacters beyond single quotes (e.g., via filesystem manipulation), this could be exploited.

**Recommendation:** Use a parameterized approach or validate that `dbDst` is an absolute path within the expected backup directory before interpolating it into SQL.

---

### H-2: Cron Job Runner Spawns Scripts from User-Writable Directory

**File:** `src/main/channels/cron/runner.ts:98-100`
**Class:** command_injection

```typescript
const personalPath = path.resolve(USER_DATA, 'scripts', definition.script.replace(/^scripts\//, ''));
const bundlePath = path.resolve(BUNDLE_ROOT, definition.script);
const scriptPath = fs.existsSync(personalPath) ? personalPath : bundlePath;
```

The cron runner prefers scripts from `~/.atrophy/scripts/` over bundled scripts. If an attacker can write to `~/.atrophy/scripts/`, they can hijack any scheduled job by placing a malicious script that shadows the bundled one. The `definition.script` value comes from `agent.json` manifests which can be edited through the UI (`updateAgentManifest`).

Additionally, `definition.script` is only stripped of a `scripts/` prefix before path resolution. A manifest with `script: "../../malicious.py"` would resolve outside the expected directory.

**Recommendation:**
- Validate that `scriptPath` resolves within either `USER_DATA/scripts/` or `BUNDLE_ROOT/scripts/` after `path.resolve()` (canonicalization check).
- Consider requiring script paths to match a strict pattern (no `..`, no absolute paths).

---

## MEDIUM Severity

### M-1: No Rate Limiting on HTTP Server Endpoints

**File:** `src/main/server.ts`
**Class:** missing_rate_limit

The HTTP server has an `inferLock` that prevents concurrent inference (returns 429), but there is no general rate limiting on authentication attempts or other endpoints (`/memory/search`, `/memory/threads`, `/session`). An attacker on localhost could brute-force the bearer token. While the token is 32 bytes of `crypto.randomBytes` (256 bits of entropy), the lack of rate limiting is a defense-in-depth gap.

**Recommendation:** Add a simple rate limiter (e.g., IP-based with a sliding window) for authentication failures, or implement exponential backoff on 401 responses.

---

### M-2: Switchboard Queue File is a TOCTOU Attack Surface

**File:** `src/main/channels/switchboard.ts:258-314`
**Class:** race_condition

The switchboard polls `~/.atrophy/.switchboard_queue.json` for MCP-originated messages. While the code uses rename-then-read to mitigate TOCTOU:

```typescript
fs.renameSync(queuePath, tmpPath);
fs.writeFileSync(queuePath, '[]');
const raw = fs.readFileSync(tmpPath, 'utf8');
```

The JSON from this file is parsed and each envelope is routed directly via `switchboard.route()`. A malicious process with write access to `~/.atrophy/` could inject arbitrary envelopes, potentially impersonating any address (e.g., `agent:xan`, `system`). The envelopes are trusted without origin verification.

**Recommendation:** Add envelope signing or at minimum validate that `from` addresses in queue-sourced envelopes are limited to `mcp:*` prefixes (since the queue is intended for MCP server communication only).

---

### M-3: Artefact iframe sandbox allows scripts without network restriction

**File:** `src/renderer/components/Artefact.svelte:231`
**Class:** insecure_defaults

```html
<iframe srcdoc={content} sandbox="allow-scripts" />
```

AI-generated artefact HTML content is rendered in an iframe with `sandbox="allow-scripts"`. While omitting `allow-same-origin` prevents the iframe from accessing the parent page's origin, the `allow-scripts` permission means the artefact can run arbitrary JavaScript. Combined with `connect-src 'self' https:` in the CSP, a malicious artefact could make outbound HTTPS requests.

The content comes from AI inference output (`extractCompleteArtifacts` in `artifact-parser.ts`), which parses `<artifact>` tags from Claude's response. This is an indirect prompt injection vector - if a user pastes content containing crafted artifact tags, or if context injection triggers artifact generation with malicious content.

**Recommendation:** Consider using a more restrictive sandbox or CSP for the artefact iframe specifically. A separate CSP with `connect-src 'none'` for the srcdoc iframe would prevent network exfiltration.

---

### M-4: Multipart Form Boundary Uses Math.random()

**File:** `src/main/channels/telegram/api.ts:886`
**Class:** crypto_weakness

```typescript
const boundary = `----FormBoundary${Date.now()}${Math.random().toString(36).slice(2)}`;
```

`Math.random()` is not cryptographically secure. While predicting the multipart boundary is unlikely to have direct security impact (it's used for HTTP body framing, not authentication), using `crypto.randomBytes()` would be more consistent with the codebase's generally strong crypto hygiene.

**Recommendation:** Replace with `crypto.randomBytes(16).toString('hex')` for consistency.

---

### M-5: Hot Bundle Loader Does Not Verify Integrity at Boot

**File:** `src/main/bootstrap.ts:100`
**Class:** command_injection

```typescript
await import(pathToFileURL(HOT_APP).href);
```

The bootstrap loads hot-updated code from `~/.atrophy/hot-bundle/`. While the bundle updater verifies SHA-256 hashes against the remote manifest before installing, the loaded code runs with full main-process privileges. If an attacker can write to `~/.atrophy/hot-bundle/` and modify the manifest file, they gain arbitrary code execution.

The boot sentinel mechanism provides some crash recovery but not integrity verification at load time.

**Recommendation:** Verify the SHA-256 hash of the hot bundle at load time (in bootstrap.ts), not just at download time (in bundle-updater.ts). This protects against post-download tampering.

---

## LOW Severity

### L-1: Agent Name Validation Inconsistency

**File:** Various

Agent name validation is done in multiple places with slightly different patterns:
- `config.ts:172`: `/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/` + `!name.includes('..')`
- `agent-manager.ts:327`: `/^[a-zA-Z0-9_-]+$/`
- `app.ts:484`: `/^[a-zA-Z0-9_-]+$/`

The config version requires the name to start with an alphanumeric character; the agent-manager version does not. This inconsistency could lead to bypasses if validation is done by one function but path construction assumes the other.

**Recommendation:** Centralize agent name validation in a single exported function (`isValidAgentName` from config.ts) and use it everywhere.

---

### L-2: Error Messages May Leak Internal Paths

**File:** `src/main/server.ts:264`, `src/main/channels/telegram/daemon.ts`
**Class:** data_exposure

Error responses from the server and error messages sent to Telegram may include full error messages from caught exceptions, which could contain filesystem paths, database paths, or internal state details:

```typescript
res.write(`data: ${JSON.stringify({ type: 'error', message: String(err) })}\n\n`);
```

**Recommendation:** Sanitize error messages in user-facing responses. Log full errors internally but return generic messages to clients.

---

### L-3: Telegram Bot Token in URL Path

**File:** `src/main/channels/telegram/api.ts:37`
**Class:** data_exposure

```typescript
return `https://api.telegram.org/bot${token}/${method}`;
```

The Telegram Bot API requires the token in the URL path, which is standard for this API. However, these URLs may be logged (line 97: `log.debug(...attempt...failed: ${e}...)`), potentially exposing the token in log files.

**Recommendation:** Ensure log output redacts or truncates bot tokens. Consider a helper that masks the token in log messages.

---

### L-4: loadURL in Dev Mode Without Validation

**File:** `src/main/app.ts:150-152`
**Class:** ssrf

```typescript
if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
```

In development mode, the window loads a URL from an environment variable without validation. While this is dev-only and the env var would need to be set by a local attacker, it could be used to load a malicious page with full preload API access.

**Recommendation:** Validate that `ELECTRON_RENDERER_URL` points to localhost before loading.

---

### L-5: deleteAgent Does Not Validate Name Within Function Body

**File:** `src/main/agent-manager.ts:572`
**Class:** path_traversal

While the IPC handler validates the name with `AGENT_RE.test(name)` before calling `deleteAgent`, the function itself does not validate. If called from another internal code path without validation, a name like `../../../etc` would resolve outside the agents directory and `fs.rmSync` with `recursive: true` could be destructive.

**Recommendation:** Add `isValidAgentName(name)` check at the top of `deleteAgent()` as defense in depth.

---

## INFORMATIONAL

### I-1: Strong Auth Implementation

The server's `checkAuth` function properly uses hash-then-compare with `crypto.timingSafeEqual`, preventing timing attacks on the bearer token. The token is generated with `crypto.randomBytes(32)` and stored with mode `0o600`.

### I-2: Good Prototype Pollution Protection

`config.ts:149` correctly filters `__proto__`, `constructor`, and `prototype` keys in the deep merge function:

```typescript
if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
```

### I-3: Good Env Var Injection Protection

The `.env` file loader uses a whitelist (`ALLOWED_ENV_KEYS`) and pattern matching for per-agent keys. Newlines are stripped from values to prevent injection. Keys already set in `process.env` are not overwritten.

### I-4: Electron Security Best Practices Followed

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`
- CSP headers applied via `onHeadersReceived`
- Preload uses `contextBridge.exposeInMainWorld` (verified by typed API)

---

## Scan Metadata

| Metric | Value |
|--------|-------|
| Files scanned | 118 |
| Code regions extracted | 114 |
| Vulnerability classes checked | 18 |
| True positives (findings) | 16 |
| False positives suppressed | ~98 (mostly generic catch blocks and non-security code flagged by extraction heuristics) |
| Scan mode | vibeaudit extraction + manual analysis |

---

## Recommendations Summary

| Priority | Action |
|----------|--------|
| **High** | Validate cron script paths resolve within expected directories |
| **High** | Use parameterized SQL or path validation for VACUUM INTO |
| **Medium** | Add rate limiting to HTTP server auth |
| **Medium** | Verify hot bundle integrity at boot time, not just download time |
| **Medium** | Sign or restrict `from` field in queue-sourced switchboard envelopes |
| **Medium** | Restrict artefact iframe CSP (block `connect-src`) |
| **Low** | Centralize agent name validation |
| **Low** | Sanitize error messages in user-facing responses |
| **Low** | Add `isValidAgentName` check inside `deleteAgent()` |

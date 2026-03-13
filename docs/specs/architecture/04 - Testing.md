# Testing Architecture

Atrophy uses a two-tier testing strategy: Vitest unit tests for business logic, and Puppeteer integration tests for UI state machine validation.

---

## Test Stack

| Tool | Purpose | Config |
|------|---------|--------|
| Vitest | Unit tests | `vitest.config.ts` |
| Puppeteer-core | UI state machine tests | Scripts in `scripts/` |
| Vibescan | Security scanning (13 tools) | CLI tool |
| Vibeaudit | AI-powered security audit | CLI tool |

---

## Unit Tests (Vitest)

**Location:** `src/main/__tests__/`
**Run:** `pnpm test`
**Watch mode:** `pnpm test:watch`

### Test files

| File | Module | Tests | What it covers |
|------|--------|-------|----------------|
| `agency.test.ts` | `agency.ts` | 36 | Mood shift detection, validation seeking, compulsive modelling, drift detection, energy/time/silence notes, emotional signals |
| `inner-life.test.ts` | `inner-life.ts` | 17 | formatForContext output, emotion labels, trust labels, decay math formula verification, type shape |
| `sentinel.test.ts` | `sentinel.ts` | 14 | Repetition detection, agreement drift, energy flatness, vocabulary staleness |
| `thinking.test.ts` | `thinking.ts` | 44 | Effort classification (low/medium/high) for various message patterns |
| `status.test.ts` | `status.ts` | 16 | Away intent detection - pattern matching for away/sleep/gone phrases |
| `usage.test.ts` | `usage.ts` | 8 | Token formatting, duration formatting |
| `server.test.ts` | `server.ts` | 35 | HTTP routing, auth, SSE format, NDJSON format, response contracts, error responses, content-type headers |
| `cli.test.ts` | `cli.ts` | 31 | Arg parsing, SSE event parsing, NDJSON event parsing, buffer splitting, header rendering, token path resolution |

**Total:** 201 tests

### Electron mock

Tests that import modules depending on Electron (like `config.ts`) use a mock at `src/main/__tests__/__mocks__/electron.ts`. The Vitest config aliases the `electron` import to this mock:

```typescript
// vitest.config.ts
alias: {
  electron: path.resolve(__dirname, 'src/main/__tests__/__mocks__/electron.ts'),
}
```

### Test patterns

- Pure function tests (agency, thinking, status) - import and call directly
- Format verification (server, cli) - reproduce parsing/formatting logic and validate contracts
- Math verification (inner-life decay) - inline the formula and verify expected values
- Type shape validation - verify object structures match expected interfaces

---

## Puppeteer Integration Tests

**Location:** `scripts/puppeteer-*.ts`
**Prerequisite:** App running with `pnpm dev:puppeteer` (opens remote debugging on port 9222)

### Test scripts

| Script | Purpose |
|--------|---------|
| `puppeteer-state-machine.ts` | **Big Beautiful Test Suite** - validates all state machines |
| `puppeteer-test.ts` | Basic connectivity, screenshot, body text dump |
| `puppeteer-chat.ts` | Send message via input, wait for response |
| `puppeteer-wait.ts` | Wait for existing inference to complete |
| `puppeteer-debug.ts` | Inspect preload API, stop inference, send via API |
| `puppeteer-send.ts` | Type "hi" via UI, poll for response |
| `puppeteer-screenshot.ts` | One-shot screenshot + body text |

### State Machine Test Suite

`puppeteer-state-machine.ts` validates every state in every state machine:

**1. AppPhase** (`boot -> setup -> ready -> shutdown`)
- Detects current phase via DOM inspection
- Checks for splash screen, setup wizard, transcript/input bar, shutdown screen

**2. InferenceState** (`idle -> thinking -> streaming -> compacting`)
- Verifies idle state (no active inference)
- Sends a test message, polls for thinking indicator
- Detects streaming text arrival
- Confirms return to idle after completion

**3. UpdateStatus** (`idle -> checking -> available -> downloading -> downloaded -> up-to-date -> error`)
- Checks for update check UI overlay
- Verifies resolution (dev mode skips updates)

**4. SetupWizard Phase** (`hidden -> welcome -> creating -> done`)
- Detects wizard visibility
- Checks for name input in welcome phase

**5. MirrorSetup Phase** (`intro -> downloading -> photo -> generating -> voice -> done`)
- Detects mirror setup overlay

**6. UI Overlays**
- Settings modal, timer, canvas, artefact, silence prompt, ask dialog, service card
- Verifies default hidden state

**7. UI Mode Toggles**
- Avatar visibility, mute state, eye mode, agent name display

**8. Keyboard Shortcuts**
- Escape key handling
- No-crash verification

**9. DOM Structure**
- CSS custom properties defined
- No error screens visible
- Console error detection

**10. Preload API**
- `window.atrophy` exposed
- All required methods present (sendMessage, getConfig, etc.)

### Running

```bash
# Terminal 1: Start app with Puppeteer support
pnpm dev:puppeteer

# Terminal 2: Run state machine tests
npx tsx scripts/puppeteer-state-machine.ts

# With options
npx tsx scripts/puppeteer-state-machine.ts --screenshots    # Save state screenshots
npx tsx scripts/puppeteer-state-machine.ts --verbose        # Detailed DOM output
npx tsx scripts/puppeteer-state-machine.ts --skip-inference  # Skip inference tests (faster)
```

---

## Security Testing

### Vibescan (automated scanning)

```bash
vibescan .                    # Full scan - secrets, CVEs, SAST, IaC, licences
vibescan . --tools gitleaks   # Quick secrets-only check
vibescan . --output md        # Markdown report
```

### Vibeaudit (AI-powered audit)

```bash
vibeaudit scan .              # Extract vulnerability patterns
vibeaudit scan . --deep       # AI deep scan (requires API key)
```

---

## CI Workflow

```bash
# 1. Typecheck
pnpm typecheck

# 2. Unit tests
pnpm test

# 3. Security scan
vibescan . --ship-safe

# 4. Build
pnpm build
```

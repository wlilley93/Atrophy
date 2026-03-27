# src/main/index.ts - Main Process Entry Point

**Dependencies:** None (re-exports `./app.ts`)  
**Purpose:** Thin entry point wrapper for electron-vite build compatibility

## Overview

This file serves as the TypeScript entry point for the Electron main process during development. In production (packaged app), `bootstrap.ts` is the actual entry point that handles hot bundle detection and dynamic imports. The separation exists because electron-vite expects a TypeScript entry point for its build pipeline, while the runtime needs JavaScript for dynamic imports of hot bundles.

## Execution Flow

### Development Mode

When running `pnpm dev`, electron-vite compiles and loads this file directly:

```
electron-vite dev → src/main/index.ts → imports ./app.ts → app.ts executes
```

### Production Mode (Packaged App)

In the packaged application, the bootstrap loader takes control:

```
bootstrap.ts → detects hot bundle → imports either:
  - Hot: ~/.atrophy/bundle/out/main/app.js
  - Frozen: <app bundle>/Resources/out/main/app.js
```

The `index.ts` file is not used in production - it exists solely for the development build pipeline.

## Code Structure

```typescript
/**
 * Entry point for the Electron main process.
 *
 * In production (packaged app), bootstrap.ts is the real entry point.
 * It detects hot bundles and loads app.ts from either the hot bundle
 * or the frozen asar.
 *
 * In development, electron-vite points here directly, and we just
 * load app.ts which does everything.
 */

import './app';
```

## Key Design Decisions

### 1. Separation from app.ts

The `index.ts` → `app.ts` split serves two purposes:

- **Build compatibility:** electron-vite expects a TypeScript entry point for its compilation pipeline
- **Runtime flexibility:** `bootstrap.ts` can dynamically import JavaScript bundles (hot or frozen) without TypeScript compilation overhead

### 2. No Logic in index.ts

This file contains zero application logic. It is purely an import statement. All initialization, IPC registration, window creation, and lifecycle management live in `app.ts`. This keeps the entry point stable and reduces the surface area for build-related issues.

### 3. Side-Effect Import

The import `import './app';` relies on side effects - `app.ts` executes its top-level code immediately upon import. This pattern is intentional and matches how Electron main processes work: the module loads and immediately begins initialization.

## Relationship to Other Files

| File | Relationship |
|------|--------------|
| `bootstrap.ts` | Production entry point that bypasses this file entirely |
| `app.ts` | The actual main process code, imported by this file in dev |
| `electron-vite.config.ts` | Build config that points to this file as the main process entry |

## Build Output

After electron-vite compilation, this file becomes:

```
out/main/index.js → compiled JavaScript that requires('./app.js')
```

The compiled output is not used in production (the bootstrap loader imports `app.js` directly), but it remains in the bundle for development-to-production parity.

## Error Handling

No error handling exists in this file. Any errors during `app.ts` initialization propagate up to Electron's main process error handler. In production, `bootstrap.ts` wraps the import in try/catch and displays a dialog on fatal errors.

## See Also

- `src/main/bootstrap.ts` - Production entry point with hot bundle detection
- `src/main/app.ts` - Actual main process implementation
- `electron-vite.config.ts` - Build configuration referencing this entry point

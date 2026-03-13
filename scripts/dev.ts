/**
 * Dev script - runs renderer Vite dev server + electron-vite for main/preload.
 *
 * Workaround for electron-vite 5 dropping Svelte plugins in its config
 * resolution pipeline. We run the renderer dev server separately using
 * the standalone vite.renderer.config.ts, then launch electron-vite
 * (which handles main/preload build + electron launch).
 */

import { createServer } from 'vite';
import { spawn } from 'child_process';
import { resolve } from 'path';

const ROOT = resolve(import.meta.dirname, '..');

async function main() {
  // 1. Start Vite dev server for renderer
  const server = await createServer({
    configFile: resolve(ROOT, 'vite.renderer.config.ts'),
    server: { port: 5173, strictPort: true },
  });
  await server.listen();

  const address = server.httpServer?.address();
  const port = typeof address === 'object' && address ? address.port : 5173;
  const rendererUrl = `http://localhost:${port}/`;

  console.log(`\n  Renderer dev server: ${rendererUrl}\n`);

  // 2. Launch electron-vite dev (main/preload only, no renderer)
  //    Set ELECTRON_RENDERER_URL so the main process loads from the dev server
  const puppeteer = process.argv.includes('--puppeteer');
  const debugPort = puppeteer ? '9222' : process.env.REMOTE_DEBUGGING_PORT;

  const evArgs = ['electron-vite', 'dev', '-c', 'electron-vite.config.ts'];
  if (debugPort) {
    evArgs.push('--', `--remote-debugging-port=${debugPort}`);
  }

  const child = spawn('npx', evArgs, {
    cwd: ROOT,
    stdio: 'inherit',
    env: {
      ...process.env,
      ELECTRON_RENDERER_URL: rendererUrl,
    },
  });

  if (debugPort) {
    console.log(`  Remote debugging on port ${debugPort} (puppeteer-core can connect)\n`);
  }

  child.on('close', async (code) => {
    await server.close();
    process.exit(code ?? 0);
  });

  // Handle Ctrl+C
  for (const sig of ['SIGINT', 'SIGTERM'] as const) {
    process.on(sig, () => {
      child.kill(sig);
    });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

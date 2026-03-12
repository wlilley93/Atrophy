/**
 * Programmatic orb icon generator for the companion app.
 *
 * Port of display/icon.py - generates a luminous consciousness orb using
 * layered radial gradients rendered as SVG, then converted to Electron
 * NativeImage. Manages tray icon state (active, muted, idle/away).
 */

import { app, nativeImage, NativeImage } from 'electron';
import * as path from 'path';
import * as fs from 'fs';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TrayState = 'active' | 'muted' | 'idle' | 'away';

interface GradientStop {
  offset: number;
  r: number;
  g: number;
  b: number;
  a: number;
}

interface RadialGradientDef {
  id: string;
  cx: number;
  cy: number;
  r: number;
  stops: GradientStop[];
}

interface EllipseDef {
  gradientId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  transform?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ICON_SIZES = [16, 32, 128, 256, 512, 1024] as const;

// ---------------------------------------------------------------------------
// Cache
// ---------------------------------------------------------------------------

let cachedAppIcon: NativeImage | null = null;
const trayIconCache = new Map<string, NativeImage>();

// ---------------------------------------------------------------------------
// SVG gradient/layer definitions (port of _render_orb 8 layers)
// ---------------------------------------------------------------------------

function buildGradients(size: number): { gradients: RadialGradientDef[]; ellipses: EllipseDef[] } {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2;

  const gradients: RadialGradientDef[] = [];
  const ellipses: EllipseDef[] = [];

  // Layer 1: Outermost ambient glow
  gradients.push({
    id: 'g1',
    cx: cx,
    cy: cy * 0.95,
    r: radius * 0.95,
    stops: [
      { offset: 0.0, r: 120, g: 140, b: 220, a: 40 / 255 },
      { offset: 0.4, r: 80, g: 90, b: 160, a: 28 / 255 },
      { offset: 0.7, r: 40, g: 30, b: 80, a: 12 / 255 },
      { offset: 1.0, r: 0, g: 0, b: 0, a: 0 },
    ],
  });
  ellipses.push({ gradientId: 'g1', x: 0, y: 0, width: size, height: size });

  // Layer 2: Outer halo - soft purple/blue envelope
  gradients.push({
    id: 'g2',
    cx: cx,
    cy: cy * 0.97,
    r: radius * 0.78,
    stops: [
      { offset: 0.0, r: 140, g: 160, b: 255, a: 100 / 255 },
      { offset: 0.3, r: 100, g: 110, b: 210, a: 75 / 255 },
      { offset: 0.6, r: 60, g: 50, b: 140, a: 45 / 255 },
      { offset: 0.85, r: 25, g: 15, b: 60, a: 15 / 255 },
      { offset: 1.0, r: 0, g: 0, b: 0, a: 0 },
    ],
  });
  ellipses.push({ gradientId: 'g2', x: 0, y: 0, width: size, height: size });

  // Layer 3: Mid-glow - visible body of the orb
  gradients.push({
    id: 'g3',
    cx: cx,
    cy: cy * 0.93,
    r: radius * 0.55,
    stops: [
      { offset: 0.0, r: 190, g: 210, b: 255, a: 200 / 255 },
      { offset: 0.25, r: 150, g: 170, b: 245, a: 160 / 255 },
      { offset: 0.5, r: 110, g: 120, b: 220, a: 110 / 255 },
      { offset: 0.75, r: 65, g: 65, b: 170, a: 55 / 255 },
      { offset: 1.0, r: 20, g: 15, b: 60, a: 0 },
    ],
  });
  ellipses.push({ gradientId: 'g3', x: 0, y: 0, width: size, height: size });

  // Layer 4: Inner bright core - white/blue hot center
  const coreCx = cx * 0.96;
  const coreCy = cy * 0.85;
  gradients.push({
    id: 'g4',
    cx: coreCx,
    cy: coreCy,
    r: radius * 0.32,
    stops: [
      { offset: 0.0, r: 255, g: 255, b: 255, a: 250 / 255 },
      { offset: 0.15, r: 235, g: 245, b: 255, a: 230 / 255 },
      { offset: 0.35, r: 190, g: 215, b: 255, a: 180 / 255 },
      { offset: 0.6, r: 140, g: 165, b: 245, a: 100 / 255 },
      { offset: 0.85, r: 100, g: 120, b: 220, a: 40 / 255 },
      { offset: 1.0, r: 70, g: 80, b: 170, a: 0 },
    ],
  });
  ellipses.push({ gradientId: 'g4', x: 0, y: 0, width: size, height: size });

  // Layer 5: Hot specular highlight - "window reflection"
  const specCx = cx * 0.88;
  const specCy = cy * 0.72;
  const specR = radius * 0.15;
  gradients.push({
    id: 'g5',
    cx: specCx,
    cy: specCy,
    r: specR,
    stops: [
      { offset: 0.0, r: 255, g: 255, b: 255, a: 200 / 255 },
      { offset: 0.3, r: 240, g: 248, b: 255, a: 140 / 255 },
      { offset: 0.7, r: 200, g: 220, b: 255, a: 40 / 255 },
      { offset: 1.0, r: 160, g: 180, b: 240, a: 0 },
    ],
  });
  ellipses.push({ gradientId: 'g5', x: 0, y: 0, width: size, height: size });

  // Layer 6: Light flare - vertical streak through the orb (tilted -15deg)
  const flareW = radius * 0.08;
  const flareH = radius * 0.7;
  const flareR = Math.max(flareH, flareW);
  gradients.push({
    id: 'g6',
    cx: 0,
    cy: -flareH * 0.2,
    r: flareR,
    stops: [
      { offset: 0.0, r: 255, g: 255, b: 255, a: 60 / 255 },
      { offset: 0.3, r: 200, g: 220, b: 255, a: 35 / 255 },
      { offset: 0.6, r: 160, g: 180, b: 240, a: 15 / 255 },
      { offset: 1.0, r: 100, g: 120, b: 200, a: 0 },
    ],
  });
  ellipses.push({
    gradientId: 'g6',
    x: -flareW,
    y: -flareH,
    width: flareW * 2,
    height: flareH * 2,
    transform: `translate(${cx}, ${cy}) rotate(-15)`,
  });

  // Layer 7: Secondary smaller flare (cross, rotated 75deg)
  const flareW2 = radius * 0.05;
  const flareH2 = radius * 0.45;
  const flareR2 = Math.max(flareH2, flareW2);
  gradients.push({
    id: 'g7',
    cx: 0,
    cy: 0,
    r: flareR2,
    stops: [
      { offset: 0.0, r: 255, g: 255, b: 255, a: 35 / 255 },
      { offset: 0.4, r: 180, g: 200, b: 255, a: 20 / 255 },
      { offset: 1.0, r: 120, g: 140, b: 220, a: 0 },
    ],
  });
  ellipses.push({
    gradientId: 'g7',
    x: -flareW2,
    y: -flareH2,
    width: flareW2 * 2,
    height: flareH2 * 2,
    transform: `translate(${cx}, ${cy}) rotate(75)`,
  });

  // Layer 8: Faint rim light on the bottom edge
  const rimCy = cy * 1.15;
  gradients.push({
    id: 'g8',
    cx: cx,
    cy: rimCy,
    r: radius * 0.50,
    stops: [
      { offset: 0.0, r: 160, g: 180, b: 240, a: 30 / 255 },
      { offset: 0.4, r: 120, g: 140, b: 210, a: 18 / 255 },
      { offset: 0.7, r: 80, g: 90, b: 170, a: 8 / 255 },
      { offset: 1.0, r: 40, g: 40, b: 100, a: 0 },
    ],
  });
  ellipses.push({ gradientId: 'g8', x: 0, y: 0, width: size, height: size });

  return { gradients, ellipses };
}

// ---------------------------------------------------------------------------
// SVG rendering
// ---------------------------------------------------------------------------

function stopToSvgColor(s: GradientStop): string {
  const alpha = Math.round(s.a * 1000) / 1000;
  return `<stop offset="${s.offset}" stop-color="rgb(${s.r},${s.g},${s.b})" stop-opacity="${alpha}"/>`;
}

function renderOrbSvg(size: number): string {
  const { gradients, ellipses } = buildGradients(size);

  const defs = gradients.map((g) => {
    // For flare layers (g6, g7) the gradient is in the transformed coordinate
    // space. We use gradientUnits="userSpaceOnUse" for all gradients.
    const stops = g.stops.map(stopToSvgColor).join('\n      ');
    return `    <radialGradient id="${g.id}" cx="${g.cx}" cy="${g.cy}" r="${g.r}" gradientUnits="userSpaceOnUse">
      ${stops}
    </radialGradient>`;
  }).join('\n');

  const shapes = ellipses.map((e) => {
    const rx = e.width / 2;
    const ry = e.height / 2;
    const elCx = e.x + rx;
    const elCy = e.y + ry;
    const transform = e.transform ? ` transform="${e.transform}"` : '';
    return `  <ellipse cx="${elCx}" cy="${elCy}" rx="${rx}" ry="${ry}" fill="url(#${e.gradientId})"${transform}/>`;
  }).join('\n');

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <defs>
${defs}
  </defs>
${shapes}
</svg>`;
}

// ---------------------------------------------------------------------------
// NativeImage conversion
// ---------------------------------------------------------------------------

function svgToNativeImage(svg: string, size: number): NativeImage {
  const buf = Buffer.from(svg, 'utf-8');
  // nativeImage.createFromBuffer can handle SVG data on macOS/Windows
  // but for reliable cross-platform support we use data URL approach.
  const dataUrl = `data:image/svg+xml;base64,${buf.toString('base64')}`;
  const img = nativeImage.createFromDataURL(dataUrl);
  // Resize to exact target to ensure pixel-perfect rendering
  return img.resize({ width: size, height: size });
}

/**
 * Render the consciousness orb at a given size and return a NativeImage.
 */
export function renderOrb(size: number): NativeImage {
  const svg = renderOrbSvg(size);
  return svgToNativeImage(svg, size);
}

// ---------------------------------------------------------------------------
// Tray state overlays
// ---------------------------------------------------------------------------

/**
 * Generate a muted indicator overlay - a small diagonal line through the orb.
 * Rendered as SVG overlay composited onto the base orb.
 */
function renderMutedOverlay(size: number): string {
  const pad = Math.round(size * 0.2);
  const stroke = Math.max(1, Math.round(size * 0.08));
  return `<line x1="${pad}" y1="${pad}" x2="${size - pad}" y2="${size - pad}" stroke="rgba(255,80,80,0.8)" stroke-width="${stroke}" stroke-linecap="round"/>`;
}

/**
 * Generate an idle/away dot indicator - small circle at bottom-right.
 */
function renderStateIndicator(size: number, state: TrayState): string {
  if (state === 'active') return '';

  const dotRadius = Math.max(2, Math.round(size * 0.12));
  const dotCx = size - dotRadius - 1;
  const dotCy = size - dotRadius - 1;

  if (state === 'muted') {
    return renderMutedOverlay(size);
  }

  // idle = yellow dot, away = gray dot
  const color = state === 'idle'
    ? 'rgba(255,200,50,0.9)'
    : 'rgba(140,140,140,0.7)';

  return `<circle cx="${dotCx}" cy="${dotCy}" r="${dotRadius}" fill="${color}" stroke="rgba(0,0,0,0.5)" stroke-width="1"/>`;
}

function renderTrayOrbSvg(size: number, state: TrayState): string {
  const { gradients, ellipses } = buildGradients(size);

  const defs = gradients.map((g) => {
    const stops = g.stops.map(stopToSvgColor).join('\n      ');
    return `    <radialGradient id="${g.id}" cx="${g.cx}" cy="${g.cy}" r="${g.r}" gradientUnits="userSpaceOnUse">
      ${stops}
    </radialGradient>`;
  }).join('\n');

  const shapes = ellipses.map((e) => {
    const rx = e.width / 2;
    const ry = e.height / 2;
    const elCx = e.x + rx;
    const elCy = e.y + ry;
    const transform = e.transform ? ` transform="${e.transform}"` : '';
    return `  <ellipse cx="${elCx}" cy="${elCy}" rx="${rx}" ry="${ry}" fill="url(#${e.gradientId})"${transform}/>`;
  }).join('\n');

  const overlay = renderStateIndicator(size, state);

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <defs>
${defs}
  </defs>
${shapes}
  ${overlay}
</svg>`;
}

/**
 * Get a tray icon NativeImage for the given state.
 * Results are cached per state+size combination.
 *
 * Tray icons on macOS are rendered at 22x22 logical pixels (44px @2x).
 * We generate at 44px and let Electron handle DPI scaling.
 */
export function getTrayIcon(state: TrayState = 'active', size: number = 44): NativeImage {
  const key = `${state}-${size}`;
  const cached = trayIconCache.get(key);
  if (cached) return cached;

  const svg = renderTrayOrbSvg(size, state);
  const img = svgToNativeImage(svg, size);
  trayIconCache.set(key, img);
  return img;
}

/**
 * Clear the tray icon cache (call after theme/color changes if needed).
 */
export function clearTrayIconCache(): void {
  trayIconCache.clear();
}

// ---------------------------------------------------------------------------
// Icon file generation
// ---------------------------------------------------------------------------

function getIconsDir(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'icons')
    : path.join(__dirname, '..', '..', 'resources', 'icons');
}

/**
 * Generate orb icon PNGs at multiple sizes. Skips sizes where a file
 * already exists (preserving hand-crafted icons).
 *
 * Returns the list of file paths (existing or newly created).
 *
 * Note: PNG writing requires the NativeImage toPNG() method which is
 * available in the Electron main process.
 */
export function generateIcons(
  directory?: string,
  sizes?: readonly number[],
): string[] {
  const dir = directory ?? getIconsDir();
  const targetSizes = sizes ?? ICON_SIZES;

  fs.mkdirSync(dir, { recursive: true });

  const paths: string[] = [];
  for (const s of targetSizes) {
    const filePath = path.join(dir, `icon_${s}x${s}.png`);
    if (fs.existsSync(filePath)) {
      paths.push(filePath);
      continue;
    }
    const img = renderOrb(s);
    const pngBuffer = img.toPNG();
    fs.writeFileSync(filePath, pngBuffer);
    paths.push(filePath);
  }

  return paths;
}

// ---------------------------------------------------------------------------
// App icon (dock / window icon)
// ---------------------------------------------------------------------------

/**
 * Return a NativeImage suitable for the app/dock icon.
 *
 * Prefers the .icns file (hand-crafted brain icon) over generated orb PNGs,
 * which are used as a fallback only. Result is cached.
 */
export function getAppIcon(): NativeImage {
  if (cachedAppIcon) return cachedAppIcon;

  const iconsDir = getIconsDir();

  // Prefer .icns (the brain icon) if it exists
  const icnsPath = path.join(iconsDir, 'TheAtrophiedMind.icns');
  if (fs.existsSync(icnsPath)) {
    const icon = nativeImage.createFromPath(icnsPath);
    if (!icon.isEmpty()) {
      cachedAppIcon = icon;
      return icon;
    }
  }

  // Fallback: generated orb PNGs
  const missing = ICON_SIZES.some(
    (s) => !fs.existsSync(path.join(iconsDir, `icon_${s}x${s}.png`)),
  );
  if (missing) {
    generateIcons(iconsDir);
  }

  // Build a multi-resolution icon from available PNGs
  // Use the largest available as the base
  for (const s of [...ICON_SIZES].reverse()) {
    const filePath = path.join(iconsDir, `icon_${s}x${s}.png`);
    if (fs.existsSync(filePath)) {
      const icon = nativeImage.createFromPath(filePath);
      if (!icon.isEmpty()) {
        cachedAppIcon = icon;
        return icon;
      }
    }
  }

  // Last resort: render a 256px orb on the fly
  cachedAppIcon = renderOrb(256);
  return cachedAppIcon;
}

/**
 * Clear all cached icons (app icon + tray icons).
 */
export function clearIconCache(): void {
  cachedAppIcon = null;
  trayIconCache.clear();
}

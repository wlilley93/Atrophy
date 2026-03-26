# src/main/icon.ts - Procedural Orb Icon Generator

**Line count:** ~350 lines  
**Dependencies:** `electron`, `path`, `fs`  
**Purpose:** Generate luminous consciousness orb icons using layered radial gradients

## Overview

This module generates the app's orb icons programmatically using SVG with layered radial gradients. It manages tray icon state (active, muted, idle, away) and provides both runtime NativeImage generation and static PNG file generation.

**Port of:** `display/icon.py`

## Types

### TrayState

```typescript
export type TrayState = 'active' | 'muted' | 'idle' | 'away';
```

**States:**
- `active` - Normal operation, no overlay
- `muted` - Red diagonal line through orb
- `idle` - Yellow dot indicator (bottom-right)
- `away` - Gray dot indicator (bottom-right)

### GradientStop

```typescript
interface GradientStop {
  offset: number;
  r: number;
  g: number;
  b: number;
  a: number;
}
```

### RadialGradientDef

```typescript
interface RadialGradientDef {
  id: string;
  cx: number;
  cy: number;
  r: number;
  stops: GradientStop[];
}
```

### EllipseDef

```typescript
interface EllipseDef {
  gradientId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  transform?: string;
}
```

## Constants

```typescript
const ICON_SIZES = [16, 32, 128, 256, 512, 1024] as const;
```

**Purpose:** Standard icon sizes for various uses (tray, dock, file icons).

## Cache

```typescript
let cachedAppIcon: NativeImage | null = null;
const trayIconCache = new Map<string, NativeImage>();
```

**Purpose:** Cache generated icons to avoid redundant SVG rendering.

## SVG Gradient/Layer Definitions

### buildGradients

```typescript
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
  // ...

  // Layer 3: Mid-glow - visible body of the orb
  // ...

  // Layer 4: Inner bright core - white/blue hot center
  // ...

  // Layer 5: Hot specular highlight - "window reflection"
  // ...

  // Layer 6: Light flare - vertical streak through the orb (tilted -15deg)
  // ...

  // Layer 7: Secondary smaller flare (cross, rotated 75deg)
  // ...

  // Layer 8: Faint rim light on the bottom edge
  // ...

  return { gradients, ellipses };
}
```

**Purpose:** Build 8-layer gradient definitions for the orb.

**Layers:**
1. Outermost ambient glow (faint blue)
2. Outer halo (soft purple/blue envelope)
3. Mid-glow (visible body of the orb)
4. Inner bright core (white/blue hot center)
5. Hot specular highlight ("window reflection")
6. Light flare (vertical streak, tilted -15deg)
7. Secondary flare (cross, rotated 75deg)
8. Faint rim light (bottom edge)

## SVG Rendering

### stopToSvgColor

```typescript
function stopToSvgColor(s: GradientStop): string {
  const alpha = Math.round(s.a * 1000) / 1000;
  return `<stop offset="${s.offset}" stop-color="rgb(${s.r},${s.g},${s.b})" stop-opacity="${alpha}"/>`;
}
```

**Purpose:** Convert gradient stop to SVG stop element.

### renderOrbSvg

```typescript
function renderOrbSvg(size: number): string {
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

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <defs>
${defs}
  </defs>
${shapes}
</svg>`;
}
```

**Purpose:** Render complete orb SVG.

## NativeImage Conversion

### svgToNativeImage

```typescript
function svgToNativeImage(svg: string, size: number): NativeImage {
  const buf = Buffer.from(svg, 'utf-8');
  // Use data URL approach for reliable cross-platform support
  const dataUrl = `data:image/svg+xml;base64,${buf.toString('base64')}`;
  const img = nativeImage.createFromDataURL(dataUrl);
  // Resize to exact target for pixel-perfect rendering
  return img.resize({ width: size, height: size });
}
```

**Purpose:** Convert SVG string to Electron NativeImage.

### renderOrb

```typescript
export function renderOrb(size: number): NativeImage {
  const svg = renderOrbSvg(size);
  return svgToNativeImage(svg, size);
}
```

**Purpose:** Render orb at given size.

## Tray State Overlays

### renderMutedOverlay

```typescript
function renderMutedOverlay(size: number): string {
  const pad = Math.round(size * 0.2);
  const stroke = Math.max(1, Math.round(size * 0.08));
  return `<line x1="${pad}" y1="${pad}" x2="${size - pad}" y2="${size - pad}" stroke="rgba(255,80,80,0.8)" stroke-width="${stroke}" stroke-linecap="round"/>`;
}
```

**Purpose:** Generate diagonal red line for muted state.

### renderStateIndicator

```typescript
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
```

**Purpose:** Generate state indicator overlay.

**Indicators:**
- `active`: No overlay
- `muted`: Red diagonal line
- `idle`: Yellow dot (bottom-right)
- `away`: Gray dot (bottom-right)

### renderTrayOrbSvg

```typescript
function renderTrayOrbSvg(size: number, state: TrayState): string {
  const { gradients, ellipses } = buildGradients(size);

  // ... build gradients and shapes ...

  const overlay = renderStateIndicator(size, state);

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <defs>
${defs}
  </defs>
${shapes}
  ${overlay}
</svg>`;
}
```

**Purpose:** Render orb with state overlay.

### getTrayIcon

```typescript
export function getTrayIcon(state: TrayState = 'active', size: number = 44): NativeImage {
  const key = `${state}-${size}`;
  const cached = trayIconCache.get(key);
  if (cached) return cached;

  const svg = renderTrayOrbSvg(size, state);
  const img = svgToNativeImage(svg, size);
  trayIconCache.set(key, img);
  return img;
}
```

**Purpose:** Get cached tray icon for state.

**Default size:** 44px (for macOS @2x tray rendering).

### clearTrayIconCache

```typescript
export function clearTrayIconCache(): void {
  trayIconCache.clear();
}
```

**Purpose:** Clear tray icon cache.

## Icon File Generation

### getIconsDir

```typescript
function getIconsDir(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'icons')
    : path.join(__dirname, '..', '..', 'resources', 'icons');
}
```

**Purpose:** Get icons directory path.

### generateIcons

```typescript
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
```

**Purpose:** Generate orb PNGs at multiple sizes.

**Behavior:** Skips sizes where file already exists (preserves hand-crafted icons).

## App Icon (Dock / Window Icon)

### getAppIcon

```typescript
export function getAppIcon(): NativeImage {
  if (cachedAppIcon) return cachedAppIcon;

  const iconsDir = getIconsDir();

  // Prefer .icns (hand-crafted brain icon) if it exists
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

  // Build multi-resolution icon from available PNGs
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

  // Last resort: render 256px orb on the fly
  cachedAppIcon = renderOrb(256);
  return cachedAppIcon;
}
```

**Priority:**
1. Hand-crafted `.icns` (brain icon)
2. Generated orb PNGs (multi-resolution)
3. Render 256px orb on the fly

### clearIconCache

```typescript
export function clearIconCache(): void {
  cachedAppIcon = null;
  trayIconCache.clear();
}
```

**Purpose:** Clear all cached icons.

## File I/O

| File | Purpose |
|------|---------|
| `resources/icons/TheAtrophiedMind.icns` | Hand-crafted brain icon |
| `resources/icons/icon_*.png` | Generated orb PNGs |
| `process.resourcesPath/icons/` | Packaged icon directory |

## Exported API

| Function | Purpose |
|----------|---------|
| `renderOrb(size)` | Render orb NativeImage |
| `getTrayIcon(state, size)` | Get cached tray icon |
| `clearTrayIconCache()` | Clear tray icon cache |
| `generateIcons(directory, sizes)` | Generate PNG files |
| `getAppIcon()` | Get app/dock icon |
| `clearIconCache()` | Clear all icon caches |
| `TrayState` | Tray state type |

## See Also

- `src/main/app.ts` - Uses getTrayIcon, getAppIcon
- `src/main/ipc/system.ts` - Icon-related IPC handlers
- `src/renderer/components/OrbAvatar.svelte` - Orb rendering in UI

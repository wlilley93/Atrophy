# src/renderer/components/Timer.svelte - Silence Timer Overlay

**Line count:** ~408 lines  
**Dependencies:** `svelte`  
**Purpose:** Draggable timer overlay with alarm, pause, and time adjustment

## Overview

This component provides a draggable timer overlay that can be set for any duration, paused/resumed, and fires an alarm when complete. It's used for the silence timer prompt and general timing needs.

## Props

```typescript
interface Props {
  onClose: () => void;
}
```

## State Variables

### Timer State

```typescript
let endTime = $state(0);           // Date.now() when timer expires
let totalSeconds = $state(0);      // Current remaining seconds
let running = $state(false);
let paused = $state(false);
let pauseRemaining = $state(0);    // Seconds when paused
let done = $state(false);
let alarming = $state(false);
let tickInterval: ReturnType<typeof setInterval> | null = null;
```

### Alarm State

```typescript
let alarmTimeouts: ReturnType<typeof setTimeout>[] = [];
let alarmAudios: HTMLAudioElement[] = [];
let autoDismissTimeout: ReturnType<typeof setTimeout> | null = null;
```

### Drag State

```typescript
let dragging = $state(false);
let dragStartX = 0;
let dragStartY = 0;
let posRight = $state(20);
let posTop = $state(80);
let posMode = $state<'right' | 'left'>('right');
let posLeft = $state(0);
```

### Visual State

```typescript
let timerColor = $state('rgba(255, 180, 100, 0.9)');
let timerShadow = $state('0 0 40px rgba(255, 140, 50, 0.2)');
```

## Time Formatting

```typescript
function formatTime(s: number): string {
  const clamped = Math.max(0, Math.floor(s));
  const h = Math.floor(clamped / 3600);
  const m = Math.floor((clamped % 3600) / 60);
  const sec = clamped % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  return `${m}:${String(sec).padStart(2, '0')}`;
}
```

**Formats:**
- Hours present: `H:MM:SS`
- No hours: `MM:SS`

## Display Update

```typescript
function updateDisplay() {
  if (paused || done) return;

  const remaining = Math.max(0, (endTime - Date.now()) / 1000);
  totalSeconds = remaining;

  // Color gradient in final 10 seconds
  if (remaining <= 10 && remaining > 0) {
    const progress = 1 - remaining / 10;  // 0 to 1
    const green = Math.round(180 - progress * 140);  // 180 → 40
    const blue = Math.round(100 - progress * 80);    // 100 → 20
    timerColor = `rgba(255, ${green}, ${blue}, 0.9)`;
    timerShadow = `0 0 40px rgba(255, ${Math.round(140 - progress * 100)}, ${Math.round(50 - progress * 50)}, ${0.2 + progress * 0.3})`;
  } else if (remaining > 10) {
    timerColor = 'rgba(255, 180, 100, 0.9)';
    timerShadow = '0 0 40px rgba(255, 140, 50, 0.2)';
  }

  if (remaining <= 0 && !done) {
    done = true;
    totalSeconds = 0;
    timerColor = 'rgba(255, 100, 100, 0.9)';
    timerShadow = '0 0 40px rgba(255, 60, 60, 0.4)';
    fireAlarm();
  }
}
```

**Visual changes:**
- Normal: Orange glow
- Final 10s: Gradient to red
- Expired: Red glow, alarm fires

## Timer Controls

### startTick

```typescript
function startTick() {
  if (tickInterval) clearInterval(tickInterval);
  tickInterval = setInterval(updateDisplay, 100);  // 100ms for smooth display
}
```

### toggle

```typescript
function toggle() {
  if (done) return;
  if (running) {
    pause();
  } else {
    start();
  }
}
```

### start

```typescript
function start() {
  if (done) return;
  if (paused) {
    // Resume from pause
    endTime = Date.now() + pauseRemaining * 1000;
    paused = false;
    running = true;
    startTick();
    return;
  }
  if (totalSeconds <= 0) return;
  endTime = Date.now() + totalSeconds * 1000;
  running = true;
  startTick();
}
```

### pause

```typescript
function pause() {
  if (!running || done) return;
  pauseRemaining = Math.max(0, (endTime - Date.now()) / 1000);
  paused = true;
  running = false;
  stopTick();
}
```

### addMinutes

```typescript
function addMinutes(n: number) {
  const addSeconds = n * 60;
  if (done) {
    // Restart from alarm state
    stopAlarm();
    done = false;
    alarming = false;
    endTime = Date.now() + addSeconds * 1000;
    totalSeconds = addSeconds;
    running = true;
    startTick();
  } else if (paused) {
    pauseRemaining += addSeconds;
    totalSeconds = pauseRemaining;
  } else if (running) {
    endTime += addSeconds * 1000;
  } else {
    totalSeconds += addSeconds;
  }
}
```

**Purpose:** Add time to timer (used by +1m, +5m buttons).

## Alarm

### fireAlarm

```typescript
function fireAlarm() {
  alarming = true;
  running = false;
  stopTick();

  // Play Glass.aiff 6 times with ~1.5s spacing
  for (let i = 0; i < 6; i++) {
    const timeout = setTimeout(() => {
      if (!alarming) return;
      const audio = new Audio('/System/Library/Sounds/Glass.aiff');
      audio.volume = 0.5;
      audio.play().catch(() => {});
      alarmAudios.push(audio);
    }, i * 1500);
    alarmTimeouts.push(timeout);
  }

  // Auto-dismiss after 30 seconds
  autoDismissTimeout = setTimeout(() => {
    stopAlarm();
    onClose();
  }, 30000);
}
```

**Alarm behavior:**
- Plays Glass.aiff 6 times
- 1.5 second spacing between plays
- Auto-dismisses after 30 seconds

### stopAlarm

```typescript
function stopAlarm() {
  alarming = false;
  for (const timeout of alarmTimeouts) clearTimeout(timeout);
  alarmTimeouts = [];
  for (const audio of alarmAudios) audio.pause();
  alarmAudios = [];
  if (autoDismissTimeout) clearTimeout(autoDismissTimeout);
  autoDismissTimeout = null;
}
```

## Dragging

### onDragStart

```typescript
function onDragStart(e: MouseEvent) {
  dragging = true;
  dragStartX = e.clientX;
  dragStartY = e.clientY;
}
```

### onDragMove

```typescript
function onDragMove(e: MouseEvent) {
  if (!dragging) return;
  
  const dx = e.clientX - dragStartX;
  const dy = e.clientY - dragStartY;
  
  if (posMode === 'right') {
    posRight = Math.max(0, posRight - dx);
  } else {
    posLeft = Math.max(0, posLeft + dx);
  }
  posTop = Math.max(0, posTop + dy);
  
  dragStartX = e.clientX;
  dragStartY = e.clientY;
}
```

### onDragEnd

```typescript
function onDragEnd() {
  dragging = false;
  
  // Snap to edge if near
  const screenWidth = window.innerWidth;
  const centerThreshold = screenWidth / 2;
  const currentLeft = posMode === 'right' ? screenWidth - posRight : posLeft;
  
  if (currentLeft < centerThreshold) {
    posMode = 'left';
    posLeft = Math.min(20, currentLeft);
    posRight = 0;
  } else {
    posMode = 'right';
    posRight = Math.min(20, screenWidth - currentLeft);
    posLeft = 0;
  }
}
```

**Behavior:** Snaps to left or right edge based on position.

## Template

```svelte
<div 
  class="timer"
  class:dragging
  style="
    top: {posTop}px;
    {posMode === 'right' ? `right: ${posRight}px` : `left: ${posLeft}px`};
    color: {timerColor};
    box-shadow: {timerShadow};
  "
  on:mousedown={onDragStart}
  on:mousemove={onDragMove}
  on:mouseup={onDragEnd}
  on:mouseleave={onDragEnd}
>
  <!-- Time display -->
  <div class="time-display">{formatTime(totalSeconds)}</div>
  
  <!-- Controls -->
  <div class="controls">
    <button onclick={() => addMinutes(1)}>+1m</button>
    <button onclick={() => addMinutes(5)}>+5m</button>
    <button onclick={toggle}>{running ? 'Pause' : 'Start'}</button>
    <button onclick={onClose}>✕</button>
  </div>
  
  <!-- Alarm indicator -->
  {#if alarming}
    <div class="alarm-indicator">🔔</div>
  {/if}
</div>
```

## Styling

```css
.timer {
  position: fixed;
  z-index: 50;
  background: rgba(0, 0, 0, 0.8);
  border-radius: 12px;
  padding: 16px 20px;
  cursor: move;
  user-select: none;
  transition: color 0.3s, box-shadow 0.3s;
}

.time-display {
  font-size: 32px;
  font-weight: 700;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.controls {
  display: flex;
  gap: 8px;
  justify-content: center;
  margin-top: 12px;
}

.controls button {
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  color: inherit;
  cursor: pointer;
}

.controls button:hover {
  background: rgba(255, 255, 255, 0.2);
}

.alarm-indicator {
  position: absolute;
  top: -10px;
  right: -10px;
  font-size: 24px;
  animation: ring 0.5s infinite;
}

@keyframes ring {
  0%, 100% { transform: rotate(0); }
  25% { transform: rotate(15deg); }
  75% { transform: rotate(-15deg); }
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/main/jobs/check-reminders.ts` - Reminder system (related timing)

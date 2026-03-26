# Settings UI Overhaul

**Date:** 2026-03-26
**Status:** Draft

## Problem

Settings is a 540px-wide floating modal. The app window is 622x830px. Seven tabs with dense content are cramped. The new AgentsTab split-panel needs width. Console output is capped at 500px height.

## Solution

Transform Settings from a modal overlay into a full-window panel with sidebar navigation. Every pixel of the window is used.

## Layout

Full-window, two-panel: sidebar nav (180px) + content area (flex: 1).

### Sidebar (180px)
- Close button (back arrow) at top
- Current agent indicator (name + dot)
- Navigation items grouped:
  - General: Settings, Agents
  - Data: Usage, Activity
  - System: Jobs, Updates, Console
- Each item: label + optional badge (Updates pending count)
- Active state: left accent border + brighter text
- Background: slightly darker than content (`rgba(10, 10, 12, 0.98)`)

### Content Area
- Full remaining width, full height
- Scrollable per-tab
- Padding: 24px on normal tabs, 0 on AgentsTab
- No max-width cap - content flows naturally

### Per-Tab Changes

**SettingsTab:** Two-column CSS grid for short form fields. Full-width rows for textareas, sliders, and section headers. Reduces vertical scroll by ~40%.

**AgentsTab:** Already split-panel - just fills the larger space. Left panel stays 280px, right panel gets more room.

**UsageTab:** No structural changes. Cards expand with width.

**ActivityTab:** No structural changes. More horizontal room for action text.

**JobsTab:** No structural changes.

**UpdatesTab:** No structural changes.

**ConsoleTab:** Remove max-height: 500px. Console output fills the full content height.

## CSS Changes

### Settings.svelte
- Remove `max-width: 540px`, `max-height: 85%`, `border-radius: 16px`
- `inset: 0` (already set), remove centering transforms
- Change from column (header + content) to row (sidebar + content)
- Remove horizontal tab bar entirely
- Add sidebar component or inline sidebar nav

### SettingsTab.svelte
- Add two-column grid: `display: grid; grid-template-columns: 1fr 1fr; gap: 0 24px`
- Section headers: `grid-column: 1 / -1`
- Long fields (textareas, paths): `grid-column: 1 / -1`
- Short fields (inputs, selects, checkboxes): single column cell

### ConsoleTab.svelte
- Remove `max-height: 500px` from `.console-output`
- Set `flex: 1` to fill available height

## Animation
- Settings slides in from left (200ms ease-out) on open
- Slides back out on close
- No backdrop blur needed since it replaces the chat view entirely

## Window Interaction
- When Settings is open, the chat interface is hidden (not just overlaid)
- Back button or Escape returns to chat
- Global shortcuts (Cmd+Shift+] for agent cycling) still work
- The app title bar / drag region is preserved

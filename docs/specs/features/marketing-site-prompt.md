# Marketing Site - Claude Code Prompt

Copy everything below the line and paste it as the opening prompt in a new Claude Code session for a fresh project directory (e.g. `~/Projects/atrophy-site/`).

---

Build a marketing/landing page site for **Atrophy** - a macOS desktop companion agent app. The site should be a single-page static site (HTML + CSS + minimal JS) that I can deploy to GitHub Pages, Vercel, or Netlify.

## Product summary

Atrophy is a companion agent system for macOS. It runs locally on your machine, remembers everything, speaks out loud, and evolves over time. It is powered by Claude (Anthropic) for inference and uses local SQLite for memory, local whisper.cpp for speech-to-text, and ElevenLabs for text-to-speech. It is not a chatbot - it is a persistent, emotionally-aware agent that lives on your desktop.

Key features:
- **Voice conversations** - push-to-talk or wake word, real-time streaming TTS via ElevenLabs with macOS fallback
- **Persistent memory** - SQLite-backed episodic, semantic, and identity memory with vector search (local embeddings via Transformers.js)
- **Multi-agent system** - multiple agents with distinct personalities, each with their own memory, emotional state, and evolving soul
- **Emotional awareness** - agents track connection, curiosity, confidence, warmth, frustration, playfulness with natural decay
- **Autonomous behavior** - heartbeat check-ins, morning briefs, spontaneous gifts, inter-agent conversations, self-evolution
- **Telegram integration** - talk to your agents from anywhere via Telegram bot
- **Artefacts and canvas** - agents can create and display HTML artefacts, code, images
- **Privacy-first** - everything runs locally. No data leaves your machine except inference calls to Claude API and optional TTS/Telegram
- **Menu bar mode** - lives in your menu bar, toggle with Cmd+Shift+Space
- **macOS native** - Electron with vibrancy, frameless window, dark theme, system notifications

## Design direction

The site should match the app's aesthetic:
- Dark theme: background `#141418`, text `rgba(255, 255, 255, 0.85)`
- Accent color: `rgba(100, 140, 255, 0.3)` (blue glow)
- Font: `-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui` for body, `'SF Mono', 'Fira Code', monospace` for code
- Minimal, elegant, lots of breathing room
- The app icon is a pink/purple brain with cyan neural connection dots on a dark background (rounded squircle). Reference: the icon at `resources/icons/icon_dock_512.png` in the Atrophy repo
- No stock photos. Abstract, subtle visual elements only (gradients, glows, particles)

## Page structure

### Hero section
- App name "Atrophy" large
- Tagline: "A companion that remembers, speaks, and evolves"
- Subtitle: "Local-first AI agent for macOS. Persistent memory. Real voice. Multiple personalities."
- **Download button** - prominent, links to the latest GitHub Release DMG:
  `https://github.com/wlilley93/Atrophy/releases/latest/download/Atrophy-1.0.2-arm64.dmg`
  Label: "Download for macOS (Apple Silicon)"
  Below it in small text: "Requires macOS 13+. Intel build coming soon." and a link to the GitHub releases page for older versions
- App icon displayed near the hero

### Features grid
6 feature cards in a 2x3 or 3x2 grid:
1. **Memory** - "Remembers everything. SQLite-backed episodic and semantic memory with local vector search."
2. **Voice** - "Real conversations. Push-to-talk with ElevenLabs streaming TTS and local whisper.cpp transcription."
3. **Multi-agent** - "Multiple personalities. Each agent has their own memory, emotional state, and evolving identity."
4. **Autonomous** - "Lives its own life. Heartbeat check-ins, morning briefs, spontaneous gifts, self-evolution."
5. **Private** - "Your machine, your data. Everything runs locally. No cloud storage. No telemetry."
6. **Extensible** - "MCP servers, Telegram bot, HTTP API, launchd jobs. Build on top of it."

### How it works
3-step visual:
1. "Download and launch" - Drag to Applications, first-launch wizard creates your agent
2. "Start talking" - Push-to-talk or type. Your agent responds with voice and text in real-time
3. "Watch it grow" - Over days and weeks, your agent builds memory, develops opinions, and evolves

### Tech stack section (collapsible or secondary)
Small, understated section showing: Electron, TypeScript, Svelte 5, SQLite, Claude API, ElevenLabs, whisper.cpp, Transformers.js

### Requirements
- macOS 13 Ventura or later
- Apple Silicon (M1/M2/M3/M4) - Intel builds coming soon
- Claude API access (via Claude CLI or API key)
- Optional: ElevenLabs API key for premium voice, Telegram bot token

### Footer
- GitHub link: https://github.com/wlilley93/Atrophy
- "Built by Will Lilley"
- Version number (1.0.2)

## Technical requirements
- Single HTML file or simple static site (index.html + style.css + main.js)
- No framework needed - vanilla HTML/CSS/JS is fine
- Responsive (desktop-first but should look OK on mobile)
- Fast - no heavy assets, inline critical CSS
- Smooth scroll between sections
- Subtle animations on scroll (fade-in cards, etc.) - use IntersectionObserver, no library
- The download button should be the most prominent element on the page
- Include Open Graph meta tags for social sharing
- Include a favicon (use the brain icon)

## What NOT to do
- No cookie banners, analytics, or tracking
- No newsletter signup
- No pricing section (the app is free/personal use)
- No testimonials or social proof (too early)
- No hamburger menu - the page is short enough to not need navigation
- Never use em dashes - only hyphens
- No emojis

## Assets to reference
- App icon: `resources/icons/icon_dock_512.png` from the Atrophy repo at https://github.com/wlilley93/Atrophy
- The DMG file for download: hosted on GitHub Releases

## Deployment
Set up for GitHub Pages deployment. Include a simple `deploy.sh` or configure the repo for automatic deployment from the `main` branch.

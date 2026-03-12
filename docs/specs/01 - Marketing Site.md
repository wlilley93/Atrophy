# Marketing Site — theatrophiedmind.com

A single-page site that does one thing: makes you want to open the app.

Not a product page. Not a landing page. An atmosphere with a download button.

---

## Principles

**Show the void, then fill it.** The site should make you feel the absence before it offers the presence. You land on near-black. You see the orb. You read three lines. You understand.

**No selling.** No "AI-powered." No "revolutionary." No "unlock your potential." The app is strange and specific. The site should be too. If someone doesn't get it in 10 seconds, they're not the audience. That's fine.

**Quiet authority.** The kind of site where you scroll slowly because the atmosphere is doing something. Like opening a terminal at 2am and finding something that actually works.

**Honest about everything.** Requirements, costs, limitations. Listed plainly. No asterisks, no "starting from," no fine print. If it costs money, say how much. If it only runs on macOS, say that first.

---

## Design Tokens

### Colour

The palette is derived from the app itself. Near-black with cold blue undertones. The only warmth comes from the brain's neural glow.

```
--bg-primary:        #0a0a12
--bg-secondary:      #0f0f1a
--bg-surface:        rgba(255, 255, 255, 0.03)
--bg-surface-hover:  rgba(255, 255, 255, 0.05)
--bg-surface-border: rgba(255, 255, 255, 0.06)

--text-primary:      rgba(255, 255, 255, 0.88)
--text-secondary:    rgba(255, 255, 255, 0.50)
--text-tertiary:     rgba(255, 255, 255, 0.30)
--text-inverse:      #0a0a12

--accent-blue:       rgba(100, 140, 255, 0.85)
--accent-blue-dim:   rgba(100, 140, 255, 0.40)
--accent-blue-glow:  rgba(100, 140, 255, 0.12)
--accent-cyan:       #5ce0d6
--accent-cyan-glow:  rgba(92, 224, 214, 0.15)
--accent-warm:       rgba(230, 160, 60, 0.70)

--border-subtle:     rgba(255, 255, 255, 0.06)
--border-medium:     rgba(255, 255, 255, 0.12)

--code-bg:           rgba(255, 255, 255, 0.04)
--code-text:         rgba(255, 255, 255, 0.65)
```

**Usage rules:**
- `--text-primary` for headings and body. Never pure white.
- `--text-secondary` for supporting text, descriptions, captions.
- `--accent-blue` for links and interactive elements only. Never decorative.
- `--accent-cyan` is the orb colour. Used once in the hero glow and once in the footer. Nowhere else.
- `--accent-warm` is reserved for cost/price callouts. The only warm colour on the page.
- No gradients on text. No gradient backgrounds. The background is flat `--bg-primary`.

### Typography

```
--font-body:         'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif
--font-mono:         'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace
--font-display:      'Inter', -apple-system, sans-serif

--text-xs:           0.75rem     /* 12px — labels, fine print */
--text-sm:           0.875rem    /* 14px — captions, meta */
--text-base:         1rem        /* 16px — body */
--text-lg:           1.125rem    /* 18px — lead paragraphs */
--text-xl:           1.375rem    /* 22px — section heads */
--text-2xl:          1.75rem     /* 28px — hero title */
--text-3xl:          2.5rem      /* 40px — hero title (desktop) */

--weight-normal:     400
--weight-medium:     500
--weight-semibold:   600

--leading-tight:     1.3
--leading-normal:    1.65
--leading-relaxed:   1.8

--tracking-normal:   0
--tracking-wide:     0.06em
--tracking-display:  0.15em
```

**Rules:**
- Body text: `--text-base`, `--weight-normal`, `--leading-normal`. Maximum 65 characters per line.
- Headings: `--font-display`, `--weight-medium`, `--leading-tight`. Never bold. Medium weight only.
- The title "THE ATROPHIED MIND" is always uppercase, always `--tracking-display`.
- Code snippets: `--font-mono`, `--text-sm`, `--code-bg` background, 2px border-radius.
- No italic anywhere on the page. Not in body, not in captions, nowhere.

### Spacing

```
--space-xs:    0.25rem    /* 4px */
--space-sm:    0.5rem     /* 8px */
--space-md:    1rem       /* 16px */
--space-lg:    1.5rem     /* 24px */
--space-xl:    2.5rem     /* 40px */
--space-2xl:   4rem       /* 64px */
--space-3xl:   6rem       /* 96px */
--space-4xl:   10rem      /* 160px */

--content-width:     720px
--grid-width:        960px
--max-width:         1080px
```

**Rules:**
- Sections are separated by `--space-4xl` (160px). This is not negotiable. The page breathes.
- Content never exceeds `--content-width` for text, `--grid-width` for grids.
- Horizontal padding: `--space-lg` on mobile, `--space-xl` on tablet+.
- No section has less than one full viewport of breathing room.

### Borders & Surfaces

```
--radius-sm:     4px
--radius-md:     8px
--radius-lg:     12px
--radius-pill:   9999px

--shadow-glow:   0 0 60px var(--accent-cyan-glow)
--shadow-subtle: 0 1px 2px rgba(0, 0, 0, 0.3)
```

**Rules:**
- Cards and surfaces use `--border-subtle` with `--radius-md`.
- No drop shadows on cards. The border is enough.
- The orb glow (`--shadow-glow`) is the only glow effect on the page.
- No box shadows on buttons. Buttons are defined by border and background.

### Motion

```
--duration-fast:    150ms
--duration-normal:  300ms
--duration-slow:    600ms
--duration-pulse:   4000ms

--ease-default:     cubic-bezier(0.4, 0, 0.2, 1)
--ease-out:         cubic-bezier(0, 0, 0.2, 1)
--ease-spring:      cubic-bezier(0.34, 1.56, 0.64, 1)
```

**Rules:**
- Links: `--duration-fast` colour transition.
- The brain pulse: `--duration-pulse` opacity oscillation, 0.7 → 1.0. Runs forever. Subtle.
- No scroll animations. No intersection observer reveals. No fade-ins on scroll. Content is there when you get to it.
- No parallax. No scroll-jacking. Native scroll.
- The only animation on the page is the brain pulse and link hovers.

---

## Texture

One effect. Used sparingly.

```css
.grain::after {
    content: '';
    position: fixed;
    inset: 0;
    background-image: url("data:image/svg+xml,...");  /* 200x200 noise tile */
    opacity: 0.025;
    pointer-events: none;
    z-index: 9999;
}
```

2.5% opacity film grain over the entire page. Fixed position, so it doesn't scroll. Adds the faintest texture to the flat black. Remove it and the page feels clinical. Add more and it feels affected.

No other textures. No patterns. No geometric decorations. No floating particles.

---

## Page Structure

Seven sections. Each earns its presence.

### 1. HERO

The first thing. The only thing for most of the viewport.

```
[brain icon — 120px, pulsing, cyan glow halo]

THE ATROPHIED MIND

Offload your mind.

[Download for macOS]     [GitHub →]
```

**Specifics:**
- Brain icon: 120px, centered. Faint pulse animation (opacity 0.7→1.0, 4s cycle). Cyan glow: `box-shadow: 0 0 60px var(--accent-cyan-glow)`.
- Title: `--text-3xl` on desktop, `--text-2xl` on mobile. `--tracking-display`. `--weight-medium`. `--text-primary`.
- Subtitle: `--text-lg`. `--text-secondary`. One line. No period.
- Download button: `--accent-blue` background at 20% opacity, `--accent-blue-dim` border, `--text-primary` text. Pill shape (`--radius-pill`). Padding: `12px 32px`. Hover: background opacity to 30%.
- GitHub link: Ghost button. `--border-subtle` border, `--text-secondary` text. Same pill shape. Hover: `--text-primary`.
- Vertical spacing: icon to title `--space-xl`, title to subtitle `--space-md`, subtitle to buttons `--space-xl`.
- The hero occupies 100vh. Content is vertically centered.
- Below the fold line, nothing. Just black. The scroll invitation is the emptiness.

### 2. WHAT IT IS

Three sentences. Centered. No heading.

```
A companion that lives on your Mac. It remembers your conversations,
speaks in a voice you chose, reflects on what matters, and reaches out
when something needs your attention. You own everything — the memory,
the identity, the infrastructure. Nothing leaves your machine unless
you want it to.
```

**Specifics:**
- `--text-lg`. `--text-secondary`. `--leading-relaxed`. Centered.
- Max width: `--content-width`.
- No heading. No label. No "What is it?" The text speaks for itself.
- Single paragraph. 3-4 sentences max.

### 3. CAPABILITIES

What it can do. Not features — capabilities.

```
VOICE                          MEMORY
Push-to-talk with local        Three-layer architecture:
speech recognition.            conversations, summaries,
ElevenLabs for speech.         and evolving observations
Speaks, listens, remembers     about you. Semantic search
what was said.                 across everything.

AUTONOMY                       IDENTITY
Background daemons for         Each agent has a personality,
heartbeats, daily reflection,  voice, opinions, and edges.
morning briefs, and monthly    You define who they are.
self-evolution. Reaches out    They become that.
when something matters.

AGENTS                         TOOLS
Multiple agents, each with     Reminders. Timers. Scheduled
their own identity and         tasks. Web browsing. Telegram.
memory. Switch with a          Google Workspace. Agents
keypress. They can hand        can build their own tools.
off to each other.
```

**Specifics:**
- 2-column grid on desktop, single column on mobile.
- Each item: label in `--text-xs`, uppercase, `--tracking-wide`, `--accent-blue`. Description in `--text-sm`, `--text-secondary`, `--leading-normal`.
- Grid gap: `--space-xl` horizontal, `--space-2xl` vertical.
- Surface cards: `--bg-surface` background, `--border-subtle` border, `--radius-md`. Padding: `--space-lg`.
- No icons. The label is the icon. Icons are decoration; this site doesn't decorate.
- Max 6 items. If it doesn't fit in 6, it's not important enough.

### 4. SETUP

How it works. Three steps. Horizontal on desktop, stacked on mobile.

```
01                             02                             03
INSTALL                        CREATE                         USE

Clone the repo or download     On first launch, Xan — the     Talk. Ask questions. Set
the .app. One command          system agent — shows you        reminders. Your companion
installs dependencies.         what's running underneath       remembers, reflects, and
Works offline from day one.    and offers to build your        reaches out between sessions.
                               first companion. Or skip —      It runs in the menu bar.
                               build one later.                Always there. Never in the way.
```

**Specifics:**
- 3-column grid, equal width. Single column on mobile.
- Step numbers: `--text-3xl`, `--text-tertiary`, `--weight-medium`. Decorative, not functional.
- Step labels: `--text-xs`, uppercase, `--tracking-wide`, `--text-primary`.
- Step descriptions: `--text-sm`, `--text-secondary`, `--leading-normal`.
- No connecting lines. No arrows. The numbers do the work.
- The word "Xan" is in `--accent-blue`. It's the only coloured word in this section.

### 5. THE APP

A screenshot. Not a mockup — a real screenshot of the app running.

```
                    [screenshot of the app window]

         "You describe who they are. Xan builds them."
```

**Specifics:**
- Centered screenshot, max-width 520px.
- The screenshot shows the setup wizard mid-conversation with Xan. Dark window, chat bubbles, the Xan header. Real content, not placeholder text.
- macOS window chrome: native dark title bar with traffic lights. Not a browser mockup. Not a flat rectangle. The real window.
- Subtle `--shadow-subtle` beneath the screenshot.
- Caption below: `--text-sm`, `--text-tertiary`, centered.
- No border on the screenshot. The dark window against the dark page creates a seamless bleed. The window chrome is the only frame.

### 6. REQUIREMENTS

What you need. What it costs. No surprises.

```
REQUIREMENTS

macOS 12+
Python 3.12+
Claude Code CLI (free — install with: npm install -g @anthropic-ai/claude-code)


OPTIONAL SERVICES

These are not required. The app works without them.

ElevenLabs — voice          $5/month minimum. Your agent speaks
                            out loud instead of text. Hundreds of
                            voices, or clone your own.

Fal.ai — avatar             Pay-as-you-go. Avatar images ~$0.01,
                            ambient video clips ~$0.30. Your agent
                            gets a face and ambient animation.

Telegram — messaging        Free. Your agent can message you
                            between sessions. Check-ins, briefs,
                            reminders.

Google — workspace          Free (OAuth). Gmail, Calendar, Drive,
                            Sheets, Docs, Tasks, Contacts. Your
                            agent can read, create, and send on
                            your behalf across all of them.
```

**Specifics:**
- Section heading: `--text-xl`, `--weight-medium`, `--text-primary`.
- Requirements list: `--text-base`, `--text-primary`. Plain text, one per line. The Claude Code install command is in `--font-mono`, `--code-bg`.
- "OPTIONAL SERVICES" subheading: `--text-xs`, uppercase, `--tracking-wide`, `--text-secondary`.
- "These are not required" line: `--text-sm`, `--text-tertiary`. Important. Says it plainly.
- Services: 2-column layout. Service name and cost in `--text-sm`, `--text-primary`. The cost figure is in `--accent-warm`. Description in `--text-sm`, `--text-secondary`.
- Services sit inside a `--bg-surface` card with `--border-subtle`. Distinct from the requirements above.
- No "Sign up" links. No affiliate codes. Just information.

### 7. FOOTER

Minimal. The brain returns.

```
                         [brain icon — 40px]
                      THE ATROPHIED MIND

              GitHub     Download     Docs     Privacy

                    Built by Will Lilley.
```

**Specifics:**
- Brain icon: 40px, no pulse, no glow. Static.
- Title: `--text-sm`, `--tracking-display`, `--text-secondary`.
- Links: `--text-xs`, `--accent-blue`, `--tracking-wide`. Spaced with `--space-xl` between them.
- Attribution: `--text-xs`, `--text-tertiary`. A statement, not a link.
- Padding: `--space-3xl` top, `--space-2xl` bottom.
- No social links. No newsletter signup. No cookie banner.

---

## Responsive

Three breakpoints. No more.

```
--bp-mobile:   0 — 639px
--bp-tablet:   640px — 1023px
--bp-desktop:  1024px+
```

**Mobile adjustments:**
- Hero title: `--text-2xl` (down from `--text-3xl`)
- Capability grid: single column
- Setup steps: stacked vertically
- Services: stacked vertically
- Section spacing: `--space-3xl` (down from `--space-4xl`)
- Content padding: `--space-lg`

**Tablet adjustments:**
- Capability grid: 2 columns (same as desktop)
- Setup steps: 3 columns (same as desktop)
- Content padding: `--space-xl`

No hamburger menu. There is no menu. The page is the navigation.

---

## Technical

```
Stack:         Static HTML + CSS. One file each. Optional vanilla JS for the pulse.
Hosting:       GitHub Pages, Cloudflare Pages, or Vercel. All free.
Build:         None. No bundler. No framework. No npm. Copy and deploy.
Performance:   < 50KB total. No external fonts (use system stack). No images except the brain PNG.
Accessibility: Semantic HTML. Proper heading hierarchy. Sufficient contrast ratios. Prefers-reduced-motion disables the pulse.
```

**Meta:**
```html
<title>Atrophy - Offload your mind</title>
<meta name="description" content="A companion agent that lives on your Mac. Voice, memory, autonomy, identity. Yours.">
<meta property="og:title" content="Atrophy">
<meta property="og:description" content="A companion agent that lives on your Mac. Voice, memory, autonomy, identity. Yours.">
<meta property="og:image" content="/og.png">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
```

**OG Image:** 1200x630px. `--bg-primary` background. Brain icon centered, 200px. Title below in white. Subtitle in `--text-secondary`. Simple. Recognisable. Looks good when shared on Twitter/LinkedIn/Discord.

---

## What This Site Is Not

- Not a SaaS landing page. No pricing tiers. No "Start free trial."
- Not an open-source project page. No contributor stats. No badge wall.
- Not a portfolio piece. No "Built with React + Tailwind + Vercel."
- Not trying to explain AI. No "How AI works" section. No jargon glossary.
- Not competing with anything. No "Unlike ChatGPT..." comparisons.
- Not a product tour. No animated demos. No interactive playground.

It's a dark room with a glowing orb and a download button. That's the site.

---

## Copy Direction

Every word on this page should sound like it was written at 2am by someone who cares about the craft but not about impressing you. No marketing voice. No startup voice. No developer voice. Just clarity.

**Do:**
- State facts. "It remembers." "It speaks." "It reaches out."
- Be specific about costs. "$5/month minimum."
- Acknowledge limitations. "macOS only."
- Use short sentences. The page should read fast.

**Don't:**
- Use superlatives. Not "best," not "most powerful," not "revolutionary."
- Use buzzwords. Not "AI-powered," not "cutting-edge," not "next-gen."
- Address the reader as "you" more than necessary. The site describes the thing. It doesn't pitch the reader.
- Explain how AI works. If they're here, they know.
- Promise outcomes. "It might help. It might not. It definitely remembers."

---

## Hosted Docs

When the site is live, docs will be served at `theatrophiedmind.com/docs/` (or a subdomain: `docs.theatrophiedmind.com`). The same markdown files from the repo's `docs/` directory, rendered with a minimal dark theme matching the marketing site tokens.

Agents will be able to fetch docs from the hosted URL via puppeteer/web tools as an alternative to the local `read_docs` MCP tool. Local-first, hosted as fallback.

The docs site uses the same design tokens but adds a sidebar navigation tree and a search bar. Same dark background, same typography, same spacing. No branding change between marketing and docs — they're the same site.

---

## Privacy Policy

Hosted at `theatrophiedmind.com/privacy`. Same design tokens as the main site. Plain text, no legalese where possible. Required for Google OAuth verification.

### URL

`theatrophiedmind.com/privacy`

### Content

```
PRIVACY POLICY

Last updated: March 2026


WHAT THIS APP IS

Atrophy is a local-first companion agent that runs on your
Mac. It is not a cloud service. There is no account. There is no server.


WHAT DATA STAYS ON YOUR MACHINE

Everything.

- Conversations and memory — stored in a local SQLite database
- Voice recordings — processed locally, never uploaded
- Agent identities and configuration — local files
- OAuth tokens — stored in ~/.atrophy/ and ~/.config/gws/
- All runtime state — local files, never transmitted


GOOGLE INTEGRATION

If you choose to connect your Google account, the app accesses the
following services on your behalf:

- Gmail — read, search, send, and manage email
- Google Calendar — read, create, update, and delete events
- Google Drive — search, read, upload, and manage files
- Google Sheets — read and write spreadsheets
- Google Docs — read and create documents
- Google Slides — read and create presentations
- Google Tasks — read and manage task lists
- Google Contacts (People) — search and read contacts
- Google Meet — create and manage meeting spaces
- Google Forms — read forms and responses
- Google Keep — read and manage notes
- YouTube — search, read, and manage videos, playlists, and subscriptions
- Google Photos — browse and organise photos and albums
- Google Search Console — read search analytics and site data

HOW GOOGLE DATA IS USED:

- Google data is fetched on-device when your agent needs it
- Data is passed to the Claude API for processing (Anthropic's LLM)
- No Google data is stored permanently beyond local conversation memory
- No Google data is shared with any third party other than Anthropic
  (for inference processing only)
- OAuth tokens are stored locally and never transmitted to us
- You can revoke access at any time via Google Account settings or
  by running: python scripts/google_auth.py --revoke

WHAT WE DO NOT DO:

- We do not operate servers that receive your data
- We do not collect analytics or telemetry
- We do not store your Google data on any remote system
- We do not sell, share, or monetise any user data
- We do not access your data — only your local agent does


THIRD-PARTY SERVICES

The app connects to these external services only when you configure them:

- Anthropic (Claude API) — LLM inference. Your conversations are sent
  to Anthropic's API for processing. See: anthropic.com/privacy
- ElevenLabs — text-to-speech (optional). Text is sent to generate
  speech audio. See: elevenlabs.io/privacy
- Telegram — messaging (optional). Messages are sent via Telegram's
  Bot API. See: telegram.org/privacy
- Google APIs — as listed above (optional). Data is accessed via
  Google's OAuth2 protocol. See: policies.google.com/privacy

No data is sent to any service you have not explicitly configured.


CHILDREN

This app is not directed at children under 13.


DATA DELETION

All data is local. Delete ~/.atrophy/ to remove everything. To revoke
Google access: python scripts/google_auth.py --revoke, or visit
myaccount.google.com/permissions.


CHANGES

If this policy changes, the update date at the top will change.
No other notification mechanism exists because we don't have
your email address.


CONTACT

Will Lilley — will@theatrophiedmind.com
GitHub: github.com/willlilley/the-atrophied-mind
```

### Specifics

- Same `--bg-primary` background, same typography as main site.
- Title: `--text-xl`, `--weight-medium`, `--text-primary`.
- Section headings: `--text-base`, `--weight-medium`, `--text-primary`, uppercase.
- Body: `--text-sm`, `--text-secondary`, `--leading-relaxed`.
- Service list: plain text, one per line, no bullets needed.
- Max width: `--content-width` (720px).
- No sidebar. No navigation. Just the back-to-home brain icon at the top.
- Footer: same as main site.

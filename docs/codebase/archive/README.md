# Archived Documentation

This directory contains legacy overview documents that were superseded by the detailed file-by-file documentation in [`../files/`](../files/).

## Contents

| File | Description |
|------|-------------|
| `00 - Overview.md` | Original architecture overview, startup sequence, window creation details |
| `01 - Core Modules.md` | Core modules overview (logger, config, memory, session, status) |
| `02 - Voice Pipeline.md` | Voice system architecture (audio, stt, tts, wake-word, call) |
| `03 - Display System.md` | GUI system and Svelte 5 components |
| `04 - Memory Architecture.md` | Three-layer memory system (Episodic, Semantic, Identity) |
| `05 - MCP Server.md` | MCP server system and tool architecture |
| `06 - Channels.md` | External communication channels (Telegram, switchboard) |
| `07 - Scripts and Automation.md` | Background jobs and cron system |
| `10 - Building and Distribution.md` | Build process, code signing, auto-updates |

## Relationship to New Documentation

The new documentation in [`../files/`](../files/) provides:
- **File-by-file detail** - Each source file has a corresponding `.md` with complete API documentation
- **Mirrored structure** - Directory structure matches `src/` layout
- **Implementation details** - Function signatures, code examples, flow diagrams
- **Cross-references** - Links between related modules

The archived documents contain:
- **High-level architecture** - System overview and design decisions
- **Historical context** - Original design rationale
- **Narrative explanations** - Prose descriptions of how systems work

## When to Use Archived Docs

Use the archived documents when:
1. You need a high-level overview of a subsystem
2. You want to understand the original design rationale
3. You're looking for narrative explanations of architecture

Use the new `files/` documentation when:
1. You need to understand a specific file's implementation
2. You need API signatures and exported functions
3. You're recreating or modifying code

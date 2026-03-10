#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  The Atrophied Mind — First-Time Setup
# ─────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │  THE ATROPHIED MIND                  │"
echo "  │  First-Time Setup                    │"
echo "  └──────────────────────────────────────┘"
echo ""

# ── Check Python ──
if ! command -v python3 &>/dev/null; then
    echo "  ✗ Python 3 is required. Install from https://python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PYTHON_VERSION"

# ── Check Claude Code ──
if ! command -v claude &>/dev/null; then
    echo ""
    echo "  ✗ Claude Code is required but not installed."
    echo ""
    echo "    Install with one of:"
    echo "      npm install -g @anthropic-ai/claude-code"
    echo "      brew install claude-code"
    echo ""
    echo "    Or download from: https://claude.ai/download"
    echo ""
    exit 1
fi

echo "  ✓ Claude Code found"

# ── Install Python dependencies ──
echo ""
echo "  Installing Python dependencies..."
cd "$PROJECT_ROOT"
pip3 install -q -r requirements.txt 2>/dev/null || pip install -q -r requirements.txt 2>/dev/null
echo "  ✓ Dependencies installed"

# ── Check for .env ──
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo ""
    echo "  Creating .env file..."
    touch "$PROJECT_ROOT/.env"
    echo "  ✓ Created .env"
fi

# ── Check for existing agents ──
AGENT_COUNT=$(find "$PROJECT_ROOT/agents" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

echo ""
if [ "$AGENT_COUNT" -eq 0 ]; then
    echo "  No agents found. Let's create your first one."
elif [ "$AGENT_COUNT" -eq 1 ]; then
    EXISTING=$(basename "$(find "$PROJECT_ROOT/agents" -mindepth 1 -maxdepth 1 -type d)")
    echo "  Found existing agent: $EXISTING"
    echo "  You can create additional agents or start using the system."
fi

echo ""
echo "  ─────────────────────────────────────────────"
echo ""
echo "  Setup complete. To create your agent:"
echo ""
echo "    1. Open a terminal in this directory"
echo "    2. Run:  claude"
echo "    3. Say:  Create my first agent"
echo ""
echo "    Claude will walk you through everything —"
echo "    identity, voice, appearance, and all the rest."
echo ""
echo "  Or use the interactive script directly:"
echo "    python scripts/create_agent.py"
echo ""
echo "  ─────────────────────────────────────────────"
echo ""

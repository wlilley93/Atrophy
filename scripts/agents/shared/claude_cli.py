"""
Shared Claude CLI helper for all Meridian agents.

All LLM calls route through the local Claude CLI binary. No Anthropic SDK,
no API key required. Scripts import this via sys.path manipulation:

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    from claude_cli import call_claude
"""
from __future__ import annotations

import subprocess
import shutil

CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def call_claude(
    system: str,
    prompt: str,
    model: str = "sonnet",
    timeout: int = 120,
) -> str:
    """One-shot Claude call via CLI. Returns response text.

    Args:
        system:  System prompt.
        prompt:  User message.
        model:   Model alias - 'haiku' for triage, 'sonnet' for analysis.
        timeout: Subprocess timeout in seconds (default 120).

    Raises:
        RuntimeError: If the CLI exits non-zero.
    """
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude exited {result.returncode}: {result.stderr[:200]}"
        )
    return result.stdout.strip()

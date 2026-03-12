#!/usr/bin/env python3
"""Scoped shell MCP server for the companion agent.

Provides sandboxed shell access with:
- Command allowlist (homebrew, git, find, ls, cat, grep, etc.)
- Path restrictions (no access to credentials, .env, tokens)
- Timeout enforcement (30s default)
- Working directory confinement (user home by default)
- Output truncation to prevent context flooding

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Max seconds a command can run
TIMEOUT = int(os.environ.get("SHELL_TIMEOUT", "30"))

# Max output bytes returned to the agent
MAX_OUTPUT = int(os.environ.get("SHELL_MAX_OUTPUT", "32000"))

# Working directory - defaults to user home
WORKING_DIR = os.environ.get("SHELL_WORKING_DIR", str(Path.home()))

# ---------------------------------------------------------------------------
# Security: command allowlist
# ---------------------------------------------------------------------------

# Binaries the agent is allowed to invoke directly.
# Sub-commands are further filtered where needed.
ALLOWED_BINARIES = {
    # File exploration
    "ls", "find", "file", "wc", "du", "df", "stat", "tree",
    # Reading files (non-sensitive paths checked separately)
    "cat", "head", "tail", "less", "bat",
    # Searching
    "grep", "rg", "ag", "fd", "fzf",
    # Text processing
    "sort", "uniq", "cut", "tr", "awk", "sed", "jq", "yq",
    # Homebrew
    "brew",
    # Git (read operations + safe writes)
    "git",
    # Node / Python tooling
    "node", "npm", "pnpm", "yarn", "bun",
    "python3", "pip3", "uv", "pipx",
    # System info
    "uname", "sw_vers", "sysctl", "whoami", "id", "date", "cal",
    "uptime", "top", "ps", "lsof", "which", "where", "type",
    "env", "printenv",
    # Networking (read-only)
    "ping", "dig", "nslookup", "host", "curl", "wget", "httpie",
    # Disk / process
    "open", "pbcopy", "pbpaste",
    # Compression
    "tar", "zip", "unzip", "gzip", "gunzip",
    # Editors (non-interactive, for piping)
    "echo", "printf", "tee",
    # Development
    "cargo", "go", "rustc", "gcc", "clang",
    "docker", "docker-compose",
    # Misc
    "realpath", "basename", "dirname", "mktemp", "touch", "mkdir",
    "cp", "mv", "ln",
}

# Binaries that are always blocked, even if somehow in the allowed set.
BLOCKED_BINARIES = {
    "rm", "rmdir", "shred",
    "sudo", "su", "doas",
    "shutdown", "reboot", "halt", "poweroff",
    "dd", "mkfs", "fdisk", "diskutil",
    "nmap", "masscan", "nc", "netcat",
    "kill", "killall", "pkill",
    "chown", "chgrp", "chmod",
    "launchctl", "systemctl",
    "defaults",  # macOS defaults write can be destructive
    "sqlite3",   # direct DB access - use memory MCP instead
    "osascript",  # AppleScript injection risk
    "security",   # keychain access
    # Shells - block as pipe targets and direct invocation to prevent sandbox escape
    "bash", "sh", "zsh", "fish", "csh", "tcsh", "ksh", "dash",
    "perl", "ruby", "php", "lua",
}

# Git subcommands that are blocked (destructive or remote-pushing)
BLOCKED_GIT_SUBCOMMANDS = {
    "push", "push --force", "reset --hard", "clean",
    "checkout -- .", "restore .",
}

# Dangerous argument patterns for specific binaries
# These binaries can execute arbitrary shell commands via their arguments
DANGEROUS_ARG_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    # awk: system(), pipe to shell via |"sh", or -f with arbitrary file
    "awk": [re.compile(r"system\s*\("), re.compile(r"\|\s*\"?(?:ba)?sh")],
    # sed: e flag executes pattern space as shell command
    "sed": [re.compile(r"(?:^|[^\\])/e(?:\b|$)"), re.compile(r"-e\b.*\be\b")],
    # find: -exec runs arbitrary commands (already in allowlist, but could run blocked binaries)
    "find": [re.compile(r"-exec\b"), re.compile(r"-execdir\b"), re.compile(r"-delete\b")],
    # xargs: can invoke any binary as argument
    "xargs": [re.compile(r".*")],  # always block - too dangerous
    # docker: host volume mounts can access anything
    "docker": [re.compile(r"-v\b.*:/"), re.compile(r"--volume\b.*:/"),
               re.compile(r"--privileged"), re.compile(r"--pid=host"),
               re.compile(r"--net=host"), re.compile(r"--network=host")],
    # make: can run arbitrary shell via Makefile targets
    "make": [re.compile(r".*")],  # always block - executes arbitrary shell from Makefiles
    # npm/pnpm/yarn: run can execute arbitrary package.json scripts
    "npm": [re.compile(r"^run\b"), re.compile(r"^exec\b"), re.compile(r"^start\b")],
    "pnpm": [re.compile(r"^run\b"), re.compile(r"^exec\b"), re.compile(r"^start\b"),
             re.compile(r"^dlx\b")],
    "yarn": [re.compile(r"^run\b"), re.compile(r"^exec\b"), re.compile(r"^start\b"),
             re.compile(r"^dlx\b")],
    "npx": [re.compile(r".*")],  # always block - runs arbitrary packages
    # git config --global can set hooks, aliases, etc.
    "git": [re.compile(r"^config\s+--global\b")],
}

# Path patterns that must never appear in commands (case-insensitive)
BLOCKED_PATH_PATTERNS = [
    r"\.env\b",
    r"server_token",
    r"credentials\.json",
    r"token\.json",
    r"config\.json",
    r"\.google\b",
    r"\.ssh\b",
    r"\.gnupg\b",
    r"\.aws\b",
    r"keychain",
    r"/etc/passwd",
    r"/etc/shadow",
    r"\.atrophy/.*\.(json|env|token)",
    r"id_rsa",
    r"id_ed25519",
    r"known_hosts",
    r"authorized_keys",
]

_blocked_path_re = re.compile("|".join(BLOCKED_PATH_PATTERNS), re.IGNORECASE)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_command(command: str) -> str | None:
    """Validate a command string. Returns error message or None if OK."""
    if not command or not command.strip():
        return "Empty command"

    # Block shell operators that could bypass restrictions
    # Allow pipes (|) and redirects (>, >>) for normal shell use,
    # but block command chaining that could run arbitrary binaries
    for dangerous in ["$(", "`", "&&", "||", ";", "\n"]:
        if dangerous in command:
            return (
                f"Command chaining with '{dangerous.strip()}' is not allowed. "
                "Run each command separately."
            )

    # Check redirect targets against blocked paths
    redirect_match = re.search(r">{1,2}\s*(\S+)", command)
    if redirect_match:
        target = redirect_match.group(1)
        if _blocked_path_re.search(target):
            return "Redirect target references a restricted path"

    # Check for blocked path patterns in the full command
    if _blocked_path_re.search(command):
        return "Command references a restricted path (credentials, tokens, keys)"

    # Parse the binary name
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"Could not parse command: {e}"

    if not parts:
        return "Empty command after parsing"

    binary = os.path.basename(parts[0])

    # Block check first
    if binary in BLOCKED_BINARIES:
        return f"'{binary}' is not allowed (blocked for safety)"

    # Allowlist check
    if binary not in ALLOWED_BINARIES:
        return (
            f"'{binary}' is not in the allowed command list. "
            f"Allowed: {', '.join(sorted(ALLOWED_BINARIES))}"
        )

    # Block inline code execution flags that allow arbitrary subprocess spawning
    INLINE_EXEC_FLAGS = {
        "node": {"-e", "--eval", "-p", "--print"},
        "python3": {"-c"},
        "perl": {"-e"},
        "ruby": {"-e"},
        "bun": {"-e", "--eval"},
    }
    if binary in INLINE_EXEC_FLAGS:
        flags = INLINE_EXEC_FLAGS[binary]
        if any(arg in flags for arg in parts[1:]):
            return (
                f"'{binary}' with inline code execution ({', '.join(sorted(flags))}) "
                "is not allowed - use a script file instead"
            )

    # Git subcommand filtering
    if binary == "git" and len(parts) > 1:
        sub = parts[1]
        full_sub = " ".join(parts[1:3]) if len(parts) > 2 else sub
        if sub in BLOCKED_GIT_SUBCOMMANDS or full_sub in BLOCKED_GIT_SUBCOMMANDS:
            return f"'git {full_sub}' is blocked (destructive operation)"

    # Check dangerous argument patterns for specific binaries
    if binary in DANGEROUS_ARG_PATTERNS:
        rest = " ".join(parts[1:])
        for pattern in DANGEROUS_ARG_PATTERNS[binary]:
            if pattern.search(rest):
                return (
                    f"'{binary}' with these arguments is not allowed (potential sandbox escape). "
                    f"Matched pattern: {pattern.pattern}"
                )

    # Validate every binary in a pipe chain (must be allowed AND not blocked)
    if "|" in command:
        pipe_segments = command.split("|")
        for segment in pipe_segments[1:]:
            segment = segment.strip()
            try:
                seg_parts = shlex.split(segment)
            except ValueError:
                continue
            if seg_parts:
                pipe_binary = os.path.basename(seg_parts[0])
                if pipe_binary in BLOCKED_BINARIES:
                    return f"Piping into '{pipe_binary}' is not allowed"
                if pipe_binary not in ALLOWED_BINARIES:
                    return f"Piping into '{pipe_binary}' is not allowed (not in allowlist)"
                # Check dangerous args on pipe targets too
                if pipe_binary in DANGEROUS_ARG_PATTERNS:
                    pipe_rest = " ".join(seg_parts[1:])
                    for pattern in DANGEROUS_ARG_PATTERNS[pipe_binary]:
                        if pattern.search(pipe_rest):
                            return (
                                f"Piping into '{pipe_binary}' with these arguments is not allowed "
                                f"(potential sandbox escape)"
                            )

    return None


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _sanitize_env() -> dict[str, str]:
    """Return a copy of os.environ with sensitive vars stripped."""
    env = dict(os.environ)
    for key in list(env.keys()):
        lower = key.lower()
        if any(s in lower for s in ["secret", "token", "password", "credential", "api_key"]):
            if key not in ("SHELL", "TERM", "PATH", "HOME", "USER"):
                del env[key]
    return env


def _run_pipeline(segments: list[str], cwd: str, env: dict[str, str], timeout: int) -> dict:
    """Execute a pipeline of commands connected by pipes, all with shell=False.

    Each segment is parsed with shlex.split() and piped to the next.
    The last segment's stdout/stderr is captured.
    """
    procs: list[subprocess.Popen[str]] = []
    try:
        prev_stdout = None
        for i, segment in enumerate(segments):
            parts = shlex.split(segment.strip())
            if not parts:
                continue

            # Resolve binary to full path via PATH lookup
            binary = parts[0]
            resolved = shutil.which(binary)
            if resolved:
                parts[0] = resolved

            is_last = i == len(segments) - 1
            proc = subprocess.Popen(
                parts,
                stdin=prev_stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if is_last else subprocess.DEVNULL,
                text=True,
                cwd=cwd,
                env=env,
            )
            # Close the previous process's stdout in the parent so the pipe works
            if prev_stdout is not None:
                prev_stdout.close()
            prev_stdout = proc.stdout
            procs.append(proc)

        if not procs:
            return {"exit_code": -1, "stdout": "", "stderr": "No valid commands in pipeline", "blocked": False}

        # Read output from the last process
        last = procs[-1]
        stdout, stderr = last.communicate(timeout=timeout)

        # Wait for all other procs
        for proc in procs[:-1]:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        return {
            "exit_code": last.returncode,
            "stdout": stdout or "",
            "stderr": stderr or "",
        }

    except subprocess.TimeoutExpired:
        for proc in procs:
            try:
                proc.kill()
            except OSError:
                pass
        return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s", "blocked": False}
    except Exception as e:
        for proc in procs:
            try:
                proc.kill()
            except OSError:
                pass
        return {"exit_code": -1, "stdout": "", "stderr": f"Execution error: {e}", "blocked": False}


def _handle_redirects(command: str) -> tuple[str, str | None, bool]:
    """Extract output redirect from command string.

    Returns (command_without_redirect, redirect_path, is_append).
    """
    # Match >> or > followed by a path (simple cases only)
    append_match = re.search(r">>\s*(\S+)\s*$", command)
    if append_match:
        return command[:append_match.start()].strip(), append_match.group(1), True
    write_match = re.search(r">\s*(\S+)\s*$", command)
    if write_match:
        return command[:write_match.start()].strip(), write_match.group(1), False
    return command, None, False


def run_command(command: str, working_dir: str | None = None, timeout: int | None = None) -> dict:
    """Run a validated shell command and return structured output.

    CRITICAL: Uses shell=False to prevent sandbox escapes via awk system(),
    sed e flag, docker host mounts, npm run scripts, make targets, etc.
    Pipes are handled by spawning a process pipeline explicitly.
    """
    error = validate_command(command)
    if error:
        return {"exit_code": -1, "stdout": "", "stderr": error, "blocked": True}

    cwd = working_dir or WORKING_DIR
    if not os.path.isdir(cwd):
        cwd = str(Path.home())

    t = timeout or TIMEOUT
    env = _sanitize_env()

    # Handle output redirects before splitting into pipeline
    command_body, redirect_path, is_append = _handle_redirects(command)

    # Split into pipe segments
    segments = command_body.split("|")

    try:
        result = _run_pipeline(segments, cwd, env, t)

        if result.get("blocked"):
            return result

        stdout = result["stdout"]
        stderr = result["stderr"]

        # Write to redirect target if specified
        if redirect_path and result["exit_code"] == 0:
            redirect_full = os.path.join(cwd, redirect_path) if not os.path.isabs(redirect_path) else redirect_path
            # Resolve to real path and validate against blocked patterns + cwd sandbox
            redirect_resolved = os.path.realpath(redirect_full)
            if _blocked_path_re.search(redirect_resolved):
                return {"exit_code": -1, "stdout": "", "stderr": "Redirect target references a restricted path", "blocked": True}
            cwd_resolved = os.path.realpath(cwd)
            if not redirect_resolved.startswith(cwd_resolved + os.sep) and redirect_resolved != cwd_resolved:
                # Allow writing to subdirs of cwd, but not escaping via ../
                home_resolved = os.path.realpath(str(Path.home()))
                if not redirect_resolved.startswith(home_resolved + os.sep):
                    return {"exit_code": -1, "stdout": "", "stderr": "Redirect target is outside allowed directories", "blocked": True}
            mode = "a" if is_append else "w"
            try:
                with open(redirect_full, mode) as f:
                    f.write(stdout)
                stdout = f"(output written to {redirect_path})"
            except OSError as e:
                return {"exit_code": -1, "stdout": "", "stderr": f"Redirect failed: {e}", "blocked": False}

        # Truncate if too long
        truncated = False
        if len(stdout) > MAX_OUTPUT:
            stdout = stdout[:MAX_OUTPUT] + f"\n\n... (truncated, {len(result['stdout'])} bytes total)"
            truncated = True
        if len(stderr) > MAX_OUTPUT // 4:
            stderr = stderr[:MAX_OUTPUT // 4] + "\n... (truncated)"

        return {
            "exit_code": result["exit_code"],
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
        }

    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution error: {e}",
            "blocked": False,
        }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "run_command",
        "description": (
            "Run a shell command on the user's machine. Commands are scoped to a safe "
            "allowlist (homebrew, git, file search, text processing, dev tools). "
            "Destructive operations (rm, sudo, kill, etc.) are blocked. "
            "Credential files (.env, tokens, keys) cannot be read. "
            "Use this for: installing packages (brew, npm, pip), searching files, "
            "reading code, running builds, git operations (except push), "
            "system info, and general development tasks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run. Must use an allowed binary.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for the command. Defaults to user home.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (max 120, default 30).",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_allowed_commands",
        "description": (
            "List all commands that are allowed to run through the scoped shell. "
            "Use this to check what tools are available before attempting a command."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

HANDLERS = {}


def handle_run_command(args):
    command = args.get("command", "")
    working_dir = args.get("working_directory")
    timeout = args.get("timeout")

    # Cap timeout
    if timeout and timeout > 120:
        timeout = 120

    result = run_command(command, working_dir, timeout)

    if result.get("blocked"):
        return f"BLOCKED: {result['stderr']}"

    parts = []
    if result["exit_code"] != 0:
        parts.append(f"Exit code: {result['exit_code']}")
    if result["stdout"]:
        parts.append(result["stdout"])
    if result["stderr"]:
        parts.append(f"stderr: {result['stderr']}")
    if result.get("truncated"):
        parts.append("(output was truncated)")

    return "\n".join(parts) if parts else "(no output)"


def handle_list_allowed(args):
    lines = ["Allowed commands:"]
    for cmd in sorted(ALLOWED_BINARIES):
        lines.append(f"  {cmd}")
    lines.append("")
    lines.append("Blocked (never allowed):")
    for cmd in sorted(BLOCKED_BINARIES):
        lines.append(f"  {cmd}")
    return "\n".join(lines)


HANDLERS["run_command"] = handle_run_command
HANDLERS["list_allowed_commands"] = handle_list_allowed


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------


def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "companion-shell", "version": "1.0.0"},
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = HANDLERS.get(tool_name)
        if not handler:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }
        try:
            result = handler(arguments)
            return {"content": [{"type": "text", "text": result}]}
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    return None


def main():
    """Main loop: read JSON-RPC from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "id" not in request:
            handle_request(request)
            continue

        result = handle_request(request)
        if result is None:
            continue

        response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

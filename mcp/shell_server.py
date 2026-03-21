#!/usr/bin/env python3
"""Shell MCP server for Atrophy agents.

Provides broad shell access with safety rails:
- Most dev tools allowed (bash, python3, node, git, brew, docker, etc.)
- Command chaining (&&, ||, ;) and pipes supported
- Path restrictions (no access to credentials, .env, tokens, keys)
- Subshell expansion ($(), backticks) blocked to prevent allowlist bypass
- Env sanitized (secrets stripped from subprocess environment)
- Timeout enforcement (30s default, 300s max)
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
    "node", "npm", "pnpm", "yarn", "bun", "npx", "uvx",
    "python3", "pip3", "uv", "pipx",
    # System info
    "uname", "sw_vers", "sysctl", "whoami", "id", "date", "cal",
    "uptime", "top", "ps", "lsof", "which", "where", "type",
    "env", "printenv",
    # Networking (read-only)
    "ping", "dig", "nslookup", "host", "curl", "wget", "httpie",
    # Process management (controlled)
    "kill", "killall", "pkill",
    # Disk / process
    "open", "pbcopy", "pbpaste",
    # Compression
    "tar", "zip", "unzip", "gzip", "gunzip",
    # Editors (non-interactive, for piping)
    "echo", "printf", "tee",
    # File operations (including delete)
    "rm", "rmdir",
    # Permissions
    "chmod",
    # Development
    "cargo", "go", "rustc", "gcc", "clang",
    "docker", "docker-compose",
    # Shell scripting (controlled - blocked paths still enforced)
    "bash", "sh", "zsh",
    "perl", "ruby",
    # macOS automation
    "osascript", "defaults", "launchctl",
    # Database (read access)
    "sqlite3",
    # Misc
    "realpath", "basename", "dirname", "mktemp", "touch", "mkdir",
    "cp", "mv", "ln",
}

# Binaries that are always blocked, even if somehow in the allowed set.
BLOCKED_BINARIES = {
    "sudo", "su", "doas",
    "shutdown", "reboot", "halt", "poweroff",
    "dd", "mkfs", "fdisk", "diskutil",
    "nmap", "masscan", "nc", "netcat",
    "chown", "chgrp",
    "systemctl",
    "security",   # keychain access
    # Shells not in allowlist are blocked to prevent sandbox escape
    "fish", "csh", "tcsh", "ksh", "dash",
    "php", "lua",
}

# Git subcommands that are blocked (destructive or remote-pushing)
BLOCKED_GIT_SUBCOMMANDS = {
    "push", "push --force", "reset --hard", "clean",
    "checkout -- .", "restore .",
}

# Dangerous argument patterns for specific binaries
# Only block patterns that could escalate privileges or escape the sandbox
DANGEROUS_ARG_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    # awk: system() can spawn arbitrary processes
    "awk": [re.compile(r"system\s*\(")],
    # sed: e flag executes pattern space as shell command
    "sed": [re.compile(r"(?:^|[^\\])/e(?:\b|$)")],
    # docker: privileged mode and host namespace access
    "docker": [re.compile(r"--privileged"), re.compile(r"--pid=host"),
               re.compile(r"--net=host"), re.compile(r"--network=host")],
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

    # Block subshell expansion (could bypass binary allowlist)
    for dangerous in ["$(", "`"]:
        if dangerous in command:
            return (
                f"Subshell expansion with '{dangerous.strip()}' is not allowed. "
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

    # Split on chaining operators and pipes to validate each segment
    # Regex splits on &&, ||, ;, | while preserving the operators
    segments = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)

    for segment in segments:
        segment = segment.strip()
        # Strip redirects from the end for parsing
        seg_clean = re.sub(r">{1,2}\s*\S+\s*$", "", segment).strip()
        if not seg_clean:
            continue

        try:
            parts = shlex.split(seg_clean)
        except ValueError as e:
            return f"Could not parse command segment: {e}"

        if not parts:
            continue

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


def _has_chaining(command: str) -> bool:
    """Check if command uses chaining operators (&&, ||, ;) or newlines."""
    # Avoid matching inside quoted strings by checking raw operators
    for op in ["&&", "||", ";"]:
        if op in command:
            return True
    return "\n" in command


def _run_shell(command: str, cwd: str, env: dict[str, str], timeout: int) -> dict:
    """Run a command via bash for chaining/complex syntax support.

    Used when the command contains &&, ||, ;, or other constructs that
    need a real shell. All commands are pre-validated by validate_command().
    """
    bash_path = shutil.which("bash") or "/bin/bash"
    try:
        proc = subprocess.run(
            [bash_path, "-c", command],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": f"Execution error: {e}"}


def run_command(command: str, working_dir: str | None = None, timeout: int | None = None) -> dict:
    """Run a validated shell command and return structured output.

    Simple commands and pipes use shell=False with explicit process pipelines.
    Commands with chaining (&&, ||, ;) are run via bash after validation.
    """
    error = validate_command(command)
    if error:
        return {"exit_code": -1, "stdout": "", "stderr": error, "blocked": True}

    cwd = working_dir or WORKING_DIR
    if not os.path.isdir(cwd):
        cwd = str(Path.home())

    t = timeout or TIMEOUT
    env = _sanitize_env()

    # Commands with chaining operators run via bash (handles &&, ||, ;, redirects)
    # Simple commands/pipes use shell=False with explicit process pipelines
    chained = _has_chaining(command)
    redirect_path = None
    is_append = False

    if chained:
        result = _run_shell(command, cwd, env, t)
    else:
        command_body, redirect_path, is_append = _handle_redirects(command)
        segments = command_body.split("|")
        result = _run_pipeline(segments, cwd, env, t)

    try:
        if result.get("blocked"):
            return result

        stdout = result["stdout"]
        stderr = result["stderr"]

        # Write to redirect target if specified (non-chained only; bash handles its own)
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
            "Run a shell command on the user's machine. Most common tools are "
            "available: bash/zsh, python3, node, git, npm/pnpm, brew, curl, "
            "docker, sqlite3, osascript, rm, kill, chmod, find -exec, and more. "
            "Command chaining (&&, ||, ;) and pipes are supported. "
            "Credential files (.env, tokens, keys) cannot be read. "
            "Subshell expansion ($(), backticks) is blocked. "
            "Use this for any development, automation, or system task."
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
    if timeout and timeout > 300:
        timeout = 300

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

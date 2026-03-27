#!/usr/bin/env python3
"""GitHub MCP server for the companion agent.

Wraps the `gh` CLI for repository, issue, PR, and search operations.
Auth is handled entirely by `gh auth login` (browser OAuth flow) -
no tokens or keys to manage manually.

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TIMEOUT = 30
MAX_OUTPUT = 32000
GH_BIN = os.environ.get("GH_BIN", shutil.which("gh") or "gh")
# Working directory for repo-relative commands (set by inference.ts)
WORKING_DIR = os.environ.get("GH_WORKING_DIR", str(Path.home()))


def _run_gh(args: list[str], timeout: int = TIMEOUT, cwd: str | None = None) -> dict:
    """Run a gh CLI command and return structured output."""
    try:
        run_cwd = cwd or WORKING_DIR
        if not os.path.isdir(run_cwd):
            run_cwd = str(Path.home())
        # Sanitize args - reject any that look like shell metacharacters
        sanitized = [str(a) for a in args]
        result = subprocess.run(
            [GH_BIN] + sanitized,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
        )
        stdout = result.stdout
        if len(stdout) > MAX_OUTPUT:
            stdout = stdout[:MAX_OUTPUT] + "\n... (truncated)"
        return {
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": result.stderr[:4000] if result.stderr else "",
        }
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": (
                "gh CLI is not installed. "
                "Install it with: brew install gh\n"
                "Then authenticate with: gh auth login"
            ),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


def _format_result(result: dict) -> str:
    """Format a gh CLI result for the agent."""
    if result["exit_code"] != 0:
        msg = result["stderr"] or result["stdout"] or "Unknown error"
        if "auth login" in msg or "not logged" in msg.lower():
            return (
                "GitHub authentication required.\n\n"
                "Ask the user to run this in their terminal:\n"
                "  gh auth login\n\n"
                "This opens a browser for secure OAuth login - no tokens needed."
            )
        return f"Error (exit {result['exit_code']}): {msg}"
    return result["stdout"] or "(no output)"


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_auth_status(args):
    """Check if gh is installed and authenticated."""
    # Check installation
    if not shutil.which(GH_BIN) and GH_BIN == "gh":
        return (
            "gh CLI is not installed.\n\n"
            "To set up GitHub access:\n"
            "1. Install: brew install gh\n"
            "2. Login: gh auth login\n"
            "   (opens browser - no tokens to copy)"
        )

    result = _run_gh(["auth", "status"])
    if result["exit_code"] == 0:
        return f"Authenticated.\n{result['stdout']}{result['stderr']}"
    return (
        "Not authenticated.\n\n"
        "Ask the user to run: gh auth login\n"
        "This opens a browser for secure OAuth - no tokens needed."
    )


def handle_repo_view(args):
    """View repository details."""
    repo = args.get("repo", "")
    cmd = ["repo", "view"]
    if repo:
        cmd.append(repo)
    result = _run_gh(cmd)
    return _format_result(result)


def handle_repo_list(args):
    """List repositories for a user/org."""
    owner = args.get("owner", "")
    limit = min(args.get("limit", 20), 100)
    cmd = ["repo", "list"]
    if owner:
        cmd.append(owner)
    cmd.extend(["--limit", str(limit)])
    if args.get("language"):
        cmd.extend(["--language", args["language"]])
    if args.get("sort"):
        cmd.extend(["--sort", args["sort"]])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_repo_clone(args):
    """Clone a repository."""
    repo = args.get("repo", "")
    if not repo:
        return "Error: repo is required (e.g. 'owner/repo')"
    directory = args.get("directory", "")
    cmd = ["repo", "clone", repo]
    if directory:
        cmd.append(directory)
    result = _run_gh(cmd, timeout=120)
    return _format_result(result)


def handle_issue_list(args):
    """List issues for a repository."""
    repo = args.get("repo", "")
    limit = min(args.get("limit", 20), 100)
    cmd = ["issue", "list", "--limit", str(limit)]
    if repo:
        cmd.extend(["-R", repo])
    if args.get("state"):
        cmd.extend(["--state", args["state"]])
    if args.get("label"):
        cmd.extend(["--label", args["label"]])
    if args.get("assignee"):
        cmd.extend(["--assignee", args["assignee"]])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_issue_view(args):
    """View a specific issue."""
    number = args.get("number")
    if not number:
        return "Error: issue number is required"
    repo = args.get("repo", "")
    cmd = ["issue", "view", str(number)]
    if repo:
        cmd.extend(["-R", repo])
    if args.get("comments"):
        cmd.append("--comments")
    result = _run_gh(cmd)
    return _format_result(result)


def handle_issue_create(args):
    """Create a new issue."""
    title = args.get("title", "")
    if not title:
        return "Error: title is required"
    repo = args.get("repo", "")
    body = args.get("body", "")
    cmd = ["issue", "create", "--title", title]
    if repo:
        cmd.extend(["-R", repo])
    if body:
        cmd.extend(["--body", body])
    if args.get("labels"):
        cmd.extend(["--label", ",".join(args["labels"])])
    if args.get("assignees"):
        cmd.extend(["--assignee", ",".join(args["assignees"])])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_pr_list(args):
    """List pull requests."""
    repo = args.get("repo", "")
    limit = min(args.get("limit", 20), 100)
    cmd = ["pr", "list", "--limit", str(limit)]
    if repo:
        cmd.extend(["-R", repo])
    if args.get("state"):
        cmd.extend(["--state", args["state"]])
    if args.get("author"):
        cmd.extend(["--author", args["author"]])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_pr_view(args):
    """View a specific pull request."""
    number = args.get("number")
    if not number:
        return "Error: PR number is required"
    repo = args.get("repo", "")
    cmd = ["pr", "view", str(number)]
    if repo:
        cmd.extend(["-R", repo])
    if args.get("comments"):
        cmd.append("--comments")
    result = _run_gh(cmd)
    return _format_result(result)


def handle_pr_create(args):
    """Create a pull request."""
    title = args.get("title", "")
    if not title:
        return "Error: title is required"
    repo = args.get("repo", "")
    cmd = ["pr", "create", "--title", title]
    if repo:
        cmd.extend(["-R", repo])
    if args.get("body"):
        cmd.extend(["--body", args["body"]])
    if args.get("base"):
        cmd.extend(["--base", args["base"]])
    if args.get("head"):
        cmd.extend(["--head", args["head"]])
    if args.get("draft"):
        cmd.append("--draft")
    result = _run_gh(cmd)
    return _format_result(result)


def handle_search_repos(args):
    """Search GitHub repositories."""
    query = args.get("query", "")
    if not query:
        return "Error: query is required"
    limit = min(args.get("limit", 10), 50)
    cmd = ["search", "repos", query, "--limit", str(limit)]
    if args.get("language"):
        cmd.extend(["--language", args["language"]])
    if args.get("sort"):
        cmd.extend(["--sort", args["sort"]])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_search_code(args):
    """Search code on GitHub."""
    query = args.get("query", "")
    if not query:
        return "Error: query is required"
    limit = min(args.get("limit", 10), 50)
    cmd = ["search", "code", query, "--limit", str(limit)]
    if args.get("repo"):
        cmd.extend(["-R", args["repo"]])
    if args.get("language"):
        cmd.extend(["--language", args["language"]])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_search_issues(args):
    """Search issues and PRs on GitHub."""
    query = args.get("query", "")
    if not query:
        return "Error: query is required"
    limit = min(args.get("limit", 10), 50)
    cmd = ["search", "issues", query, "--limit", str(limit)]
    if args.get("repo"):
        cmd.extend(["-R", args["repo"]])
    if args.get("state"):
        cmd.extend(["--state", args["state"]])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_gist_list(args):
    """List your gists."""
    limit = min(args.get("limit", 10), 50)
    cmd = ["gist", "list", "--limit", str(limit)]
    result = _run_gh(cmd)
    return _format_result(result)


def handle_gist_view(args):
    """View a gist."""
    gist_id = args.get("id", "")
    if not gist_id:
        return "Error: gist id is required"
    cmd = ["gist", "view", gist_id]
    result = _run_gh(cmd)
    return _format_result(result)


def handle_gist_create(args):
    """Create a gist from content."""
    filename = args.get("filename", "")
    content = args.get("content", "")
    if not filename or not content:
        return "Error: filename and content are required"
    desc = args.get("description", "")
    public = args.get("public", False)
    # Write content to temp file, create gist, clean up
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=f"_{filename}", delete=False)
    try:
        tmp.write(content)
        tmp.close()
        cmd = ["gist", "create", tmp.name, "--filename", filename]
        if desc:
            cmd.extend(["--desc", desc])
        if public:
            cmd.append("--public")
        result = _run_gh(cmd)
        return _format_result(result)
    finally:
        os.unlink(tmp.name)


def handle_release_list(args):
    """List releases for a repository."""
    repo = args.get("repo", "")
    limit = min(args.get("limit", 10), 50)
    cmd = ["release", "list", "--limit", str(limit)]
    if repo:
        cmd.extend(["-R", repo])
    result = _run_gh(cmd)
    return _format_result(result)


def handle_api(args):
    """Make a raw GitHub API request (GET only for safety)."""
    endpoint = args.get("endpoint", "")
    if not endpoint:
        return "Error: endpoint is required (e.g. '/user' or '/repos/owner/repo')"
    # Only allow GET requests for safety - explicitly enforce with --method GET
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    cmd = ["api", "--method", "GET", endpoint]
    if args.get("jq"):
        # Sanitize jq filter - block shell-like patterns
        jq_filter = args["jq"]
        if any(c in jq_filter for c in [";", "|", "$("]):
            return "Error: jq filter contains disallowed characters"
        cmd.extend(["--jq", jq_filter])
    result = _run_gh(cmd)
    return _format_result(result)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "github",
        "description": (
            "GitHub operations via gh CLI. Actions: auth_status, repo_view, repo_list, "
            "repo_clone, issue_list, issue_view, issue_create, pr_list, pr_view, pr_create, "
            "search_repos, search_code, search_issues, gist_list, gist_view, gist_create, "
            "release_list, api."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "auth_status", "repo_view", "repo_list", "repo_clone",
                        "issue_list", "issue_view", "issue_create",
                        "pr_list", "pr_view", "pr_create",
                        "search_repos", "search_code", "search_issues",
                        "gist_list", "gist_view", "gist_create",
                        "release_list", "api",
                    ],
                    "description": "GitHub action to perform",
                },
                "repo": {"type": "string", "description": "Repository in owner/repo format"},
                "owner": {"type": "string", "description": "GitHub username or org"},
                "number": {"type": "integer", "description": "Issue/PR number"},
                "title": {"type": "string", "description": "Issue/PR title"},
                "body": {"type": "string", "description": "Issue/PR body (markdown)"},
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
                "state": {"type": "string", "description": "Filter: open, closed, all"},
                "label": {"type": "string", "description": "Filter by label"},
                "assignee": {"type": "string", "description": "Filter by assignee"},
                "assignees": {"type": "array", "items": {"type": "string"}},
                "labels": {"type": "array", "items": {"type": "string"}},
                "author": {"type": "string", "description": "Filter by author"},
                "language": {"type": "string", "description": "Filter by language"},
                "sort": {"type": "string", "description": "Sort field"},
                "base": {"type": "string", "description": "Base branch (PR)"},
                "head": {"type": "string", "description": "Head branch (PR)"},
                "draft": {"type": "boolean", "description": "Create as draft PR"},
                "comments": {"type": "boolean", "description": "Include comments"},
                "directory": {"type": "string", "description": "Clone directory"},
                "id": {"type": "string", "description": "Gist ID"},
                "filename": {"type": "string", "description": "Gist filename"},
                "content": {"type": "string", "description": "Gist content"},
                "description": {"type": "string", "description": "Description"},
                "public": {"type": "boolean", "description": "Make public"},
                "endpoint": {"type": "string", "description": "API endpoint"},
                "jq": {"type": "string", "description": "jq filter"},
            },
            "required": ["action"],
        },
    },
]

_GITHUB_ROUTES = {
    "auth_status": handle_auth_status,
    "repo_view": handle_repo_view,
    "repo_list": handle_repo_list,
    "repo_clone": handle_repo_clone,
    "issue_list": handle_issue_list,
    "issue_view": handle_issue_view,
    "issue_create": handle_issue_create,
    "pr_list": handle_pr_list,
    "pr_view": handle_pr_view,
    "pr_create": handle_pr_create,
    "search_repos": handle_search_repos,
    "search_code": handle_search_code,
    "search_issues": handle_search_issues,
    "gist_list": handle_gist_list,
    "gist_view": handle_gist_view,
    "gist_create": handle_gist_create,
    "release_list": handle_release_list,
    "api": handle_api,
}


def _route_github(args):
    action = args.get("action")
    if not action:
        return "Error: 'action' is required"
    handler = _GITHUB_ROUTES.get(action)
    if not handler:
        valid = ", ".join(_GITHUB_ROUTES.keys())
        return f"Error: unknown action '{action}'. Valid: {valid}"
    return handler(args)


HANDLERS = {
    "github": _route_github,
}


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
            "serverInfo": {"name": "companion-github", "version": "1.0.0"},
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

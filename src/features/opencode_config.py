"""
Generates per-run opencode.json for each worktree.
OpenCode reads this file to discover MCP servers and provider config.
"""
import json
import os
from typing import Any

from src.core.models import AgentConfig

# Tools that map to MCP servers (need a running subprocess)
_MCP_TOOLS = {"serena", "semble"}

# Tools that are built into OpenCode natively (bash, read, write, glob)
_BUILTIN_TOOLS = {
    "read", "read_all", "write", "patch", "glob", "shell",
    "grep", "rg", "git_grep", "ugrep", "semgrep"
}

def build_opencode_json(config: AgentConfig, worktree_path: str) -> dict[str, Any]:
    """
    Returns a dict representing opencode.json for this config/worktree.
    """
    cfg: dict[str, Any] = {"$schema": "https://opencode.ai/config.json"}

    # Inject provider API keys so opencode doesn't need them in the shell env
    openai_key = os.getenv("OPENAI_API_KEY")
    google_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    providers: dict[str, Any] = {}
    if openai_key:
        providers["openai"] = {"apiKey": openai_key}
    if google_key:
        providers["google"] = {"options": {"apiKey": google_key}}
    if providers:
        cfg["provider"] = providers

    # MCP server entries for semantic tools
    mcp: dict[str, Any] = {}
    if "serena" in config.tools or "semble" in config.tools:
        mcp["serena"] = {
            "type": "local",
            "command": ["serena", "start-mcp-server", "--project", worktree_path],
        }

    if mcp:
        cfg["mcp"] = mcp

    return cfg


def write_opencode_json(config: AgentConfig, worktree_path: str) -> str:
    """
    Writes opencode.json into worktree_path. Returns the path written.
    """
    cfg = build_opencode_json(config, worktree_path)
    dest = os.path.join(worktree_path, "opencode.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return dest


def build_tool_restriction_prefix(config: AgentConfig) -> str:
    """
    Returns a prompt prefix that soft-restricts OpenCode to the config's tool set.
    This is a best-effort ablation measure: OpenCode always has built-in bash/read/write,
    but we instruct it to prefer/avoid specific retrieval strategies.
    """
    tool_names = set(config.tools) - {"test", "patch", "write"}  # exclude always-on tools
    if not tool_names:
        return ""

    lines = [
        "[BENCHMARK TOOL CONFIG]",
        f"Configuration: {config.name} (archetype: {config.archetype})",
        f"Preferred retrieval tools: {', '.join(sorted(tool_names))}",
        "Use ONLY the listed retrieval strategies. Avoid alternatives not in this list.",
        "[END CONFIG]\n",
    ]
    return "\n".join(lines)

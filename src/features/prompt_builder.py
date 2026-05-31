from src.core.models import AgentConfig


def build_tool_restriction_prefix(config: AgentConfig) -> str:
    """
    Returns a prompt prefix that restricts the agent to the config's tool set.
    """
    if config.tool_restriction_prefix:
        return config.tool_restriction_prefix + "\n"

    retrieval_tools = sorted(set(config.tools) - {"test", "patch", "write"})
    write_tools = [t for t in config.tools if t in ("write", "patch")]

    if not retrieval_tools and not write_tools:
        return ""

    lines = [
        "[BENCHMARK TOOL CONFIG]",
        f"Configuration: {config.name} (archetype: {config.archetype})",        
    ]
    if retrieval_tools:
        lines.append(f"Retrieval tools available: {', '.join(retrieval_tools)}")
    if write_tools:
        lines.append(f"Write tools (MANDATORY - use to save changes): {', '.join(write_tools)}")

    lines.append("Use ONLY the listed retrieval strategies. Avoid alternatives not in this list.")

    # Heavy-read archetypes (claude, gemini) tend to over-read without writing.
    # Inject an explicit write-gate to prevent read-loops that exhaust budget.
    if config.archetype in ("claude", "gemini", "codex"):
        lines.append(
            "EFFICIENCY RULE: Read at most 6 files before making your first code change. "
            "Once you locate the target function, edit it immediately — do not keep reading "
            "other files first. Every model call costs money; act on what you know."
        )

    lines.append("[END CONFIG]\n")
    return "\n".join(lines)

from src.core.models import AgentConfig


def build_tool_restriction_prefix(config: AgentConfig) -> str:
    """
    Returns a prompt prefix that restricts the agent to the config's tool set.
    """
    tool_names = set(config.tools) - {"test", "patch", "write"}
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

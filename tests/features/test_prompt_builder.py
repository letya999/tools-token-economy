from src.core.models import AgentConfig
from src.features.prompt_builder import build_tool_restriction_prefix


def test_build_tool_restriction_prefix_empty_for_no_retrieval_tools():
    config = AgentConfig(id="t5", name="test", archetype="minimal", tools=["test", "patch", "write"])
    prefix = build_tool_restriction_prefix(config)
    assert prefix == ""

def test_build_tool_restriction_prefix_includes_tools_and_name():
    config = AgentConfig(id="t6", name="MyConfig", archetype="custom", tools=["grep", "serena", "test"])
    prefix = build_tool_restriction_prefix(config)

    assert "[BENCHMARK TOOL CONFIG]" in prefix
    assert "Configuration: MyConfig" in prefix
    assert "Preferred retrieval tools: grep, serena" in prefix
    assert "test" not in prefix.split("Preferred retrieval tools:")[1]

def test_build_tool_restriction_prefix_excludes_always_on():
    config = AgentConfig(id="t7", name="AblationRun", archetype="full", tools=["test", "patch", "write", "grep"])
    prefix = build_tool_restriction_prefix(config)

    # Only grep should be in the preferred list
    assert "grep" in prefix
    assert "test" not in prefix
    assert "patch" not in prefix
    # "write" is in the text of the tool set removal, but check if it's in the final "Preferred retrieval tools" line
    tools_line = [l for l in prefix.split("\n") if l.startswith("Preferred retrieval tools:")][0]
    assert "grep" in tools_line
    assert "test" not in tools_line
    assert "patch" not in tools_line
    assert "write" not in tools_line

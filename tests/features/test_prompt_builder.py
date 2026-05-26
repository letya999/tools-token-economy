from src.core.models import AgentConfig
from src.features.prompt_builder import build_tool_restriction_prefix


def test_build_tool_restriction_prefix_empty_for_no_retrieval_tools():
    config = AgentConfig(id="t5", name="test", archetype="minimal", tools=["test", "patch", "write"])
    prefix = build_tool_restriction_prefix(config)
    # Write tools section should still appear even without retrieval tools      
    assert "[BENCHMARK TOOL CONFIG]" in prefix
    assert "Write tools (MANDATORY" in prefix
    assert "patch" in prefix
    assert "write" in prefix

def test_build_tool_restriction_prefix_includes_tools_and_name():
    config = AgentConfig(id="t6", name="MyConfig", archetype="custom", tools=["grep", "serena", "test"])
    prefix = build_tool_restriction_prefix(config)
    assert "[BENCHMARK TOOL CONFIG]" in prefix
    assert "Configuration: MyConfig" in prefix
    assert "Retrieval tools available: grep, serena" in prefix
    assert "test" not in prefix.split("Retrieval tools available:")[1].split("\n")[0]

def test_build_tool_restriction_prefix_excludes_always_on():
    config = AgentConfig(id="t7", name="AblationRun", archetype="full", tools=["test", "patch", "write", "grep"])
    prefix = build_tool_restriction_prefix(config)
    # grep should appear
    assert "grep" in prefix
    # test should not appear anywhere
    assert "test" not in prefix
    # patch and write should appear in write tools section, NOT in retrieval tools line
    retrieval_line = [l for l in prefix.split("\n") if l.startswith("Retrieval tools available:")][0]
    assert "grep" in retrieval_line
    assert "test" not in retrieval_line
    assert "patch" not in retrieval_line
    assert "write" not in retrieval_line
    # but write tools section must exist
    assert "Write tools (MANDATORY" in prefix

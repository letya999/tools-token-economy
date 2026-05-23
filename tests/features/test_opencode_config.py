import json
import os

from src.core.models import AgentConfig
from src.features.opencode_config import build_opencode_json, build_tool_restriction_prefix, write_opencode_json


def test_build_opencode_json_minimal_structure_present():
    config = AgentConfig(id="t1", name="test", archetype="minimal", tools=["read", "write"])
    cfg = build_opencode_json(config, "/tmp/worktree")
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    assert cfg["provider"]["google"]["options"]["apiKey"] == "{env:GOOGLE_API_KEY}"
    assert "mcp" not in cfg

def test_build_opencode_json_includes_serena_mcp_entry():
    config = AgentConfig(id="t2", name="test", archetype="full", tools=["serena", "read"])
    cfg = build_opencode_json(config, "/tmp/worktree")
    assert "mcp" in cfg
    assert "serena" in cfg["mcp"]
    assert cfg["mcp"]["serena"]["type"] == "local"
    assert cfg["mcp"]["serena"]["command"] == ["serena", "start-mcp-server", "--project", "/tmp/worktree"]

def test_build_opencode_json_includes_serena_for_semble():
    config = AgentConfig(id="t3", name="test", archetype="full", tools=["semble", "read"])
    cfg = build_opencode_json(config, "/tmp/worktree")
    assert "mcp" in cfg
    assert "serena" in cfg["mcp"]

def test_write_opencode_json(tmp_path):
    worktree = str(tmp_path)
    config = AgentConfig(id="t4", name="test", archetype="full", tools=["serena"])
    dest = write_opencode_json(config, worktree)

    assert dest == os.path.join(worktree, "opencode.json")
    assert os.path.exists(dest)

    with open(dest) as f:
        data = json.load(f)
    assert "mcp" in data
    assert "serena" in data["mcp"]

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

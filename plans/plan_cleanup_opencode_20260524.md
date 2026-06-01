# Plan: Remove OpenCode, clean up project

## Goal
Remove all OpenCode-specific code and temporary debug scripts. Preserve the
`build_tool_restriction_prefix` utility (still used by benchmark.py) by moving
it to a properly named module.

## Steps

### 1. Create `src/features/prompt_builder.py`
New file containing only `build_tool_restriction_prefix` (extracted from
`opencode_config.py`). No other content.

Content:
```python
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
```

### 2. Update `src/orchestrator/benchmark.py`
Change import line:
- FROM: `from src.features.opencode_config import build_tool_restriction_prefix`
- TO:   `from src.features.prompt_builder import build_tool_restriction_prefix`

### 3. Delete via `git rm`
- `src/features/opencode_config.py`
- `tests/features/test_opencode_runner.py`
- `tests/features/test_opencode_config.py`

### 4. Create `tests/features/test_prompt_builder.py`
Keep only the three `test_build_tool_restriction_prefix_*` tests from the
deleted `test_opencode_config.py`. Update the import to:
`from src.features.prompt_builder import build_tool_restriction_prefix`

Tests to keep (copy them exactly, updated import only):
- `test_build_tool_restriction_prefix_empty_for_no_retrieval_tools`
- `test_build_tool_restriction_prefix_includes_tools_and_name`
- `test_build_tool_restriction_prefix_excludes_always_on`

### 5. Delete untracked junk files (plain `del` / `Remove-Item`)
- `_debug2.py`
- `_test_wslenv.py`
- `ripgrep_14.1.1-1_amd64.deb`
- `MISSING_FEATURES.md`
- `plans/plan_opencode_fixes_20260523.md`
- `plans/plan_opencode_integration_20260523.md`
- `plans/plan_replace_opencode_with_agno_20260524.md`
- `plans/plan_fix_subprocess_hang_20260524.md`

### 6. Stage and commit
```
git add src/features/prompt_builder.py
git add tests/features/test_prompt_builder.py
git add src/orchestrator/benchmark.py
git rm src/features/opencode_config.py
git rm tests/features/test_opencode_runner.py
git rm tests/features/test_opencode_config.py
git add src/features/agent_integration/agno_runner.py
git add pyproject.toml uv.lock main.py scripts/setup_wsl.sh src/core/tools.py tests/conftest.py
git commit -m "refactor: replace OpenCode runner with Agno, remove OpenCode artifacts"
```

## What NOT to touch
- `src/features/agent_integration/agno_runner.py` — new runner, keep as-is
- `src/orchestrator/benchmark.py` — only the import line changes
- All tool registry files
- `src/features/google_oauth_service.py` — untracked, leave alone (target benchmark task)
- `tests/unit/` — new tests, leave alone
- `plans/plan_fix_audit_20260523.md` — keep (useful reference)
- `plans/plan_tool_restriction_and_install_20260524.md` — keep

# Plan: Fix test_prompt_builder.py after prompt_builder refactor

## Context

`src/features/prompt_builder.py` was updated to show write tools (patch, write) in a separate
mandatory section. Three tests in `tests/features/test_prompt_builder.py` now fail because
they expected the old behavior (write/patch excluded from output entirely).

## Failing tests and required fixes

### test_build_tool_restriction_prefix_empty_for_no_retrieval_tools (line 5)

Old expectation: prefix is `""` when config only has `["test", "patch", "write"]`.
New behavior: prefix shows "Write tools (MANDATORY..." section even without retrieval tools.

Fix: change assertion from `assert prefix == ""` to check that write tools ARE present:

```python
def test_build_tool_restriction_prefix_empty_for_no_retrieval_tools():
    config = AgentConfig(id="t5", name="test", archetype="minimal", tools=["test", "patch", "write"])
    prefix = build_tool_restriction_prefix(config)
    # Write tools section should still appear even without retrieval tools
    assert "[BENCHMARK TOOL CONFIG]" in prefix
    assert "Write tools (MANDATORY" in prefix
    assert "patch" in prefix
    assert "write" in prefix
```

### test_build_tool_restriction_prefix_includes_tools_and_name (line 10)

Old expectation: line `"Preferred retrieval tools: grep, serena"`.
New behavior: line is `"Retrieval tools available: grep, serena"` (wording changed).

Fix: update the string assertion:

```python
def test_build_tool_restriction_prefix_includes_tools_and_name():
    config = AgentConfig(id="t6", name="MyConfig", archetype="custom", tools=["grep", "serena", "test"])
    prefix = build_tool_restriction_prefix(config)
    assert "[BENCHMARK TOOL CONFIG]" in prefix
    assert "Configuration: MyConfig" in prefix
    assert "Retrieval tools available: grep, serena" in prefix
    assert "test" not in prefix.split("Retrieval tools available:")[1].split("\n")[0]
```

### test_build_tool_restriction_prefix_excludes_always_on (line 19)

Old expectation: `"patch" not in prefix` entirely.
New behavior: `"patch"` appears in "Write tools (MANDATORY...)" section — this is intentional.

Fix: the assertions should only verify that patch/write are NOT in the retrieval tools line,
but ARE in the write tools section:

```python
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
```

## File to modify

`tests/features/test_prompt_builder.py` — replace the entire file content with the three
updated test functions above (keep the same imports at the top).

## Verification

After the fix, run: `uv run pytest tests/features/test_prompt_builder.py -v`
Expected: 3 passed.

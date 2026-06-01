# Plan: Add str_replace `edit` Tool + Safety Guard on `write`

**Date**: 2026-05-29

**Problem**: Agents destroy existing files when using `write` after reading only a partial view
(5k chars out of 60k). The agent writes back only what it read + new code, deleting the rest.

**Research basis**: All production coding tools (aider, Claude Code, SWE-agent, OpenHands,
Agno workspace) use str_replace pattern for modifying existing files. Agno itself ships
`edit_file` (replace substring) in its workspace toolkit. The standard is:
- `write` → only for NEW files
- `edit(old_string, new_string)` → for modifying existing files
No prompt restrictions needed — the tools themselves signal correct behavior via error messages.

---

## Change 1 — `src/features/tool_registry/basic_tools.py`

### 1a. Add `StrReplaceEditTool` class (new class, add after `FileWriteTool`)

Add the following class after the `FileWriteTool` class:

```python
class StrReplaceEditTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__(
            "edit",
            "Replaces an exact string in an existing file. "
            "Use to modify specific sections without touching the rest of the file. "
            "`old_string` must be a unique substring of the current file content. "
            "`new_string` replaces it exactly. Returns error if not found or not unique."
        )
        self.worktree_path = worktree_path

    def execute(self, file_path: str, old_string: str, new_string: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}. Use `write` to create new files.")

        try:
            with open(full_path, encoding="utf-8") as f:
                content = f.read()

            count = content.count(old_string)
            if count == 0:
                # Provide helpful context: show first 200 chars of file
                preview = content[:200].replace('\n', '↵')
                return self.format_result(
                    f"Error: `old_string` not found in {file_path}.\n"
                    f"File preview (first 200 chars): {preview}\n"
                    "Tip: Read the relevant section of the file first to get the exact text."
                )
            if count > 1:
                return self.format_result(
                    f"Error: `old_string` matches {count} locations in {file_path}. "
                    "Make `old_string` more specific by including more surrounding context."
                )

            new_content = content.replace(old_string, new_string, 1)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            lines_changed = abs(new_string.count('\n') - old_string.count('\n'))
            return self.format_result(
                f"Successfully edited {file_path} (+/-{lines_changed} lines net change)."
            )
        except Exception as e:
            return self.format_result(f"Error editing file: {e}")
```

### 1b. Add safety guard to `FileWriteTool.execute()`

Find the `FileWriteTool.execute()` method. It currently looks like:
```python
    def execute(self, file_path: str, content: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return self.format_result(f"Successfully wrote to {file_path}")
        except Exception as e:
            return self.format_result(f"Error writing file: {e}")
```

Replace with (add the guard block before the write):
```python
    def execute(self, file_path: str, content: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")

        try:
            # Safety guard: reject writes that would destroy significant existing content.
            if os.path.isfile(full_path):
                with open(full_path, encoding="utf-8") as f:
                    orig_lines = f.readlines()
                new_lines = content.splitlines()
                if len(orig_lines) > 80 and len(new_lines) < 0.7 * len(orig_lines):
                    return self.format_result(
                        f"Error: Write rejected. New content has {len(new_lines)} lines but "
                        f"the current file has {len(orig_lines)} lines. "
                        f"Writing would delete {len(orig_lines) - len(new_lines)} existing lines. "
                        f"Use `edit` to modify specific sections, or `patch` to apply a diff. "
                        f"If you intend to replace the full file, read it completely first."
                    )

            os.makedirs(os.path.dirname(full_path) if os.path.dirname(full_path) else '.', exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return self.format_result(f"Successfully wrote to {file_path}")
        except Exception as e:
            return self.format_result(f"Error writing file: {e}")
```

---

## Change 2 — `src/features/tool_registry/registry.py`

Register the new `edit` tool.

Find the registry dict where tools are registered (look for lines like `"read": lambda wt: FileReadTool(wt)`).

Add one entry for the new tool:
```python
"edit": lambda wt: StrReplaceEditTool(wt),
```

Also add the import of `StrReplaceEditTool` from `basic_tools` at the top of the file (wherever FileReadTool, FileWriteTool etc. are imported from).

---

## Change 3 — `configs/tools.yaml`

Add `"edit"` to all configs that currently have `"write"`. The `edit` tool should be available
alongside `write` in every config that can modify files. This gives the agent both options and
lets it choose the appropriate one.

Find every config entry that contains `"write"` in its tools list and add `"edit"` next to it.

For example, if a config has:
```yaml
tools: ["read", "write", "patch", "glob", "shell"]
```
Change to:
```yaml
tools: ["read", "write", "edit", "patch", "glob", "shell"]
```

Apply this to ALL configs that include `"write"`.

---

## Files to modify

1. `src/features/tool_registry/basic_tools.py` — add `StrReplaceEditTool` class + safety guard in `FileWriteTool`
2. `src/features/tool_registry/registry.py` — register `"edit"` tool
3. `configs/tools.yaml` — add `"edit"` to all configs that have `"write"`

## Verification

After changes:
1. `grep -n "StrReplaceEditTool\|\"edit\"" src/features/tool_registry/basic_tools.py` — should show new class
2. `grep "edit" src/features/tool_registry/registry.py` — should show registration
3. `grep -c '"edit"' configs/tools.yaml` — should show multiple configs with edit
4. Run: `wsl bash -c "bash scripts/run_wsl.sh --dry-run --config-ids 01_cursor_like"` — should pass

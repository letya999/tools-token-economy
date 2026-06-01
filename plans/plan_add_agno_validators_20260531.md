# Plan: Add Agno Validators for edit, insert, append tools

## Problem
Doctor check fails for 3 tools with "Failed to instantiate tool for Agno check":
- `edit` (StrReplaceEditTool)
- `insert` (InsertAfterLineTool)  
- `append` (AppendToFileTool)

Root cause: `BaseToolValidator._get_tool_instance()` returns None because these tools have no
specific validator registered in `ToolRegistry._validators`. The `validate_agno_registration()`
method cannot instantiate the tool to wrap it for Agno.

## Files to Create

### 1. `src/features/tool_registry/tools/edit/__init__.py`
Empty file.

### 2. `src/features/tool_registry/tools/edit/validator.py`
```python
from src.features.tool_registry.base import BaseToolValidator
from src.features.tool_registry.basic_tools import StrReplaceEditTool


class EditValidator(BaseToolValidator):
    tool_name = "edit"
    def _get_tool_instance(self, tmp_dir): return StrReplaceEditTool(tmp_dir)
```

### 3. `src/features/tool_registry/tools/insert/__init__.py`
Empty file.

### 4. `src/features/tool_registry/tools/insert/validator.py`
```python
from src.features.tool_registry.base import BaseToolValidator
from src.features.tool_registry.basic_tools import InsertAfterLineTool


class InsertValidator(BaseToolValidator):
    tool_name = "insert"
    def _get_tool_instance(self, tmp_dir): return InsertAfterLineTool(tmp_dir)
```

### 5. `src/features/tool_registry/tools/append/__init__.py`
Empty file.

### 6. `src/features/tool_registry/tools/append/validator.py`
```python
from src.features.tool_registry.base import BaseToolValidator
from src.features.tool_registry.basic_tools import AppendToFileTool


class AppendValidator(BaseToolValidator):
    tool_name = "append"
    def _get_tool_instance(self, tmp_dir): return AppendToFileTool(tmp_dir)
```

## File to Modify

### 7. `src/features/tool_registry/registry.py`

Add imports near the top (after the existing `from src.features.tool_registry.tools.insert_after.validator import InsertAfterValidator` line):
```python
from src.features.tool_registry.tools.edit.validator import EditValidator
from src.features.tool_registry.tools.insert.validator import InsertValidator
from src.features.tool_registry.tools.append.validator import AppendValidator
```

Add to `self._validators` dict in `ToolRegistry.__init__` (after `"insert_after": InsertAfterValidator,`):
```python
"edit": EditValidator,
"insert": InsertValidator,
"append": AppendValidator,
```

## Validation

After implementation, run in WSL:
```bash
bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --doctor
```

Expected: `edit`, `insert`, `append` all show `[PASS]` for Agno Integration. Overall: 22/22 PASS.

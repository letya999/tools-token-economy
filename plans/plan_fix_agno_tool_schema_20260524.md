# Plan: Fix AgnoRunner - Tool Schema Bug + Error Traceback

## Problem 1 (CRITICAL): Tool JSON schema is wrong

`_build_agno_tools()` in `src/features/agent_integration/agno_runner.py` wraps each
tool as `def wrapper(**kwargs)`. Agno (via pydantic) calls `inspect.signature(wrapper)`
to build the OpenAI function calling schema — and sees only `**kwargs`, so it generates:
```json
{"properties": {"kwargs": {}}, "required": ["kwargs"]}
```
OpenAI then calls the tool with `{"kwargs": {"file_path": "...", ...}}` instead of
`{"file_path": "..."}`. The wrapper receives `kwargs={"kwargs": {...}}`, the filter
keeps nothing (no param named `kwargs` in the real signature), and `execute()` gets
wrong/missing args → every tool call silently fails or errors.

## Problem 2 (DIAGNOSTIC): ENOENT swallowed in error handler

The current handler only logs `str(e)`, which loses the file path and traceback for
the `[Errno 2] No such file or directory` affecting configs 02-20.

---

## File to modify: `src/features/agent_integration/agno_runner.py`

### Change 1 — Add `wrapper.__signature__` in `_build_agno_tools()`

**Location**: lines 52-72, the `_build_agno_tools` method.

Replace:
```python
def _build_agno_tools(self) -> list:
    agno_tools_list = []
    for t in self.tools:
        def make_wrapper(tool_obj: Tool):
            sig = inspect.signature(tool_obj.execute)
            params = list(sig.parameters.keys())

            def wrapper(**kwargs):
                try:
                    filtered = {k: v for k, v in kwargs.items() if k in params}
                    result = tool_obj.execute(**filtered)
                    return result.output
                except Exception as e:
                    return f"Error executing tool {tool_obj.name}: {str(e)}"

            wrapper.__name__ = tool_obj.name
            wrapper.__doc__ = tool_obj.description
            return agno_tool(wrapper)

        agno_tools_list.append(make_wrapper(t))
    return agno_tools_list
```

With:
```python
def _build_agno_tools(self) -> list:
    agno_tools_list = []
    for t in self.tools:
        def make_wrapper(tool_obj: Tool):
            sig = inspect.signature(tool_obj.execute)
            params = list(sig.parameters.keys())

            def wrapper(**kwargs):
                try:
                    filtered = {k: v for k, v in kwargs.items() if k in params}
                    result = tool_obj.execute(**filtered)
                    return result.output
                except Exception as e:
                    return f"Error executing tool {tool_obj.name}: {str(e)}"

            wrapper.__name__ = tool_obj.name
            wrapper.__doc__ = tool_obj.description
            # Expose real parameter signature so Agno builds correct OpenAI schema.
            # Without this, **kwargs causes schema {properties: {kwargs: {}}} and
            # the model calls tools with the wrong argument structure.
            wrapper.__signature__ = sig.replace(return_annotation=str)
            return agno_tool(wrapper)

        agno_tools_list.append(make_wrapper(t))
    return agno_tools_list
```

### Change 2 — Log full traceback in the error handler

**Location**: lines 145-147, the `except Exception as e:` block at the end of `run()`.

Replace:
```python
        except Exception as e:
            _log.error("Agno agent execution failed: %s", str(e))
            success = False
```

With:
```python
        except Exception as e:
            import traceback as _tb
            _log.error("Agno agent execution failed: %s\n%s", str(e), _tb.format_exc())
            success = False
```

---

## What NOT to change
- All other methods in `agno_runner.py`
- Any other files

---

## After applying

Run a quick schema-validation test in WSL:
```bash
cd /mnt/c/Users/User/a_projects/tools_token_economy
UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run python - <<'EOF'
import inspect
from src.features.tool_registry.basic_tools import FileReadTool
from src.features.agent_integration.agno_runner import AgnoRunner
from src.core.models import AgentConfig

tool = FileReadTool("/tmp")
sig = inspect.signature(tool.execute)
print("execute sig:", sig)

# Simulate what _build_agno_tools does after fix
def wrapper(**kwargs): pass
wrapper.__signature__ = sig.replace(return_annotation=str)
print("wrapper sig:", inspect.signature(wrapper))
print("params:", list(inspect.signature(wrapper).parameters.keys()))
EOF
```

Expected output:
```
execute sig: (file_path: str, start_line: int = 1, end_line: int = -1) -> ToolResult
wrapper sig: (file_path: str, start_line: int = 1, end_line: int = -1) -> str
params: ['file_path', 'start_line', 'end_line']
```

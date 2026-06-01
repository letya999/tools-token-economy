# Plan: Comprehensive V2 Post-Implementation Fixes
Date: 2026-05-28

## Summary
Fix 8 issues found during deep review of ROADMAP_V2 implementation.
Do NOT change anything not listed here.

---

## Fix 1: configs/tasks/medium.yaml — wrong required_files

File: `configs/tasks/medium.yaml`

The task is "Jira Sync Execution Timeout". The actual codebase has:
- `app/services/dagster_client.py` — needs `tags={"timeout":"3600"}` added to trigger_job()
- `app/api/integrations.py` — call site for trigger_job
- `tests/unit/test_dagster_client.py` — tests to update/add

Replace:
```yaml
target_file: "tests/unit/test_api_google_oauth.py"
required_files:
  - "tests/unit/test_api_google_oauth.py"
  - "src/api/google_oauth.py"
```
With:
```yaml
target_file: "tests/unit/test_dagster_client.py"
required_files:
  - "app/services/dagster_client.py"
  - "app/api/integrations.py"
  - "tests/unit/test_dagster_client.py"
```

---

## Fix 2: configs/provider.yaml — model name missing prefix

File: `configs/provider.yaml`

Replace:
```yaml
model: gpt-4.1-mini
```
With:
```yaml
model: openai/gpt-4.1-mini
```

---

## Fix 3: tests/core/test_config_loader.py — missing tests for new loaders

File: `tests/core/test_config_loader.py`

Add tests for the 4 new loader functions. Use `tmp_path` fixture to write temp YAML files.

Add to the file (after existing test):

```python
import tempfile
import os
import yaml
import pytest

from src.core.config_loader import (
    load_provider_config,
    load_tools_config,
    load_task_config,
    load_codebase_config,
)
from src.core.models import ProviderConfig


def test_load_provider_config(tmp_path):
    data = {"provider": "openai", "model": "openai/gpt-4.1-mini", "max_steps": 30, "temperature": 0.1}
    f = tmp_path / "provider.yaml"
    f.write_text(yaml.dump(data))
    cfg = load_provider_config(str(f))
    assert isinstance(cfg, ProviderConfig)
    assert cfg.model == "openai/gpt-4.1-mini"
    assert cfg.max_steps == 30
    assert cfg.temperature == 0.1


def test_load_tools_config_inherits_provider_model(tmp_path):
    provider_data = {"provider": "openai", "model": "openai/gpt-4.1-mini", "max_steps": 25}
    tools_data = {
        "configs": [
            {"id": "01_test", "name": "Test", "archetype": "cursor", "tools": ["read", "write"]},
        ]
    }
    pf = tmp_path / "provider.yaml"
    pf.write_text(yaml.dump(provider_data))
    tf = tmp_path / "tools.yaml"
    tf.write_text(yaml.dump(tools_data))

    provider = load_provider_config(str(pf))
    configs = load_tools_config(str(tf), provider)
    assert len(configs) == 1
    assert configs[0].model == "openai/gpt-4.1-mini"
    assert configs[0].max_steps == 25


def test_load_tools_config_explicit_override_wins(tmp_path):
    """If a config explicitly sets model/max_steps, it overrides the provider default."""
    provider_data = {"model": "openai/gpt-4.1-mini", "max_steps": 50}
    tools_data = {
        "configs": [
            {"id": "01_test", "name": "Test", "archetype": "cursor",
             "tools": ["read"], "model": "openai/gpt-4.1-nano", "max_steps": 10},
        ]
    }
    pf = tmp_path / "provider.yaml"
    pf.write_text(yaml.dump(provider_data))
    tf = tmp_path / "tools.yaml"
    tf.write_text(yaml.dump(tools_data))

    provider = load_provider_config(str(pf))
    configs = load_tools_config(str(tf), provider)
    assert configs[0].model == "openai/gpt-4.1-nano"
    assert configs[0].max_steps == 10


def test_load_task_config(tmp_path):
    data = {
        "difficulty": "medium",
        "name": "Test Task",
        "description": "  Do something.  ",
        "test_cmd": "uv run pytest",
        "timeout_sec": 600,
        "required_files": ["app/services/dagster_client.py"],
    }
    f = tmp_path / "task.yaml"
    f.write_text(yaml.dump(data))
    cfg = load_task_config(str(f))
    assert cfg.description == "Do something."  # stripped
    assert cfg.timeout_sec == 600
    assert "app/services/dagster_client.py" in cfg.required_files


def test_load_codebase_config(tmp_path):
    data = {
        "name": "myrepo",
        "github_url": "https://github.com/example/repo",
        "local_path": "/tmp/repo",
        "install_cmd": "uv sync",
    }
    f = tmp_path / "codebase.yaml"
    f.write_text(yaml.dump(data))
    cfg = load_codebase_config(str(f))
    assert cfg.name == "myrepo"
    assert cfg.local_path == "/tmp/repo"
```

---

## Fix 4: tests/core/test_models.py — missing tests for new models and RunMetrics fields

File: `tests/core/test_models.py`

Add the following tests (append to existing file):

```python
from src.core.models import (
    ProviderConfig, TaskConfig, CodebaseConfig, McpServerConfig, RunMetrics
)
from dataclasses import field


def test_provider_config_defaults():
    cfg = ProviderConfig()
    assert cfg.provider == "openai"
    assert cfg.model == "openai/gpt-4.1-mini"
    assert cfg.max_steps == 50
    assert cfg.temperature == 0.0


def test_task_config_defaults():
    cfg = TaskConfig()
    assert cfg.difficulty == "medium"
    assert cfg.required_files == []
    assert cfg.target_file is None


def test_codebase_config_defaults():
    cfg = CodebaseConfig()
    assert cfg.local_path == ""
    assert cfg.branch == "main"


def test_mcp_server_config_warmup_fields():
    cfg = McpServerConfig(
        tool_name="serena",
        command="serena",
        args_template=["start-mcp-server", "--project", "{path}"],
        warmup_call="get_symbols_overview",
        warmup_args={"project": "/tmp"},
    )
    assert cfg.warmup_call == "get_symbols_overview"
    assert cfg.warmup_args == {"project": "/tmp"}
    # Default is None/empty
    cfg2 = McpServerConfig(tool_name="t", command="t", args_template=[])
    assert cfg2.warmup_call is None
    assert cfg2.warmup_args == {}


def test_run_metrics_new_fields_defaults():
    m = RunMetrics(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=30,
        duration_sec=5.0, model_calls=2, tool_calls=5,
    )
    assert m.agent_cycles == 0
    assert m.time_to_target == 0
    assert m.context_waste_ratio == 0.0
    assert m.warmup_sec == 0.0


def test_run_metrics_avg_tokens_per_tool_computed():
    # tool_calls=5, tool_tokens=100 → avg=20.0
    m = RunMetrics(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=100,
        duration_sec=5.0, model_calls=2, tool_calls=5,
    )
    assert m.avg_tokens_per_tool == 20.0


def test_run_metrics_avg_tokens_per_tool_zero_division():
    # tool_calls=0 → avg=0.0 (no division by zero)
    m = RunMetrics(
        success=False, eval_score=0.0,
        input_tokens=0, output_tokens=0, tool_tokens=0,
        duration_sec=1.0, model_calls=0, tool_calls=0,
    )
    assert m.avg_tokens_per_tool == 0.0


def test_run_metrics_all_new_fields_serialized():
    """New fields must appear in model_dump() so metrics.json captures them."""
    m = RunMetrics(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=80,
        duration_sec=5.0, model_calls=2, tool_calls=4,
        agent_cycles=3, time_to_target=2, context_waste_ratio=0.4, warmup_sec=1.5,
    )
    d = m.model_dump()
    assert d["agent_cycles"] == 3
    assert d["time_to_target"] == 2
    assert d["context_waste_ratio"] == 0.4
    assert d["warmup_sec"] == 1.5
    assert "avg_tokens_per_tool" in d   # computed field must be serialized
    assert d["avg_tokens_per_tool"] == 20.0
```

---

## Fix 5: src/features/preflight.py — add fastembed model check + required_files check

File: `src/features/preflight.py`

### 5a: Add `required_files` param to `PreflightChecker.__init__`

In `__init__`, add parameter `required_files: list[str] | None = None` and store it:
```python
self.required_files = required_files or []
```

### 5b: Add `_check_fastembed_model` method

Add this method to `PreflightChecker` class (after `_check_semble_model`):

```python
def _check_fastembed_model(self) -> list[PreflightResult]:
    """Verify BAAI/bge-small-en-v1.5 is cached; download it if missing (needed for simple_rag)."""
    needs_simple_rag = any("simple_rag" in c.tools for c in self.configs)
    if not needs_simple_rag:
        return []

    model_id = "BAAI/bge-small-en-v1.5"
    hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
    snap_base = os.path.join(hf_cache, "models--BAAI--bge-small-en-v1.5", "snapshots")

    if os.path.isdir(snap_base):
        for snap in os.listdir(snap_base):
            snap_dir = os.path.join(snap_base, snap)
            if os.path.isdir(snap_dir):
                real_files = [f for f in os.listdir(snap_dir) if not f.startswith(".")]
                if real_files:
                    return [PreflightResult(
                        name="SimpleRAG: bge-small-en-v1.5",
                        passed=True,
                        level="info",
                        detail=f"Model '{model_id}' cached ({len(real_files)} files)",
                    )]

    _log.info("Downloading fastembed model '%s'...", model_id)
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             f"from fastembed import TextEmbedding; TextEmbedding(model_name='{model_id}'); print('ok')"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and "ok" in result.stdout:
            return [PreflightResult(
                name="SimpleRAG: bge-small-en-v1.5",
                passed=True,
                level="info",
                detail=f"Model '{model_id}' downloaded and ready",
            )]
        return [PreflightResult(
            name="SimpleRAG: bge-small-en-v1.5",
            passed=False,
            level="warning",
            detail=f"Download failed (exit {result.returncode}): {result.stderr.strip()[:200]}",
        )]
    except subprocess.TimeoutExpired:
        return [PreflightResult(
            name="SimpleRAG: bge-small-en-v1.5",
            passed=False,
            level="warning",
            detail="Model download timed out after 300s — check network or pre-cache manually",
        )]
    except Exception as exc:
        return [PreflightResult(
            name="SimpleRAG: bge-small-en-v1.5",
            passed=False,
            level="warning",
            detail=f"Download error: {exc}",
        )]
```

### 5c: Add `_check_required_files` method

```python
def _check_required_files(self) -> list[PreflightResult]:
    """Verify that required_files exist in the target repository."""
    if not self.required_files:
        return []
    results = []
    for rel_path in self.required_files:
        full_path = os.path.join(self.repo_path, rel_path)
        exists = os.path.isfile(full_path)
        results.append(PreflightResult(
            name=f"Required file: {rel_path}",
            passed=exists,
            level="warning",
            detail=full_path if exists else f"NOT FOUND in target repo: {full_path}",
        ))
    return results
```

### 5d: Add both checks to `run()` method

In the `run()` method, add `self._check_fastembed_model` and `self._check_required_files` to the checks list:

```python
for check in [
    self._check_benchmark_python,
    self._check_git,
    self._check_python_packages,
    self._check_tool_cli_deps,
    self._check_tool_smoke_tests,
    self._check_api_keys,
    self._check_target_repo,
    self._check_target_deps,
    self._check_target_file_and_baseline,
    self._check_required_files,       # NEW
    self._check_serena_global_config,
    self._check_semble_model,
    self._check_fastembed_model,      # NEW
]:
```

---

## Fix 6: src/orchestrator/benchmark.py — pass required_files to PreflightChecker

File: `src/orchestrator/benchmark.py`

In `_run_preflight()` method, add `required_files=self.required_files` to the `PreflightChecker(...)` call:

```python
checker = PreflightChecker(
    repo_path=self.repo_path,
    configs=self.tools_configs,
    test_cmd=self.test_cmd,
    dry_run=self.dry_run,
    selected_ids=selected_ids,
    target_file=self.task_config.target_file,
    target_test=self.task_config.target_file,
    required_files=self.required_files,   # NEW
)
```

---

## Fix 7: src/features/dashboard_builder.py — add new columns to Table 1 and Table 2

File: `src/features/dashboard_builder.py`

### 7a: Table 1 — add 3 new columns after `duration_sec`

In the t1_rows construction loop, after `<td data-val="{c['duration_sec']:.1f}">{c['duration_sec']:.1f}s</td>`:
```html
<td data-val="{c.get('agent_cycles', 0)}">{c.get('agent_cycles', 0)}</td>
<td data-val="{c.get('avg_tokens_per_tool', 0):.1f}">{c.get('avg_tokens_per_tool', 0):.0f}</td>
<td data-val="{c.get('context_waste_ratio', 0):.3f}">{c.get('context_waste_ratio', 0):.1%}</td>
```

### 7b: Table 1 headers — add matching headers

In the Table 1 header `<tr>`, add after the duration header:
```html
<th onclick="sortTable('table-winners', 9)">Cycles</th>
<th onclick="sortTable('table-winners', 10)">Tok/Tool</th>
<th onclick="sortTable('table-winners', 11)">Waste%</th>
```

### 7c: Table 2 — add new columns at the end (before made_changes)

After `<td>{c.get('errors',0)}/{c.get('tool_errors',0)}</td>`, add:
```html
<td>{c.get('agent_cycles', 0)}</td>
<td>{c.get('avg_tokens_per_tool', 0):.0f}</td>
<td>{c.get('time_to_target', 0)}</td>
<td>{c.get('context_waste_ratio', 0):.1%}</td>
<td>{c.get('warmup_sec', 0):.1f}s</td>
```

### 7d: Table 2 headers — add matching headers

After the `errors/tool_errors` header:
```html
<th>Cycles</th>
<th>Tok/Tool</th>
<th>TTT</th>
<th>Waste%</th>
<th>Warmup</th>
```

## Implementation Notes
- Do NOT modify any other files
- Run `uv run python -m pytest tests/ -x -q` after each file change to verify no regressions
- For the dashboard HTML change, find the exact string by reading the file first
- For preflight, find exact location of `_check_semble_model` to insert after it
- English only in all code/comments

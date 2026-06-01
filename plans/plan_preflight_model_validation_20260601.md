# Plan: Preflight Model Existence Validation + Fix gpt-5.1-mini

## Problem

The judge model `gpt-5.1-mini` does not exist on OpenAI. It is:
1. Hardcoded in `configs/provider.yaml` line 14 as the judge model
2. Hardcoded as the default in `src/core/models.py` line 27 (`JudgeConfig.model`)

Additionally, there is no preflight check that validates model existence before spending money
on a real benchmark run. If a model is renamed/removed, the entire run fails mid-way.

## Fix 1: Correct the model name (2 files)

### `configs/provider.yaml`
Change line 14:
```yaml
  model: "gpt-5.1-mini"       # direct OpenAI Platform, NOT via OpenRouter
```
To:
```yaml
  model: "gpt-4.1-mini"       # direct OpenAI Platform, NOT via OpenRouter
```

### `src/core/models.py`
Change line 27 (JudgeConfig default):
```python
model: str = "gpt-5.1-mini"
```
To:
```python
model: str = "gpt-4.1-mini"
```

## Fix 2: Add `_check_models_exist()` to PreflightChecker

### `src/features/preflight.py`

**Constructor change** — add optional `provider_cfg` parameter:
```python
from src.core.models import AgentConfig, ProviderConfig  # add ProviderConfig

def __init__(
    self,
    repo_path: str,
    configs: list[AgentConfig],
    test_cmd: str,
    dry_run: bool = False,
    selected_ids: list[str] | None = None,
    target_file: str | None = None,
    target_test: str | None = None,
    required_files: list[str] | None = None,
    provider_cfg: ProviderConfig | None = None,   # NEW
):
    ...
    self.provider_cfg = provider_cfg
```

**New method** `_check_models_exist()`:

Logic:
1. In dry_run mode: return a single info-level PASS ("skipped in dry-run")
2. Collect models to check:
   - Agent model: `self.provider_cfg.model` with provider `self.provider_cfg.provider`
   - Judge model: `self.provider_cfg.judge.model` with provider `self.provider_cfg.judge.provider`
   - If no provider_cfg: return []
3. For each unique (provider, model) pair:
   - provider == "openai": use `openai.models.retrieve(model_id)` — if it raises NotFoundError, FAIL (critical)
   - provider == "anthropic": use `anthropic.models.list()` and check membership
   - other providers: skip with info-level (cannot validate without SDK)
4. Level: CRITICAL for each model — a missing model blocks the entire run

Implementation for OpenAI check:
```python
import openai as _openai
client = _openai.OpenAI(api_key=os.getenv(api_key_env) or "")
try:
    _openai_client.models.retrieve(model_id)
    return PreflightResult(name=f"Model exists: {model_id}", passed=True, level="critical", detail="OK")
except _openai.NotFoundError:
    return PreflightResult(name=f"Model exists: {model_id}", passed=False, level="critical",
                           detail=f"Model '{model_id}' not found on {provider}. Check provider.yaml.")
except Exception as e:
    return PreflightResult(name=f"Model exists: {model_id}", passed=False, level="critical",
                           detail=f"Could not verify model '{model_id}': {e}")
```

**Register the check** in `run()` — add `self._check_models_exist` to the checks list, BEFORE the main benchmark starts (place it after `self._check_api_keys`).

### `src/orchestrator/benchmark_runner.py`

In `_run_preflight()`, pass `provider_cfg`:
```python
checker = PreflightChecker(
    repo_path=self.repo_path,
    configs=self.tools_configs,
    test_cmd=self.test_cmd,
    dry_run=self.dry_run,
    selected_ids=selected_ids,
    target_file=self.task_config.target_file,
    target_test=self.task_config.target_file,
    required_files=self.required_files,
    provider_cfg=self.provider_config,   # ADD THIS
)
```

This requires `self.provider_config` to be accessible — check BenchmarkOrchestrator's `__init__` to confirm the attribute name (it may be `self.provider_cfg` or `self.provider_config`).

### `main.py`

In `_run_setup_pipeline()`, the PreflightChecker is also instantiated. Pass provider_cfg there too.
The `args.provider` is available; load ProviderConfig from it and pass it in.

## Fix 3: Tests

### `tests/features/test_preflight.py`

Add two test cases to the existing test class:

**Test 1: model check skipped in dry_run**
```python
def test_model_check_skipped_in_dry_run(self):
    from src.core.models import ProviderConfig
    checker = PreflightChecker(
        repo_path=self.tmp_dir,
        configs=[],
        test_cmd="pytest",
        dry_run=True,
        provider_cfg=ProviderConfig(model="gpt-999-nonexistent"),
    )
    results = checker._check_models_exist()
    self.assertTrue(all(r.passed for r in results))
```

**Test 2: nonexistent model fails (mocked)**
```python
@patch("openai.OpenAI")
def test_model_check_fails_for_nonexistent_model(self, mock_openai):
    from src.core.models import ProviderConfig, JudgeConfig
    import openai
    mock_client = MagicMock()
    mock_client.models.retrieve.side_effect = openai.NotFoundError(
        message="model not found", response=MagicMock(status_code=404), body={}
    )
    mock_openai.return_value = mock_client

    checker = PreflightChecker(
        repo_path=self.tmp_dir,
        configs=[],
        test_cmd="pytest",
        dry_run=False,
        provider_cfg=ProviderConfig(model="gpt-999-fake", judge=JudgeConfig(model="gpt-999-fake")),
    )
    results = checker._check_models_exist()
    self.assertTrue(any(not r.passed for r in results))
```

## Validation

After implementation, run:
```bash
# Tests pass
source /home/artem/.venvs/tools_token_economy/bin/activate
cd /mnt/c/Users/User/a_projects/tools_token_economy
pytest tests/features/test_preflight.py -q --tb=short

# Setup shows model check in preflight report
bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --setup
```

Expected: preflight report shows `[PASS]  Model exists: gpt-4.1-mini` and `[PASS]  Model exists: gpt-4.1-mini` (judge).

# Plan: Change judge model to gpt-5.4-nano

## Changes

### 1. `configs/provider.yaml`
In the `judge:` section, change:
```yaml
  model: "gpt-4.1-mini"
```
to:
```yaml
  model: "gpt-5.4-nano"
```

### 2. `src/core/models.py`
In `JudgeConfig`, change default:
```python
model: str = "gpt-4.1-mini"
```
to:
```python
model: str = "gpt-5.4-nano"
```

## Validation
Run in WSL:
```bash
bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --setup
```
Preflight should show `[PASS]  Model exists: gpt-5.4-nano` in the model existence check.

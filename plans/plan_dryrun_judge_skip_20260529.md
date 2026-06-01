# Plan: Skip LLM Judge during dry-run
**Date:** 2026-05-29
**Scope:** 1 file change only

---

## Problem

In `src/orchestrator/benchmark.py`, `LLMJudge.evaluate()` is called after every config run
regardless of `self.dry_run`. During dry-run the agent returns a mock response (no real API calls),
but the judge still makes 7 real OpenAI API calls per config (140 calls for a full 20-config dry-run).
This wastes quota and makes dry-runs slow.

---

## Fix

**File:** `src/orchestrator/benchmark.py`

Find the block that calls `LLMJudge.evaluate()` inside `_run_single_config()`.
It looks like this:

```python
            # LLM Judge Evaluation
            messages_data: list[dict] = []
            try:
                if os.path.exists(log_path):
                    with open(log_path, encoding="utf-8") as f:
                        messages_data = json.load(f)

                patch_path = os.path.join(run_dir, "final.patch")
                patch_content = None
                if os.path.exists(patch_path):
                    with open(patch_path, encoding="utf-8") as f:
                        patch_content = f.read()

                judge = LLMJudge()
                report = judge.evaluate(
                    ...
                )
```

Wrap the entire judge block with `if not self.dry_run:` so it becomes:

```python
            # LLM Judge Evaluation (skipped in dry-run)
            messages_data: list[dict] = []
            if not self.dry_run:
                try:
                    if os.path.exists(log_path):
                        with open(log_path, encoding="utf-8") as f:
                            messages_data = json.load(f)

                    patch_path = os.path.join(run_dir, "final.patch")
                    patch_content = None
                    if os.path.exists(patch_path):
                        with open(patch_path, encoding="utf-8") as f:
                            patch_content = f.read()

                    judge = LLMJudge()
                    report = judge.evaluate(
                        ...
                    )
                    run_metrics = run_metrics.model_copy(update={...})
                except Exception as e:
                    self.logger.warning("LLM Judge failed for config %s: %s", config.id, e)
```

Similarly, the retrieval metrics block right after the judge block:

```python
            # Retrieval precision/recall (computed, not judge-based)
            required = self.required_files
            if required and messages_data:
                try:
                    precision, recall = compute_retrieval_metrics(messages_data, required)
                    ...
```

This block already guards on `messages_data` being non-empty — in dry-run it will be `[]`
so it naturally skips. No change needed for this block.

---

## Important notes for Gemini

1. Find the EXACT text of the judge block in the current file before editing.
2. Preserve ALL the indentation and logic inside the block — just add `if not self.dry_run:` before it
   and indent everything inside by one extra level (4 spaces).
3. The `messages_data` variable must still be initialized to `[]` BEFORE the `if not self.dry_run:` block
   (so the retrieval metrics block below still compiles).
4. After the change, run:
   ```
   wsl bash -c "export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:/usr/local/bin:\$PATH\" && source /home/artem/.venvs/tools_token_economy/bin/activate && cd /mnt/c/Users/User/a_projects/tools_token_economy && python -m pytest tests/ -q --tb=short 2>&1 | tail -5"
   ```
   All 157 tests must still pass.

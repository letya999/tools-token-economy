# Plan: Fix Agent Instructions — Include `edit` as Valid Write Tool

**Date**: 2026-05-29

## Problem

In `src/features/agent_integration/agno_runner.py`, the `_build_agent()` instructions
tell the agent it MUST call `write` or `patch` before TASK_COMPLETE. But `edit` and
`insert_after` are also valid file-modification tools. An agent that correctly uses
`edit` to modify existing files will believe it hasn't "saved" — causing it to loop,
hit the write guard, and exhaust all 50 steps without completing.

Same issue in `configs/tasks/medium.yaml` — the task description says "calling write/patch".

## Fix 1 — `src/features/agent_integration/agno_runner.py`

In the `_build_agent()` method, find the `instructions=[...]` list.

There are 3 strings that need updating:

### String A — find:
```python
"MANDATORY: You MUST call the `write` or `patch` tool to save your code changes to disk before saying TASK_COMPLETE. Reading files and thinking about changes is not enough - you must persist changes with a tool call.",
```
Replace with:
```python
"MANDATORY: You MUST call at least one file-modification tool (`write`, `edit`, `patch`, or `insert_after`) to save your code changes to disk before saying TASK_COMPLETE. Reading files and thinking about changes is not enough - you must persist changes with a tool call.",
```

### String B — find:
```python
"Workflow: (1) Use retrieval tools to understand the codebase. (2) Write your changes using `write` (full file) or `patch` (unified diff). (3) Verify by reading the file back. (4) Output exactly: TASK_COMPLETE",
```
Replace with:
```python
"Workflow: (1) Use retrieval tools to understand the codebase. (2) Save your changes using `edit` (modify specific section — preferred for existing files), `write` (full file replacement — only when creating new files or replacing entirely), `patch` (unified diff), or `insert_after` (add new code after anchor). (3) Verify by reading the file back. (4) Output exactly: TASK_COMPLETE",
```

### String C — find:
```python
"Never output TASK_COMPLETE if you have not called write or patch at least once.",
```
Replace with:
```python
"Never output TASK_COMPLETE if you have not called at least one of: write, edit, patch, insert_after.",
```

## Fix 2 — `configs/tasks/medium.yaml`

Find the line:
```
  Finalize by calling write/patch to save changes and output: TASK_COMPLETE.
```
Replace with:
```
  Finalize by saving changes with any write tool (edit, write, patch, or insert_after) and output: TASK_COMPLETE.
```

## Files to modify

1. `src/features/agent_integration/agno_runner.py` — 3 instruction strings in `_build_agent()`
2. `configs/tasks/medium.yaml` — 1 line in description

## Verification

After changes, grep to confirm:
```
grep -n "write or patch\|write/patch" src/features/agent_integration/agno_runner.py configs/tasks/medium.yaml
```
Should return NO matches.

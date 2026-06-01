# Task Authoring Guide

This guide explains how to add new benchmark tasks and task suites to the Tools Token Economy Benchmark.

## Goal: External Validity
To truly evaluate a toolset, we must test it across many diverse tasks. A winning tool should be consistently better across different retrieval archetypes (e.g., finding strings, understanding structure, fixing bugs).

## Task Category Taxonomy
When authoring a task, assign it to one of these categories:
- `structural`: Requires understanding class/function hierarchies or call graphs.
- `string_search`: Can be solved by simple text search (e.g., renaming a variable).
- `bugfix`: Requires identifying and fixing a logical error.
- `refactor`: Changing implementation without changing behavior (e.g., optimizing a query).
- `feature`: Adding a small, isolated capability.
- `schema_change`: Modifying API schemas or database models.
- `constant_extraction`: Moving hardcoded values to constants.
- `signature_change`: Changing function or method arguments.
- `test_addition`: Adding new test cases for edge cases.

## Core Rules for Tasks

### 1. Deterministic Verification
Each task MUST have a `test_cmd` that yields a binary PASS/FAIL outcome. Prefer `pytest` on a specific file. The benchmark uses this command to verify success.

### 2. Memory-Proof Logic
Tasks must target bespoke repository logic that an LLM could not have seen in its training data.
- **Rule of Thumb**: A config with NO retrieval tools (e.g., `bash_only`) should NOT be able to solve the task with fewer than 2 file reads.
- Use internal commitment rules, specific column names, and unique project structures.

### 3. Isolated Worktrees
Tasks are executed in isolated git worktrees. They can modify files, and the benchmark will capture the diff.

## Adding a Task
1. Create a YAML file in `configs/tasks/<name>.yaml`.
2. Follow this schema:
```yaml
difficulty: "medium"
name: "my_task"
description: "Detailed description of the task..."
test_cmd: "uv run pytest tests/unit/test_my_logic.py -q"
timeout_sec: 600
target_file: "src/logic.py"
required_files:
  - "src/logic.py"
  - "tests/unit/test_my_logic.py"
success_criteria:
  - "Condition A is met"
  - "Tests pass"
```

## Creating a Task Suite
A suite allows running many tasks in one command.
1. Create a YAML file in `configs/task_suites/<name>.yaml`.
2. Manifest schema:
```yaml
name: "my_suite_v1"
description: "Collection of diverse tasks."
codebase: "configs/codebase.yaml"
tasks:
  - file: "configs/tasks/task_01.yaml"
    category: "structural"
  - file: "configs/tasks/task_02.yaml"
    category: "bugfix"
```

## Running the Suite
Use the `--task-suite` flag:
```bash
python main.py --task-suite configs/task_suites/my_suite_v1.yaml
```

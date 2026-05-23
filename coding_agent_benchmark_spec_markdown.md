# Goal

Построить локальный benchmark framework для исследования token-efficiency и task-efficiency coding agents на одном среднем реальном репозитории и одной фиксированной задаче.

Цель:
- сравнить retrieval/navigation strategies современных coding agents
- выяснить, какие tool combinations дают лучший:
  - success rate
  - token efficiency
  - latency
  - accuracy
- проверить реальные archetypes:
  - Cursor-like
  - Claude Code-like
  - Gemini-like
  - Codex-like
- отдельно проверить:
  - grep family
  - AST/LSP approaches
  - semantic retrieval
  - Serena
  - Semble
  - Serena + Semble

Важно:
это НЕ production coding agent.
Это reproducible eval harness / experimentation framework.

---

# Environment

Host OS:
- Windows 11 Pro

Execution environment:
- WSL2 Ubuntu

Main runtime:
- Python 3.12+

Package manager:
- uv preferred
- alternatively poetry/pip

Agent runtime:
- OpenCode

Model backend:
- Gemini 2.5 Flash (free tier)

Constraints:
- 10 requests per minute
- free quota
- sequential execution only
- no parallel agent runs

---

# Main Architectural Idea

Нужен один orchestrator, который:
- автоматически переключает configs
- запускает один и тот же task
- делает git rollback после каждого run
- собирает metrics
- сохраняет patches/logs/results

Система должна быть полностью reproducible.

---

# Benchmark Philosophy

Нужно тестировать:
- НЕ “магические агенты”
- а retrieval/navigation/tool strategies

Важно:
- один repo
- одна и та же задача
- одинаковый model
- одинаковые limits
- одинаковый evaluation pipeline

Меняется только:
- tool configuration
- retrieval strategy

---

# Repository Setup

Используется:
- один средний реальный repository

Для каждого run:
1. checkout/reset к фиксированному commit
2. запуск агента
3. выполнение задачи
4. запуск eval/tests
5. сохранение результатов
6. полный rollback назад

Никакого накопления изменений между runs.

---

# Git Isolation Strategy

Предпочтительно использовать:

```bash
git worktree
```

Для каждого run:
- отдельный isolated worktree
- после завершения удаляется

Если слишком сложно:
- `git reset --hard`
- `git clean -fdx`

---

# Agent Architecture

Нужен простой coding-agent loop:

```text
observe
-> think
-> tool call
-> observe result
-> patch/edit
-> test/eval
-> repeat
```

Важно:
- deterministic execution
- reproducible logs
- configurable tool access

---

# Core Tool Categories

## Basic File Tools

- read
- read_all
- write
- patch
- glob

## Grep Family

Проверить отдельно:

- grep
- git grep
- ripgrep (rg)
- ugrep
- semgrep

Важно:
grep-family должен быть отдельной категорией benchmark.

---

# Structural Navigation

Проверить отдельно:

- tree-sitter AST
- LSP symbols/references
- repo_map

---

# Semantic Retrieval

Проверить отдельно:

- simple RAG
- Semble MCP
- Serena MCP

---

# Important Constraint

Нельзя делать “tool soup”.

Например:
- Serena уже покрывает часть symbolic navigation
- Semble уже покрывает semantic retrieval

Поэтому benchmark должен тестировать:
- clean strategies
- isolated mechanisms
- realistic hybrids

---

# Metrics To Collect

Для каждого run:

```text
success
tests_passed
eval_score
time_sec
model_calls
tool_calls
input_tokens
output_tokens
tool_output_tokens
total_tokens
estimated_cost
files_read
files_changed
patch_lines
errors
```

Главная метрика:

```text
success_per_token
```

Дополнительные:
- success_per_minute
- success_rate
- token_efficiency
- retrieval_efficiency

---

# Token Accounting

Использовать:
- provider usage stats
- tiktoken normalization

Нужно считать отдельно:
- model input/output
- tool outputs
- retrieval context size

---

# Evaluation Strategy

После каждого run:

1. запуск tests
2. optional custom evaluator
3. проверка:
   - fixed/not fixed
   - partial success
   - tests passed
4. сохранение:
   - patch
   - logs
   - metrics

---

# Execution Constraints

Gemini Flash free tier:
- 10 RPM

Поэтому:
- sequential execution only
- max_steps configurable
- max_calls_per_run configurable

Ожидаемая длительность:
~40–90 minutes for full benchmark suite.

---

# Benchmark Configurations

## Archetypes

### 01_cursor_like

```text
repo_map + simple_rag + read + patch + test
```

### 02_claude_code_like

```text
glob + rg + read + bash + patch + test
```

### 03_gemini_like

```text
repo_map + read_many + rg + patch + test
```

### 04_codex_like

```text
grep + read + patch + test
```

---

# Mechanism Ablations

### 05_read_only

```text
read + patch + test
```

### 06_read_all

```text
read_all + patch + test
```

### 07_grep

```text
grep + read + patch + test
```

### 08_git_grep

```text
git_grep + read + patch + test
```

### 09_rg

```text
rg + read + patch + test
```

### 10_ugrep

```text
ugrep + read + patch + test
```

### 11_semgrep

```text
semgrep + read + patch + test
```

### 12_tree_sitter

```text
tree_sitter_ast + read + patch + test
```

### 13_lsp

```text
lsp_symbols + read + patch + test
```

### 14_repo_map

```text
repo_map + read + patch + test
```

### 15_simple_rag

```text
simple_rag + read + patch + test
```

---

# Semantic / Hybrid Configs

### 16_serena_only

```text
serena + patch + test
```

### 17_semble_only

```text
semble + patch + test
```

### 18_rg_repo_map

```text
repo_map + rg + read + patch + test
```

### 19_rg_lsp

```text
rg + lsp_symbols + read + patch + test
```

### 20_serena_semble

```text
serena + semble + patch + test
```

---

# Desired Final Output

Нужен полностью автоматизированный benchmark framework, который:

- запускает configs sequentially
- автоматически откатывает repository
- собирает metrics
- считает tokens
- сохраняет patches
- сохраняет logs
- строит rankings/results

И позволяет ответить:

```text
Какая retrieval/navigation strategy
самая точная,
самая быстрая,
и самая token-efficient
для coding agents?
```


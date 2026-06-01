# Roadmap v2.0: Benchmark Framework for Coding Agents

## Контекст

Текущий бенчмарк запускает 20 конфигов (tool-стратегий) на одной жёстко прописанной в
`benchmark_configs.yaml` задаче и одной кодовой базе. Модель и провайдер также зашиты
в каждый конфиг.

**Цель v2.0:** разделить ортогональные оси конфигурации так, чтобы одной командой можно
было запустить те же 20 стратегий на новой задаче или другой модели, не трогая код.

---

## Новая конфиг-архитектура (5 файлов)

```
configs/
  provider.yaml          ← NEW  провайдер + модель
  tools.yaml             ← REN  (из benchmark_configs.yaml)  20 стратегий без model
  tasks/
    easy.yaml            ← NEW
    medium.yaml          ← NEW  (текущая задача переезжает сюда)
    hard.yaml            ← NEW
  codebase.yaml          ← NEW  целевой репозиторий
  benchmark_weights.yaml ← OK   веса (уже есть)
```

**Запуск бенчмарка (CLI):**
```bash
uv run python main.py 
  --provider  configs/provider.yaml 
  --tools     configs/tools.yaml 
  --task      configs/tasks/medium.yaml 
  --codebase  configs/codebase.yaml 
  --weights   configs/benchmark_weights.yaml
```

Без флагов — берутся дефолтные пути выше. Можно передать любой кастомный файл.
Результат: те же 20 прогонов, папки `run_TIMESTAMP_ID_TOOLNAME/`.

### `configs/provider.yaml`
```yaml
provider: openai          # openai | anthropic | google | ollama
model: gpt-4.1-mini
api_base: ""              # пусто = дефолтный endpoint провайдера
max_steps: 50             # глобальный дефолт, переопределяется в tools.yaml
temperature: 0.0
```

### `configs/tools.yaml`
Текущий `benchmark_configs.yaml` минус поля `model`, `max_steps` (берутся из provider.yaml,
кроме явного override в конкретном tool-конфиге).

```yaml
configs:
  - id: "01"
    name: "cursor_like"
    archetype: "cursor"
    tools: ["repo_map", "simple_rag", "read", "write", "patch", "insert_after", "shell"]
    max_steps: 50          # optional override
  - id: "02"
    name: "claude_code_like"
    archetype: "claude"
    tools: ["glob", "rg", "read", "write", "patch", "insert_after", "shell"]
  # ... остальные 18
```

### `configs/tasks/medium.yaml`  (current → here)
```yaml
difficulty: medium
name: "Google OAuth redirect scopes"
description: |
  Implement a system-wide execution timeout ...  # текущий task-текст
test_cmd: "uv run --extra dev pytest tests/unit/ -q"
timeout_sec: 1200
target_file: "tests/unit/test_api_google_oauth.py"
required_files:
  - "tests/unit/test_api_google_oauth.py"
  - "src/api/google_oauth.py"
success_criteria:
  - "All new tests pass"
```

### `configs/codebase.yaml`
```yaml
name: process_metrics_platform_v2
github_url: "https://github.com/letya999/process_metrics_platform_v2"
branch: main
commit: HEAD            # зафиксировать после клонирования
local_path: ""          # если задан — используется без клонирования (приоритет)
install_cmd: "uv sync --extra dev"
```

**Логика выбора пути (в benchmark.py):**
```python
if codebase.local_path and os.path.isdir(codebase.local_path):
    repo_path = codebase.local_path          # уже склонировано
else:
    repo_path = clone_repo(codebase)         # клонировать + вернуть путь
    # worktree создаётся поверх этого пути как сейчас
```

---

## Фаза 0 — Конфиг-рефакторинг

**Файлы к созданию:**
- `configs/provider.yaml`
- `configs/tools.yaml` (из benchmark_configs.yaml; убрать поля model/max_steps)
- `configs/tasks/easy.yaml`, `medium.yaml`, `hard.yaml`
- `configs/codebase.yaml`

**Файлы к изменению:**
- `src/core/models.py` — добавить `ProviderConfig`, `CoderbaseConfig`, `TaskConfig` dataclass/pydantic
- `src/orchestrator/benchmark.py` — читать 5 конфигов, строить матрицу прогонов
- `main.py` — добавить CLI-флаги `--provider`, `--tools`, `--task`, `--codebase`, `--weights`

**Backward compatibility:** старый `benchmark_configs.yaml` остаётся рядом пока не удалён вручную.

---

## Фаза 1а — Новые поля RunMetrics + сохранение артефактов

### Новые поля в `src/core/models.py` → `RunMetrics`

```python
# Телеметрия цикла
agent_cycles: int = 0
# Вычисляемое: tool_tokens / tool_calls (0 если tool_calls == 0)
avg_tokens_per_tool: float = computed_field(...)

# Discovery quality
time_to_target: int = 0   # номер цикла (1-based) когда впервые прочитан required_file

# Context waste
context_waste_ratio: float = 0.0   # (read_tokens_total - read_tokens_useful) / read_tokens_total

# MCP warmup (не входит в duration_sec)
warmup_sec: float = 0.0
```

### `agent_cycles` — как считать (решение)

Агно не даёт явных коллбэков на границы цикла. После `agent.run()` в `response.messages`
каждый `role == "tool"` message = завершение одного цикла think→tool→response.

```python
# В _collect_metrics() в agno_runner.py
agent_cycles = sum(1 for m in (response.messages or []) if getattr(m, "role") == "tool")
```

Это точный счётчик: каждый ответ от инструмента замыкает один цикл.
Разница `tool_calls - agent_cycles > 0` = параллельные вызовы (multi-tool calling).

### `context_waste_ratio` — как считать (решение)

Проблема с побайтовым счётчиком файлов: у нас нет маппинга "tool call → имя файла"
в агно — `response.tools[i].result` содержит контент, а не путь.

**Решение — двухуровневая аппроксимация:**

1. **Общие read-токены**: уже считаются через `role == "tool"` messages. Их токены —
   это `total_read_tokens` (уже есть как `tool_tokens`).

2. **Полезные токены**: из `response.tools` итерируемся по вызовам read-инструментов,
   для каждого смотрим на аргумент `path` (agno сохраняет args в `tool_exec.input`
   или можно парсить из текста ответа). Сравниваем с `required_files`. Если совпало —
   токены ответа = useful.

```python
_read_tools = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag"}
total_read_tok = 0
useful_read_tok = 0
required = set(task_config.required_files)   # передаём из task.yaml

for tool_exec in (response.tools or []):
    if tool_exec.tool_name not in _read_tools:
        continue
    res_str = str(getattr(tool_exec, "result", "") or "")
    tok = self._count_tokens(res_str)   # уже есть: tiktoken cl100k / len//4
    total_read_tok += tok
    # Определяем имя файла из аргументов вызова
    args = getattr(tool_exec, "input", {}) or {}
    file_arg = args.get("path") or args.get("file_path") or args.get("query") or ""
    if any(req in file_arg or file_arg in req for req in required):
        useful_read_tok += tok

context_waste_ratio = (
    (total_read_tok - useful_read_tok) / total_read_tok
    if total_read_tok > 0 else 0.0
)
```

Это не 100% точно (glob возвращает список файлов, не контент), но даёт честный
signal: сколько токенов tool-ответов пришло из нужных файлов vs шума.

### Сохранение артефактов

В `benchmark.py` / `agno_runner.py` после завершения каждого прогона сохранять в папку
`results/run_TIMESTAMP_ID_NAME/`:

**`agent_messages.json`** — сериализация `response.messages`:
```python
msgs = []
for m in (response.messages or []):
    msgs.append({
        "role": getattr(m, "role", ""),
        "content": str(getattr(m, "content", "") or "")[:4000],  # обрезка
        "tool_calls": [tc.model_dump() for tc in (getattr(m, "tool_calls", None) or [])],
    })
with open(os.path.join(run_dir, "agent_messages.json"), "w") as f:
    json.dump(msgs, f, ensure_ascii=False, indent=2)
```

**`final.patch`** — diff после прогона:
```python
patch = subprocess.run(
    ["git", "diff", "HEAD"],
    cwd=worktree_path, capture_output=True, text=True
).stdout
with open(os.path.join(run_dir, "final.patch"), "w") as f:
    f.write(patch)
```

---

## Фаза 1б — MCP Warmup

### Изменение `McpServerConfig` в `src/core/models.py`

```python
class McpServerConfig(BaseModel):
    ...
    warmup_call: str | None = None   # имя MCP-тула для прогрева, e.g. "get_symbols_overview"
    warmup_args: dict = {}
```

### Изменение `agno_runner.py` — до старта таймера

```python
# В _run_with_mcp(), до строки start_time = time.time()
warmup_total = 0.0
for mcp_cfg in (self.mcp_configs or []):
    if mcp_cfg.warmup_call:
        t_w = time.time()
        await mcp_client.call_tool(mcp_cfg.warmup_call, mcp_cfg.warmup_args)
        warmup_total += time.time() - t_w

start_time = time.time()   # основной таймер стартует ПОСЛЕ прогрева
...
metrics.warmup_sec = warmup_total
```

---

## Фаза 2 — HTML-дашборд (обновление)

**`configs/benchmark_weights.yaml`** — добавить в `all_metrics_weights`:
```yaml
avg_tokens_per_tool:
  weight: 0.040
  direction: lower
  description: Average tokens per tool call — lower = more surgical tool use
time_to_target:
  weight: 0.030
  direction: lower
  description: Agent cycle when first required file was read — lower = faster discovery
context_waste_ratio:
  weight: 0.040
  direction: lower
  description: Fraction of read tokens that came from non-required files
```

(Пересчитать суммы, чтобы total = 1.0.)

**`src/features/dashboard_builder.py`** — добавить новые колонки в Table 1 и Table 2.

---

## Фаза 3 — Streamlit MVP

### Минимальный набор (MVP)

Файл: `streamlit_app.py` в корне проекта.

```
Sidebar:
  - Выбор timestamp прогона (dropdown из results/)
  - Фильтр: All / Pass Only / Fail Only

Tab 1 — Leaderboard:
  st.dataframe (sortable) с колонками:
  config, pass, eval_composite, full_composite, tokens, cost, SPT, TTT, waste%

Tab 2 — Config Deep Dive:
  - Выбор конфига из результатов текущего прогона
  - Radar chart (plotly): 7 judge dimensions vs медиана
  - Judge Reasoning: st.expander для каждого из 7 судейских блоков
  - Code Diff: st.code() с final.patch (подсветка ± строк через CSS)
  - Agent Timeline: таблица tool-вызовов из agent_messages.json
    [цикл | инструмент | аргументы | токены | ошибка]
```

**За рамками MVP (v2.1+):**
- Cross-run comparison (несколько timestamp'ов)
- Agent Mind Timeline с reasoning текстами между вызовами
- Интерактивный radar с несколькими конфигами на одном графике

### Зависимости

```toml
# pyproject.toml
streamlit = ">=1.35"
plotly = ">=5.20"
```

Запуск: `uv run streamlit run streamlit_app.py`

---

## Порядок реализации

| Шаг | Что | Приоритет | Риск |
|-----|-----|-----------|------|
| 0 | Конфиг-рефакторинг (5 файлов + CLI) | Критично | Низкий |
| 1а | RunMetrics поля + agent_messages.json + final.patch | Высокий | Низкий |
| 1б | agent_cycles + context_waste_ratio + time_to_target | Высокий | Средний |
| 1в | MCP warmup (McpServerConfig + agno_runner) | Средний | Низкий |
| 2 | HTML dashboard новые колонки | Средний | Низкий |
| 3 | Streamlit MVP | Низкий | Средний |

---

## Открытые вопросы (перед реализацией)

1. **tool_exec.input формат** — нужно проверить в агно что поле `input` содержит
   аргументы вызова (path/file_path), прежде чем реализовывать context_waste_ratio.
   Альтернатива: парсить первую строку result-текста как path.

2. **required_files передача в runner** — сейчас TaskConfig не передаётся в AgnoRunner.
   Нужно добавить его как параметр `__init__` или передавать в `run()`.

3. **Worktree vs clone** — codebase.yaml предполагает что benchmark клонирует репо.
   Сейчас benchmark создаёт git-worktree поверх существующего репо. Нужно согласовать:
   если `local_path` задан → создать worktree из него (как сейчас).
   Если только `github_url` → сначала клонировать в `~/.cache/benchmark_repos/{name}`,
   затем worktree из клона.

4. **easy/hard задачи** — нужно создать реальные задачи разной сложности на той же
   кодовой базе. Это контентная работа, не техническая.

This document outlines the development plan for the framework testing token-efficiency and task-efficiency of AI agents (based on OpenCode) using TDD, Clean Architecture, and Vertical Feature Sliced Design.

## Phase 1: Project Setup & Core Infrastructure [DONE]

### Task 1: Project Initialization & QA Tools [DONE]
**Description:** Set up the base environment using `uv`, add linters, formatters, and a testing framework. Configure `.gitignore`.
**Acceptance Criteria (AC):**
- Project initialized via `uv init`.
- `pyproject.toml` contains dependencies: `pytest`, `pytest-mock`, `ruff`, `pydantic`.
- `.gitignore` configured (excludes `worktrees/`, `results/`, etc.).
- `ruff check` and `pytest` run without errors.

### Task 2: Architectural Documentation & Memory Initialization [DONE]
**Description:** Create `AGENTS.md` (agent instructions), `docs/ARCHITECTURE.md` (VFSD + Clean Arch description), and initialize `MEMORY.md`.
**AC:**
- `AGENTS.md` created with project rules.
- `docs/ARCHITECTURE.md` created with layer diagrams.
- `MEMORY.md` initialized in the private project folder.
- Base conventions for Serena/Semble described.

### Task 3: Core Domain Models Implementation [DONE]
**Description:** Create Pydantic models for strict typing of configurations, results, and metrics.
**AC:**
- `AgentConfig`, `RunMetrics`, and `EvalResult` models created.
- Model creation and validation covered by tests.

### Task 4: Rate Limiter Implementation (10 RPM) [DONE]
**Description:** Create a mechanism to control the frequency of requests to Gemini 2.5 Flash to respect free tier limits.
**AC:**
- `RateLimiter` decorator/context manager implemented.
- Tests prove that 12 calls are distributed with the correct delay (no faster than 10 per minute).

---

## Phase 2: Environment Isolation & Evaluation Engine [DONE]

### Task 5: Environment Isolation (Git Worktree) [DONE]
**Description:** Implement the logic for creating isolated copies of the target repository for each run using `git worktree`.
**AC:**
- `GitIsolationProvider` class implemented.
- TDD: Tests verify worktree creation, file existence, and complete cleanup after `teardown()`.

### Task 6: Command Execution Abstraction (WSL2 Subprocess) [DONE]
**Description:** Wrapper over `subprocess` for safe shell command execution within the prepared worktree.
**AC:**
- `ShellExecutor` implemented with timeout support.
- Tests verify successful `stdout`/`stderr` capture and non-zero exit code handling.

### Task 7: Execution Evaluation (Evaluation Engine) [DONE]
**Description:** Logic for running tests in the target repository and determining task success.
**AC:**
- `ExecutionValidator` implemented (replacing `EvalEngine`), with `UV_PROJECT_ENVIRONMENT` isolation.
- Tests verify parsing of successful, failed, and partial test runs.

### Task 8: Patch Application Mechanism [DONE]
**Description:** Reliable application of diffs/patches generated by the agent.
**AC:**
- `PatchApplier` tool implemented.
- Tests for successful and conflicting patch application.

---

## Phase 3: Tool Registry & Adapters

### Task 9: Basic File Tools [DONE]
**Description:** Implement `read`, `read_all`, `write`, `patch`, `glob` tools in OpenCode-compatible format.
**AC:**
- Tool classes created, inheriting from the base interface.
- Unit tests written for each tool.

### Task 10: Grep Family Tools [DONE]
**Description:** Implement `grep`, `git grep`, `rg` (ripgrep), `ugrep`, `semgrep`.
**AC:**
- Wrappers implemented calling binaries via `ShellExecutor`.
- Tools return results with line numbers and context.
- Tests written using mock files.

### Task 11: Structural Navigation Tools [DONE]
**Description:** Implement `tree-sitter AST`, `lsp_symbols/references`, `repo_map`.
**AC:**
- Parsers connected (e.g., `tree-sitter-python`).
- `repo_map` generates a compact file and symbol tree.
- Covered by tests.

### Task 12: Semantic Retrieval Tools [DONE]
**Description:** Integration with `Serena MCP`, `Semble MCP`, and base implementation of `Simple RAG`.
**AC:**
- Stubs or full MCP clients for Serena and Semble created.
- `Simple RAG` implemented.
- Tool isolation verified (no "tool soup").

---

## Phase 4: OpenCode Integration & Telemetry [DONE]

### Task 13: OpenCode Adapter (Runtime Adapter) [DONE]
...
### Task 14: Tool Injector [DONE]
...
### Task 15: Token Accounting [DONE]
...
### Task 16: Metrics Aggregation & Logging [DONE]

---

## Phase 5: Orchestrator, Configurations & E2E [DONE]

### Task 17: Configuration Registry (20 Configs) [DONE]
**Description:** Transfer 20 configurations from the spec to code.
**AC:**
- `configs/benchmark_configs.yaml` contains 20 valid descriptions.
- Parser successfully loads configs into `AgentConfig` objects.

### Task 18: Main Orchestrator Loop [DONE]
**Description:** Assemble all components: Config -> Worktree -> Run OpenCode -> Eval -> Teardown -> Report.
**AC:**
- `benchmark.py` (entrypoint) written.
- Orchestrator handles sequential suite execution and rollback on failure.

### Task 19: E2E Dry-Run (Mock Agent) [DONE]
**Description:** Run the pipeline with a Mock model that doesn't call the real API.
**AC:**
- `--dry-run` flag added.
- Script passes 20 configurations without real token expenditure.

### Task 20: Final E2E Run on Test Repository [DONE]
**Description:** Full execution on a small test repository with real Gemini 2.5 Flash.
**AC:**
- `benchmark.py` execution successful.
- Final rankings table generated.
- Rate limits respected.


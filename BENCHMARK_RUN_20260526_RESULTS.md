# Benchmark Run: run_20260526_213013

**Date:** 2026-05-26 21:30 — 2026-05-27 09:13  
**Status:** INVALID — infrastructure failure (NTFS eval_venv bug, see Errors section)  
**Configs:** 20/20 completed  
**Execution pass rate:** 0/20 (all `outcome=failed`, not agent fault)  
**Judge pass rate (task quality):** 12/20 scored jT=1.0

---

## Full Results Table

| Config | jTask | jContext | jTools | Tokens | Cost | Time | Calls | Err | Made | Outcome |
|--------|-------|---------|--------|--------|------|------|-------|-----|------|---------|
| 01_cursor_like | 0.60 | — | 0.50 | 17,077 | $0.00868 | 4.1m | 8 | 4 | Y | failed |
| 02_claude_code_like | 1.00 | — | 0.50 | 17,828 | $0.01046 | 4.2m | 5 | 4 | Y | failed |
| 03_gemini_like | 0.60 | — | 0.50 | 371,381 | $0.14922 | 4.3m | 7 | 4 | Y | failed |
| 04_codex_like | 1.00 | — | 0.50 | 3,511 | $0.00176 | 3.5m | 3 | 4 | Y | failed |
| 05_read_only | 0.00 | — | 0.00 | 1,924 | $0.00113 | 3.4m | 2 | 4 | N | failed |
| 06_read_all | 0.60 | — | 0.50 | 12,295 | $0.00646 | 5.4m | 7 | 4 | Y | failed |
| 07_grep | 1.00 | — | 0.50 | 5,018 | $0.00241 | **607m** | 4 | 4 | Y | failed |
| 08_git_grep | 1.00 | — | 0.50 | 13,261 | $0.00625 | 3.6m | 8 | 4 | Y | failed |
| 09_rg | 1.00 | — | 0.50 | 3,652 | $0.00181 | 4.0m | 3 | 4 | Y | failed |
| 10_ugrep | 1.00 | — | 0.50 | 3,655 | $0.00182 | 3.5m | 3 | 4 | Y | failed |
| 11_ast_grep | 1.00 | — | 0.50 | 15,389 | $0.00662 | 3.7m | 6 | 4 | Y | failed |
| 12_tree_sitter | 0.00 | — | 0.50 | 5,643 | $0.00276 | 0.2m | 4 | 0 | N | not_verified |
| 13_lsp | 0.60 | — | 0.70 | 8,816 | $0.00403 | 3.8m | 5 | 5 | Y | failed |
| 14_repo_map | 1.00 | — | 0.50 | 4,519 | $0.00211 | 3.7m | 3 | 4 | Y | failed |
| 15_simple_rag | 1.00 | — | 0.50 | 7,333 | $0.00361 | 3.7m | 5 | 4 | Y | failed |
| 16_serena_only | 1.00 | — | 0.50 | 30,003 | $0.01230 | 3.9m | 5 | 4 | Y | failed |
| 17_semble_only | 0.60 | — | 0.50 | 10,184 | $0.00514 | 4.6m | 5 | 4 | Y | failed |
| 18_rg_repo_map | 0.60 | — | 0.50 | 34,396 | $0.01579 | 3.9m | 10 | 4 | Y | failed |
| 19_rg_lsp | 1.00 | — | 0.50 | 3,660 | $0.00175 | 3.6m | 3 | 5 | Y | failed |
| 20_serena_semble | 1.00 | — | 0.50 | 68,851 | $0.03107 | 4.9m | 7 | 4 | Y | failed |
| **TOTAL** | | | | **638,396** | **$0.275** | **~11.3h** | | | | 0/20 |

> `jContext` column is `—` because context quality dimension was not yet implemented in this run. See eval requirements below.

### Token Efficiency Ranking (jTask=1.0, made changes)

| Rank | Config | Tokens | Cost | Time |
|------|--------|--------|------|------|
| 1 | 04_codex_like | 3,511 | $0.0018 | 3.5m |
| 2 | 19_rg_lsp | 3,660 | $0.0018 | 3.6m |
| 3 | 09_rg | 3,652 | $0.0018 | 4.0m |
| 4 | 10_ugrep | 3,655 | $0.0018 | 3.5m |
| 5 | 14_repo_map | 4,519 | $0.0021 | 3.7m |
| 6 | 07_grep | 5,018 | $0.0024 | **607m** ⚠️ |
| 7 | 15_simple_rag | 7,333 | $0.0036 | 3.7m |
| 8 | 08_git_grep | 13,261 | $0.0063 | 3.6m |
| 9 | 11_ast_grep | 15,389 | $0.0066 | 3.7m |
| 10 | 02_claude_code_like | 17,828 | $0.0105 | 4.2m |
| 11 | 16_serena_only | 30,003 | $0.0123 | 3.9m |
| 12 | 20_serena_semble | 68,851 | $0.0311 | 4.9m |

### Anomalies

- **03_gemini_like:** 371K tokens / $0.149 — 100x более дорогой чем топ-конфиги. Агент зациклился.
- **07_grep:** 607 минут — subprocess pipe hang (см. Error #2). Реальное время агента ~4 минут.
- **12_tree_sitter:** made=False, not_verified — агент не смог использовать tool.

---

## AI Evaluation Rubric (3 Dimensions)

Все оценки используют **нечёткую логику** с шагом 0.25. Промежуточные значения (0.1, 0.3 и т.д.) допустимы для пограничных случаев.

### Dimension 1: Task Solution Quality (`task_quality`)

Насколько точно и полно код агента решает поставленную задачу.

| Score | Критерий |
|-------|---------|
| **0.00** | Изменений нет; или изменения разрушают существующий код; или агент объяснил решение словами без кода |
| **0.25** | Подход узнаваем, но фундаментальные ошибки не позволяют коду работать (неверная сигнатура, отсутствующий import, wrong assertion type) |
| **0.50** | Частичное решение: структура верна, но критические детали отсутствуют (нет assertions, неверное имя функции/метода, отсутствует `async` для async-теста) |
| **0.75** | Почти готовое решение: код работает, но не покрывает edge cases или содержит незначительную логическую ошибку |
| **1.00** | Полное, корректное решение: все требования выполнены, тест/код работает как ожидается |

### Dimension 2: Context Retrieval Quality (`context_quality`)

Насколько эффективно агент нашёл нужный контекст в кодовой базе — без лишних чтений и без пропуска ключевого кода.

| Score | Критерий |
|-------|---------|
| **0.00** | Агент не читал кодовую базу; написал код из предположений/галлюцинаций; структура не соответствует проекту |
| **0.25** | Читал файлы, но большинство нерелевантны; пропустил ключевой файл с функцией/классом для тестирования |
| **0.50** | Нашёл целевой код, но с избыточными чтениями (>2x лишних файлов) или пропустил важный контекст (fixtures, helpers) |
| **0.75** | Хорошее использование контекста, незначительная неэффективность (1 лишний файл или 1 пропущенный вспомогательный элемент) |
| **1.00** | Оптимально: нашёл точно нужные файлы с минимальным количеством чтений, весь релевантный контекст учтён |

### Dimension 3: Tool Usage Quality (`tool_quality`)

Насколько правильно и по назначению агент использовал prescribed tools конфигурации.

| Score | Критерий |
|-------|---------|
| **0.00** | Prescribed tools полностью проигнорированы; использовались только базовые read/write без поиска |
| **0.25** | Попытка использовать prescribed tools, но без смысла (пустые запросы, игнорирование результатов, сразу отказ от tool) |
| **0.50** | Prescribed tool использован, но с ошибками (неправильный запрос) или не все prescribed tools задействованы при наличии задач для каждого |
| **0.75** | Правильное использование prescribed tools с незначительной избыточностью или одним пропущенным оптимальным вызовом |
| **1.00** | Все prescribed tools использованы корректно, в правильной последовательности, запросы точны и результативны |

---

## Errors Found and Fixes Applied

### Error 1: `.eval_venv` на NTFS — packages не устанавливались

**Симптом:** Все конфиги показывали `tests_passed=0`, `outcome=failed`. Pytest падал с `ModuleNotFoundError: No module named 'streamlit'` во время коллекции.

**Причина:** `_run_cmd()` создавал `UV_PROJECT_ENVIRONMENT = os.path.join(worktree_path, ".eval_venv")`. Worktree находится на `/mnt/c/...` (NTFS mount в WSL). `uv` не может создавать hardlinks через файловые системы, поэтому пакеты не устанавливались корректно. `streamlit` (основная зависимость целевого проекта `process_metrics_platform_v2`) не попадал в venv.

**Дополнительный фактор:** `_is_env_error()` проверяет только `stderr`, но pytest выводит ошибки коллекции в `stdout`. `ModuleNotFoundError` в stdout не распознавался как `env_error` → `outcome="failed"` вместо `"env_error"`.

**Фикс:** `_eval_venv_path()` теперь возвращает `~/.eval_venvs/{md5_hash[:12]}` — путь на native Linux fs (`/home/artem/.eval_venvs/`). Uv создаёт там venv без проблем с hardlinks.

**Файл:** `src/features/execution_validator.py`  
**Коммит:** `2039b0a fix: move eval venv to native Linux fs and fix timeout hang`

---

### Error 2: `subprocess.run(timeout=X)` — pipe hang на 10+ часов

**Симптом:** Config 07 (grep) выполнялся 607 минут вместо ~4 минут.

**Причина:** `subprocess.run(shell=True, capture_output=True, timeout=1200)` при истечении timeout убивает только прямой дочерний процесс (shell). Внуки (`uv` → `pytest`) остаются живыми и держат pipe file descriptors открытыми. Python в `subprocess.run()` бесконечно ждёт EOF на этих pipes.

**Фикс:** Переход на `subprocess.Popen` с `preexec_fn=os.setsid` (новая process group). При timeout: `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` убивает всю group. Timeout теперь возвращает `outcome="env_error"` вместо `outcome="failed"`.

**Файл:** `src/features/execution_validator.py`  
**Коммит:** `2039b0a fix: move eval venv to native Linux fs and fix timeout hang`

---

### Error 3: Process кешировал старый модуль — фикс не применился к текущему прогону

**Симптом:** Фикс #1 и #2 были записаны на диск в 08:35, но benchmark process стартовал в 07:29 и уже закешировал старый `execution_validator` в `sys.modules`. Весь прогон прошёл со старым кодом.

**Причина:** Python caches module imports at startup. File-system changes don't affect running processes.

**Решение:** Следующий прогон (PID 760, стартовал в 09:17) использует исправленный код.

---

### Error 4: `03_gemini_like` — token runaway (371K токенов)

**Симптом:** Config 03 использовал 371,381 токенов — в 100 раз больше медианы. Агент не мог остановиться.

**Причина:** Конфигурация `gemini_like` предусматривает тяжёлый контекст (много инструментов, большой system prompt). Агент вошёл в loop чтения файлов без прогресса к решению. `CostGuard` сработал только по бюджету (`$0.15`), а не по количеству итераций.

**Статус:** Не исправлено. Требует `max_iterations` guard в agent loop.

---

### Error 5: `12_tree_sitter` — агент не сделал изменений (not_verified, made=False)

**Симптом:** Config завершился за 0.2 минуты, агент не записал ни одного файла.

**Причина:** Tree-sitter tool либо вернул ошибку на первом вызове, либо agent не смог разобрать результат и решил не делать изменений. Сам tree-sitter tool требует предварительно скомпилированных грамматических файлов (`.so`/`.dll`), которые не проверяются в pre-flight.

**Статус:** Частично решено — doctor check проверяет наличие `ast-grep`, но не проверяет Python tree-sitter grammar compilation.

---

## Requirements for Eval Expansion

### 1. Add `context_quality_score` Dimension

**Файлы:** `src/features/llm_judge.py`, `src/core/models.py`

```
Добавить третий LLM-судья вызов: _judge_context_quality()
Промпт: показать агенту список tool_calls (read/search операции),
        цель задачи, и спросить: насколько эффективно агент нашёл нужный контекст.
Шкала 0/0.25/0.5/0.75/1.0 с описанием из рубрики выше.
Добавить context_quality_score и context_quality_reasoning в JudgeReport и RunMetrics.
```

### 2. Fix `_is_env_error()` to Check stdout

**Файл:** `src/features/execution_validator.py`

```
Добавить отдельный список _ENV_ERROR_PATTERNS_STDOUT с паттернами:
  r"ModuleNotFoundError", r"No module named", r"ImportError"
Проверять их только в stdout (не смешивать со stderr-паттернами чтобы не ловить
ложные срабатывания из build output).
```

### 3. Add `max_iterations` Guard to Agent Loop

**Файл:** `src/features/agent_integration/agno_runner.py` (или BenchmarkMeta)

```
Добавить max_iterations: int = 15 в BenchmarkMeta.
AgnoRunner должен прерывать loop при достижении лимита с outcome="env_error" 
(не штрафовать агента за наш бесконечный loop).
```

### 4. WSL Setup Pipeline: Pre-flight for LSP, Semble, Tree-sitter

**Файл:** `scripts/setup_tools/setup_ast_lsp.sh`

```
Tree-sitter (Python bindings):
  - uv add tree-sitter tree-sitter-python (или pip install)
  - Проверить что: python -c "import tree_sitter; from tree_sitter import Language" выполняется
  - Скомпилировать Python grammar: Language.build_library('build/my-languages.so', ['tree-sitter-python'])
  - Проверить наличие .so файла

LSP (jedi):  
  - Убедиться что jedi >= 0.19 установлен в .venv-wsl
  - Smoke test: python -c "import jedi; s = jedi.Script('import os\nos.path.'); print(s.complete(2, 15)[0].name)"
  - Проверить что jedi.Script работает на реальном Python файле из target repo
```

**Файл:** `scripts/setup_tools/setup_serena_semble.sh`

```
Semble pre-warm:
  - Запустить uvx semble --help или uvx --from semble semble --version
  - Если пакет не скачан — скачать явно: uv tool install semble
  - Doctor check должен ждать download, а не timeout немедленно
  - Добавить SEMBLE_WARMUP_DONE flag чтобы не тратить время каждый раз
```

### 5. Target Repo Pre-Setup Before Clean Run

**Файл:** `main.py` или `src/features/benchmark_runner.py`

```
Перед запуском baseline measurement:
  1. Проверить что target repo путь существует
  2. Запустить: cd {target_repo} && uv sync --extra dev
  3. Проверить import основных модулей: python -c "import app" (или эквивалент)
     Допустимо: EnvironmentError из-за missing .env — главное что код парсится
  4. Запустить: python -m py_compile на ключевых .py файлах target repo
  5. Если uv sync падает — abort с понятной ошибкой, не запускать benchmark
```

### 6. Benchmark Validity Guard

**Файл:** `src/features/benchmark_runner.py`

```
Если baseline pass count = 0 — не запускать конфиги, abort с ошибкой:
  "Baseline measurement returned 0 tests. Target repo may be misconfigured."
Это предотвратит будущие прогоны с невалидным baseline.
```

---

## Infrastructure Changes Made This Session

| Change | File | Commit |
|--------|------|--------|
| eval venv moved to Linux native fs (`~/.eval_venvs/{hash}`) | `execution_validator.py` | `2039b0a` |
| subprocess.run → Popen+setsid+killpg (timeout hang fix) | `execution_validator.py` | `2039b0a` |
| Timeout outcome changed `"failed"` → `"env_error"` | `execution_validator.py` | `2039b0a` |
| `--project` flag injected into `uv run` for NTFS worktrees | `execution_validator.py` | `a408d8f` |
| Stdout logging added to validation commands | `execution_validator.py` | `a408d8f` |

---

## Next Clean Run

**PID:** 760  
**Started:** 2026-05-27 09:17  
**Status:** Running — baseline measurement in progress  
**Expected:** All configs should show `outcome=passed` for agents that write correct tests

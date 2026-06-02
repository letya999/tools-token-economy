# Tools Token Economy Benchmark

**Какой набор инструментов позволяет агенту решить задачу с минимальными затратами токенов?**

Бенчмарк запускает 21 конфигурацию инструментов на одной и той же задаче и замеряет успешность, стоимость, эффективность (SPT) и 7 качественных измерений от LLM-судьи. Все конфиги используют одну модель (`gpt-4.1-mini`) и одну задачу — меняется только набор инструментов.

## Результаты — Хард задача, 2026-06-01

**21 конфиг × 6 повторений = 126 прогонов.** Задача: добавить флаг `is_stale` в Polars-пайплайн расчёта возраста рабочих элементов. 3 файла, строгая схема. Общая стоимость: $15.16.

> **Метаданные:** n=6 · модель=gpt-4.1-mini · задача=hard (aging_stale) · 2026-06-01
> Судья: gpt-5.4-nano. Отсортировано по среднему judge score за 6 повторений.

| Конфиг | Инструменты | Pass | Judge | Avg токенов | Заметки |
|---|---|---|---|---|---|
| **04_codex_like** | grep+read+edit | **6/6** | **0.85** | 861K | высокое качество, дорого |
| **20_serena_semble** | serena+semble | 5/6 | **0.79** | 120K | ⭐ лучший баланс |
| 14_repo_map | repo_map+edit | 4/6 | 0.76 | 97K | хорошо |
| **16_serena_only** | serena | **6/6** | 0.68 | **79K** | ⭐ чемпион по токенам |
| 17_semble_only | semble | 5/6 | 0.58 | 84K | |
| 10_ugrep | ugrep+edit | 4/6 | 0.62 | 1 224K | очень дорого |
| 18_rg_repo_map | rg+repo_map | 0/6 | 0.49 | 79K | 0 pass, но judge≠0 |
| 19_rg_lsp | rg+lsp | 4/6 | 0.37 | 425K | pass≠качество |
| 03_gemini_like | read_all+repo_map | **0/6** | **0.00** | 419K | полный провал |
| 21_bash_only | bash | 0/6 | 0.10 | 85K | не может редактировать код |

**Ключевые выводы:**
- `serena_only` — **чемпион по эффективности**: 100% pass при всего 79K токенов (в 11 раз меньше, чем codex_like при том же pass rate)
- `serena_semble` — лучший баланс качества и стоимости: judge=0.79 при 120K токенов
- `rg_lsp` и `git_grep`: 67% pass, но judge всего 0.37 — прошли тесты «по случайности», задача не решена
- `rg_repo_map`: 0% pass, но judge=0.49 — правильный подход, провал на выполнении
- `gemini_like`: 0% pass, judge=0.00, 419K токенов — агент зациклился на чтении и не сделал ни одного изменения

## Результаты — Средняя задача, 2026-05-25

**20 конфигов, 1 повторение.** Задача: исправить регистронезависимую проверку Bearer-токена.
14/20 прошли (70%). Отсортировано по эффективности (меньше токенов = лучше).

| Конфиг | Инструменты | Токены | Цена $ | Pass | Заметки |
|---|---|---|---|---|---|
| **10_ugrep** | ugrep + edit | **2 697** | **$0.0018** | ✓ | самый эффективный |
| **18_rg_repo_map** | rg + repo_map | 3 003 | $0.0020 | ✓ | |
| **07_grep** | grep + edit | 3 439 | $0.0022 | ✓ | |
| **05_read_only** | glob + read | 3 276 | $0.0021 | ✓ | |
| **02_claude_code_like** | glob + rg + edit | 3 559 | $0.0022 | ✓ | |
| 08_git_grep | git_grep + edit | 4 576 | $0.0027 | ✓ | |
| 13_lsp | lsp + edit | 9,994 | $0.0077 | ✓ | |
| 14_repo_map | repo_map + edit | 11,087 | $0.0065 | ✓ | |
| 12_tree_sitter | tree_sitter + edit | 13,469 | $0.0074 | ✓ | |
| 20_serena_semble | serena+semble | 32,747 | $0.0188 | ✓ | |
| 03_gemini_like | read_all+repo_map | 175,208 | $0.1015 | ✗ | взрыв контекста |

**Главный вывод:** на средних задачах выигрывают лёгкие grep-инструменты. На сложных задачах — семантические (serena). Сложность задачи — ключевой дифференциатор.

---

## Скриншоты дашборда

| Лидерборд | Config Explorer |
|---|---|
| ![leaderboard](docs/screenshots/01_leaderboard.png) | ![explorer](docs/screenshots/03_config_explorer.png) |

| Графики | Deep Dive |
|---|---|
| ![charts](docs/screenshots/02_charts.png) | ![deepdive](docs/screenshots/05_deep_dive.png) |

| Информация о прогоне | Все метрики |
|---|---|
| ![runinfo](docs/screenshots/04_run_info.png) | ![allmetrics](docs/screenshots/06_all_metrics.png) |

---

## Что измеряется

Каждый прогон фиксирует:

- **success** — прошёл ли патч агента все тесты?
- **eval\_score** — составной балл (success × оценки судьи × штрафы за неэффективность)
- **SPT** — `success / (total_tokens / 1000)` — главная метрика эффективности
- **Waste%** — доля токенов контекста, которые были прочитаны, но не вошли в финальный патч
- **TTT** — time-to-target: сколько циклов до первого обращения к нужному файлу
- **7 измерений от LLM-судьи**: task\_solved, correctness, tool\_correctness, context\_quality, minimality, pattern\_adherence, tool\_sequence

Бенчмарк использует реальный Go-репозиторий ([process\_metrics\_platform\_v2](https://github.com/letya999/process_metrics_platform_v2)) и реальную задачу: исправить баг с регистрозависимым префиксом Bearer-токена. Агент должен найти нужную функцию, исправить её и добавить регрессионный тест — всё проверяется через `pytest`.

---

## Быстрый старт

### 1. Клонировать репозиторий
```bash
git clone https://github.com/letya999/tools-token-economy
cd tools-token-economy
```

### 2. Настроить окружение
```bash
cp .env.example .env  # добавить OPENAI_API_KEY
```

### 3. Настройка (проверки окружения, установка зависимостей, пробный запуск)
```bash
wsl bash -c "cd /mnt/c/path/to/tools-token-economy && uv run python main.py --setup"
```
Ожидаемый результат: каждый этап печатает `[PASS]`.

### 4. Запустить бенчмарк
```bash
wsl bash -c "cd /mnt/c/path/to/tools-token-economy && uv run python main.py"
```
Результаты: `results/run_TIMESTAMP_*/metrics.json`

### 5. Открыть дашборд
```bash
# Windows (рекомендуется)
python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501

# или через uv в WSL
uv run streamlit run streamlit_app.py --server.address 0.0.0.0
```
Открывается на `http://localhost:8501` — 8 вкладок, переключение языка EN/RU в сайдбаре.

---

## Вкладки дашборда

| Вкладка | Что показывает |
|---|---|
| **Leaderboard** | Рейтинговая таблица: Pass · Eval · Tokens · Cost · SPT · TTT · Waste% · Cycles |
| **Config Explorer** | Раскрывающиеся карточки на каждый конфиг: оценки + reasoning судьи + diff патча + таймлайн |
| **Charts** | Бар-чарт (любая метрика × конфиги) + Radar (до 5 конфигов × 12 измерений) |
| **Run Info** | Модель, описание задачи, данные о кодовой базе, все 21 конфиг |
| **Weights** | Визуальная разбивка весов eval и составных метрик |
| **Glossary** | Поиск по определениям всех 35 метрик и измерений оценки |
| **Config Deep Dive** | Radar vs медиана + полный reasoning судьи + diff + пошаговый таймлайн |
| **All Metrics** | Все поля RunMetrics по всем конфигам, сортировка + статистический срез |

---

## Конфигурации инструментов

21 конфигурация в 6 архетипах:

| Архетип | Конфиги | Философия |
|---|---|---|
| **cursor** | 01 | Repo map + RAG для широкого контекста |
| **claude** | 02 | Glob + ripgrep для точечного поиска |
| **gemini** | 03 | Read all + rg (сначала весь контекст) |
| **codex** | 04 | Grep + read (классический Unix) |
| **ablation** | 05–15 | По одному инструменту поиска (glob, read\_all, grep, git\_grep, rg, ugrep, ast\_grep, tree\_sitter, LSP symbols, repo\_map, simple\_RAG) |
| **semantic** | 16–17 | Serena MCP / Semble MCP (семантическое понимание кода) |
| **hybrid** | 18–20 | Комбинации (rg+repo\_map, rg+LSP, Serena+Semble) |
| **minimal** | 21 | Только bash — без специализированных инструментов |

---

## Прочие команды

| Команда | Описание |
|---|---|
| `python main.py --dry-run` | Проверить загрузку всех 21 конфига (без API-вызовов) |
| `python main.py --config-ids 02_claude_code_like` | Запустить один конфиг |
| `python main.py --config-ids 02,08,13` | Запустить конкретные конфиги |
| `python main.py --retry-failed` | Перезапустить упавшие конфиги в ту же папку результатов |
| `python main.py --runs 5` | Мульти-прогон (p75 агрегация для статистической устойчивости) |
| `python main.py --doctor` | Проверка инфраструктуры |
| `python main.py --dashboard` | Сгенерировать статичный HTML-дашборд (без сервера) |

---

## Архитектура

```
src/
  core/           # Модели данных (RunMetrics, BenchmarkMeta, AgentConfig), загрузчик конфигов
  features/       # Изоляция, LLM-судья, preflight, реестр инструментов, агрегатор метрик
  orchestrator/   # BenchmarkOrchestrator — связывает всё вместе
configs/
  provider.yaml         # Настройки провайдера (модель, max_steps, температура)
  tools.yaml            # 21 стратегия инструментов
  tasks/medium.yaml     # Описание задачи (description, test_cmd, required_files)
  codebase.yaml         # Конфиг целевого репозитория
  benchmark_weights.yaml # Веса для составных метрик
streamlit_app.py   # Интерактивный дашборд с 8 вкладками
results/           # Результаты: metrics.json, agent_messages.json, final.patch
tests/             # Unit-тесты (pytest)
```

Подробности архитектуры — в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), инструкции для AI-агентов — в [`AGENTS.md`](AGENTS.md).

---

## Требования

- Python 3.13+, `uv`
- WSL2 Ubuntu (выполнение агента — в WSL)
- `rg` (ripgrep): `sudo apt install ripgrep`
- `OPENAI_API_KEY` в `.env`

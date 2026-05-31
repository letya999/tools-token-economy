# Benchmark Setup: Full Guarantee Protocol

Этот документ описывает полную архитектуру подготовки окружения перед запуском бенчмарка.
Принцип: **ни один шаг не начинается пока предыдущий не прошёл полностью**.

---

## Структура скриптов

```
scripts/
  checks/                    # Проверки — каждый возвращает 0 (OK) или 1 (NOT OK)
    check_git.sh
    check_grep.sh
    check_rg.sh
    check_ugrep.sh
    check_astgrep.sh
    check_uv.sh              # нужен для uvx (semble)
    check_serena.sh          # проверяет бинарь serena в venv
    check_semble.sh          # проверяет uvx + semble[mcp] доступен
    check_python_deps.sh     # qdrant-client, fastembed, jedi, tree-sitter, serena-agent
  install/                   # Установка — отдельный скрипт на каждый инструмент
    install_git.sh
    install_rg.sh
    install_ugrep.sh
    install_astgrep.sh       # скачивает binary с GitHub releases
    install_uv.sh            # curl | sh astral.sh/uv
    install_serena.sh        # pip install serena-agent в .venv-wsl
    install_semble.sh        # uv tool install semble + uvx preload
    install_python_deps.sh   # uv sync (подтягивает pyproject.toml)
  verify/                    # Верификация через Python — Agno реально видит инструменты
    verify_serena_mcp.py
    verify_semble_mcp.py
    verify_basic_tools.py    # read, write, patch, glob smoke tests
    verify_grep_tools.py     # grep, rg, ugrep, ast-grep smoke tests
    verify_rag_tool.py       # SimpleRagTool (Qdrant + fastembed) smoke test
  setup_benchmark.sh         # ГЛАВНЫЙ оркестратор всей подготовки
```

---

## Главный оркестратор: `scripts/setup_benchmark.sh`

```
ФАЗА 1: Проверка и установка каждого инструмента (check → install → recheck)
ФАЗА 2: Python-level верификация (imports, smoke tests)
ФАЗА 3: MCP-серверная верификация (старт процесса + Agno видит инструменты)
```

Каждый шаг использует паттерн **check → install if failed → recheck → abort if still failed**:

```bash
check_and_install() {
    local CHECK=$1 INSTALL=$2 TOOL=$3
    bash "$CHECK" && { echo "[OK] $TOOL"; return 0; }
    echo "[MISSING] $TOOL — running install..."
    bash "$INSTALL"
    bash "$CHECK" && { echo "[OK] $TOOL installed"; return 0; }
    echo "[FATAL] $TOOL failed after install. Aborting." >&2
    exit 1
}
```

Если recheck упал → `exit 1` → `set -e` останавливает всё. Бенчмарк не стартует.

---

## ФАЗА 1: Проверка + Установка CLI-инструментов

### Порядок проверок (важен — зависимости между инструментами)

```
1. git          — нужен для изоляции worktree
2. uv/uvx       — нужен для semble и uv sync
3. rg            — ripgrep
4. ugrep         — ugrep
5. ast-grep      — бинарь ast-grep (не через pip)
6. grep          — системный grep (обычно есть)
7. serena        — бинарь serena в venv (pip install serena-agent)
8. semble        — uvx --from "semble[mcp]" semble
9. python-deps   — qdrant-client, fastembed, jedi, tree-sitter, serena-agent (import check)
```

### `scripts/checks/check_git.sh`
```bash
#!/bin/bash
command -v git &>/dev/null
```

### `scripts/checks/check_uv.sh`
```bash
#!/bin/bash
command -v uv &>/dev/null && command -v uvx &>/dev/null
```

### `scripts/checks/check_rg.sh`
```bash
#!/bin/bash
command -v rg &>/dev/null && rg --version &>/dev/null
```

### `scripts/checks/check_ugrep.sh`
```bash
#!/bin/bash
command -v ugrep &>/dev/null
```

### `scripts/checks/check_astgrep.sh`
```bash
#!/bin/bash
command -v ast-grep &>/dev/null && ast-grep --version &>/dev/null
```

### `scripts/checks/check_serena.sh`
```bash
#!/bin/bash
# Ищем в venv-wsl/bin или в PATH
SERENA=$(command -v serena 2>/dev/null || echo "")
[ -n "$SERENA" ] && serena --help &>/dev/null
```

### `scripts/checks/check_semble.sh`
```bash
#!/bin/bash
# Проверяем что uvx может запустить semble[mcp]
command -v uvx &>/dev/null || exit 1
uvx --from "semble[mcp]" semble --help &>/dev/null
```

### `scripts/checks/check_python_deps.sh`
```bash
#!/bin/bash
PYTHON="${VENV_PYTHON:-python3}"
$PYTHON -c "
import importlib.util, sys
REQUIRED = ['qdrant_client', 'fastembed', 'jedi', 'tree_sitter', 'serena']
missing = [p for p in REQUIRED if importlib.util.find_spec(p) is None]
if missing:
    print('Missing packages:', missing, file=sys.stderr)
    sys.exit(1)
"
```

---

### Install Scripts

### `scripts/install/install_git.sh`
```bash
#!/bin/bash
sudo apt-get update -y && sudo apt-get install -y git
```

### `scripts/install/install_uv.sh`
```bash
#!/bin/bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

### `scripts/install/install_rg.sh`
```bash
#!/bin/bash
sudo apt-get install -y ripgrep
```

### `scripts/install/install_ugrep.sh`
```bash
#!/bin/bash
# Пробуем apt, потом deb-пакет с GitHub
sudo apt-get install -y ugrep 2>/dev/null && exit 0
UGREP_VER="7.3.2"
wget -q "https://github.com/Genivia/ugrep/releases/download/v${UGREP_VER}/ugrep_${UGREP_VER}_amd64.deb" -O /tmp/ugrep.deb
sudo dpkg -i /tmp/ugrep.deb && rm /tmp/ugrep.deb
```

### `scripts/install/install_astgrep.sh`
```bash
#!/bin/bash
# Скачать binary с GitHub releases (содержит оба: ast-grep и sg)
LATEST=$(curl -sL https://api.github.com/repos/ast-grep/ast-grep/releases/latest \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
curl -sL "https://github.com/ast-grep/ast-grep/releases/download/${LATEST}/app-x86_64-unknown-linux-gnu.zip" \
  -o /tmp/ast-grep.zip
python3 -c "import zipfile; zipfile.ZipFile('/tmp/ast-grep.zip').extractall('/tmp/ast-grep-bin/')"
mkdir -p ~/.local/bin
cp /tmp/ast-grep-bin/ast-grep ~/.local/bin/ast-grep
cp /tmp/ast-grep-bin/sg ~/.local/bin/sg
chmod +x ~/.local/bin/ast-grep ~/.local/bin/sg
rm -rf /tmp/ast-grep.zip /tmp/ast-grep-bin
export PATH="$HOME/.local/bin:$PATH"
```

### `scripts/install/install_serena.sh`
```bash
#!/bin/bash
VENV_PYTHON="${VENV_PYTHON:-/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/python}"
$VENV_PYTHON -m pip install "serena-agent"
# serena бинарь окажется в .venv-wsl/bin/serena
```

### `scripts/install/install_semble.sh`
```bash
#!/bin/bash
# uv tool install — глобальная установка через uv (доступна через uvx)
uv tool install "semble[mcp]"
# Preload: первый запуск скачает модели
uvx --from "semble[mcp]" semble --help || true
```

### `scripts/install/install_python_deps.sh`
```bash
#!/bin/bash
# uv sync подтягивает всё из pyproject.toml (qdrant-client, fastembed, etc.)
export UV_LINK_MODE=copy
cd /mnt/c/Users/User/a_projects/tools_token_economy
uv sync --extra dev
```

---

## ФАЗА 2: Python-level верификация (smoke tests)

Запускаются после успешной ФАЗЫ 1. Используют реальные классы инструментов.

### `scripts/verify/verify_basic_tools.py`
Создаёт temp dir с temp py-файлом, затем:
- `FileReadTool(tmp).execute(file_path="test.py")` — ожидает непустой результат
- `FileWriteTool(tmp).execute(file_path="out.py", content="x=1")` — ожидает success
- `PatchApplierTool(tmp).execute(patch=valid_patch)` — ожидает success
- `GlobTool(tmp).execute(pattern="*.py")` — ожидает непустой список
- Любая ошибка → `sys.exit(1)`

### `scripts/verify/verify_grep_tools.py`
Создаёт temp git repo с py-файлом, затем:
- `GrepTool(tmp).execute(pattern="hello")` — ожидает match
- `RgTool(tmp).execute(pattern="hello")` — ожидает match
- `UgrepTool(tmp).execute(pattern="hello")` — ожидает match
- `AstGrepTool(tmp).execute(pattern="def $A(): ...")` — ожидает match или no matches (не Error)
- `GitGrepTool(tmp).execute(pattern="hello")` — ожидает match

### `scripts/verify/verify_rag_tool.py`
Создаёт temp dir с несколькими py-файлами, затем:
- `SimpleRagTool(tmp).execute(query="function definition")` — ожидает результат без Error
- Проверяет что Qdrant создал коллекцию и fastembed встроился

---

## ФАЗА 3: MCP-серверная верификация (Agno видит инструменты)

**Это самая важная фаза.** Здесь проверяется не просто что бинарь есть, а что:
1. MCP-сервер стартует (процесс жив)
2. Agno подключается к нему
3. Agno импортирует инструменты
4. Можно сделать тестовый вызов

### `scripts/verify/verify_serena_mcp.py`

```
Алгоритм:
1. Найти бинарь serena (venv bin или PATH)
2. Создать temp dir с минимальным Python-проектом (1 файл с функцией)
3. Создать StdioServerParameters(command=serena_bin, args=["start-mcp-server", "--project", tmp])
4. Запустить: async with MCPTools(server_params=params) as mcp_tools:
5. Проверить: len(mcp_tools.tools) > 0
6. Вывести список инструментов которые видит Agno
7. Сделать тестовый вызов find_symbol или search_symbol через agno tools
8. Закрыть (context manager сам убьёт процесс)
Выход: 0 = OK, 1 = FAIL с описанием
```

### `scripts/verify/verify_semble_mcp.py`

```
Алгоритм:
1. Проверить что uvx доступен
2. Создать temp dir с py-файлами
3. Создать StdioServerParameters(command="uvx", args=["--from", "semble[mcp]", "semble"])
4. Запустить: async with MCPTools(server_params=params) as mcp_tools:
5. Проверить: len(mcp_tools.tools) > 0 (ожидаем: search, find_related)
6. Вывести список инструментов которые видит Agno
7. Сделать тестовый вызов: search("function definition", tmp_path)
8. Закрыть
Выход: 0 = OK, 1 = FAIL с описанием
```

---

## Изменения кода

### `src/core/models.py`
Добавить:
```python
@dataclass
class McpServerConfig:
    tool_name: str
    command: str
    args_template: list[str]  # "{path}" заменяется на worktree_path при запуске

    def resolve_args(self, worktree_path: str) -> list[str]:
        return [a.replace("{path}", worktree_path) for a in self.args_template]
```

### `src/orchestrator/benchmark.py`
Добавить реестр MCP-инструментов и логику разделения:
```python
_MCP_TOOL_REGISTRY: dict[str, McpServerConfig] = {
    "serena": McpServerConfig("serena", "serena",
                              ["start-mcp-server", "--project", "{path}"]),
    "semble": McpServerConfig("semble", "uvx",
                              ["--from", "semble[mcp]", "semble"]),
    # Для semble путь не в args старта сервера —
    # он передаётся как аргумент в каждом tool call: search("query", "/path")
}
```

При создании AgnoRunner для каждого конфига:
- `regular_tools: list[BaseTool]` — все кроме serena/semble
- `mcp_configs: list[McpServerConfig]` — serena и/или semble

### `src/features/agent_integration/agno_runner.py`
Добавить параметр `mcp_configs: list[McpServerConfig] | None = None`.

Если `mcp_configs` не пуст — использовать async путь:
```python
import asyncio
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

async def _run_with_mcp(self, task, worktree_path, test_cmd, log_path):
    mcp_tool_instances = []
    context_managers = []

    for cfg in self.mcp_configs:
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.resolve_args(worktree_path)
        )
        # MCPTools используется как async context manager
        mcp_inst = MCPTools(server_params=params)
        context_managers.append(mcp_inst)

    # Вход во все context managers
    async with contextlib.AsyncExitStack() as stack:
        for cm in context_managers:
            loaded = await stack.enter_async_context(cm)
            mcp_tool_instances.append(loaded)

        # Agno agent с regular tools + MCP tools
        all_tools = self._build_agno_tools() + mcp_tool_instances
        agent = Agent(model=..., tools=all_tools, ...)
        response = await agent.arun(task)
        # ... остальная обработка метрик
```

Если `mcp_configs` пуст — использовать существующий синхронный путь (без изменений).

### `src/features/tool_registry/semantic_tools.py`
- **Удалить** `SerenaAdapterTool` и `SembleAdapterTool`
- **Исправить баг** в `SimpleRagTool.execute()` строка 120:
  ```python
  # БЫЛО (неправильно — обращение к приватному атрибуту):
  search_result = self._client._client.search(...)
  # СТАЛО:
  search_result = self._client.search(
      collection_name=self._collection_name,
      query_vector=query_vector,
      limit=top_k
  )
  ```

### `src/features/preflight.py`
- **Убрать** `if self.dry_run: return early` — preflight всегда полный
- **Обновить** `_TOOL_CLI_DEPS`:
  ```python
  "serena": "serena",   # critical
  "semble": "uvx",      # critical (проверяем uvx, не semble напрямую)
  "simple_rag": None,   # Python-only
  ```
- **Добавить** `_check_python_packages()` через `importlib.util.find_spec`:
  - `qdrant_client` — critical если simple_rag в конфиге
  - `fastembed` — critical если simple_rag в конфиге
  - `jedi` — critical если lsp_symbols в конфиге
  - `tree_sitter` — critical если tree_sitter в конфиге
- **Убрать** smoke-тест для MCP из preflight — они теперь в `scripts/verify/`

### `pyproject.toml`
Добавить:
```toml
"serena-agent>=0.1.0",
```
Убрать: `"rank-bm25>=0.2.2"` (заменён Qdrant+fastembed)

### `run_benchmark_wsl.sh`
```bash
#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy
VENV_PYTHON="/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/python"
export VENV_PYTHON
source /mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/activate
cd /mnt/c/Users/User/a_projects/tools_token_economy

echo "================================================================"
echo " BENCHMARK SETUP: check → install → verify → test → dry-run → run"
echo "================================================================"

# ФАЗА 1+2+3: Полная подготовка (check, install, verify)
bash scripts/setup_benchmark.sh

# ФАЗА 4: Тест-сьют самого бенчмарка
echo ""
echo "=== [4/5] Benchmark test suite ==="
$VENV_PYTHON -m pytest tests/ -q --tb=short

# ФАЗА 5: Dry-run preflight (полный, не урезанный)
echo ""
echo "=== [5/6] Full preflight dry-run ==="
$VENV_PYTHON main.py --dry-run

# ФАЗА 6: Бенчмарк
echo ""
echo "=== [6/6] Running benchmark ==="
exec $VENV_PYTHON main.py
```

### `scripts/setup_benchmark.sh` (полный)
```bash
#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

check_and_install() {
    local CHECK="$SCRIPT_DIR/checks/$1"
    local INSTALL="$SCRIPT_DIR/install/$2"
    local TOOL="$3"

    if bash "$CHECK" 2>/dev/null; then
        echo "  [OK] $TOOL"
        return 0
    fi

    echo "  [MISSING] $TOOL — installing..."
    bash "$INSTALL"

    if bash "$CHECK" 2>/dev/null; then
        echo "  [OK] $TOOL — installed successfully"
        return 0
    fi

    echo "  [FATAL] $TOOL — still missing after install. Check logs above." >&2
    exit 1
}

echo ""
echo "=== [1/3] CLI tool checks & installs ==="
check_and_install check_git.sh    install_git.sh    "git"
check_and_install check_uv.sh     install_uv.sh     "uv/uvx"
check_and_install check_rg.sh     install_rg.sh     "ripgrep (rg)"
check_and_install check_ugrep.sh  install_ugrep.sh  "ugrep"
check_and_install check_astgrep.sh install_astgrep.sh "ast-grep"
check_and_install check_serena.sh  install_serena.sh  "serena MCP server"
check_and_install check_semble.sh  install_semble.sh  "semble MCP server"
check_and_install check_python_deps.sh install_python_deps.sh "Python packages"

echo ""
echo "=== [2/3] Python-level smoke tests ==="
VENV_PYTHON="${VENV_PYTHON:-python3}"
$VENV_PYTHON scripts/verify/verify_basic_tools.py
$VENV_PYTHON scripts/verify/verify_grep_tools.py
$VENV_PYTHON scripts/verify/verify_rag_tool.py

echo ""
echo "=== [3/3] MCP server + Agno integration verification ==="
$VENV_PYTHON scripts/verify/verify_serena_mcp.py
$VENV_PYTHON scripts/verify/verify_semble_mcp.py

echo ""
echo "All checks passed. Environment is ready for benchmark."
```

---

## Итоговая цепочка выполнения

```
run_benchmark_wsl.sh
│
├─ setup_benchmark.sh
│  ├─ [1/3] CLI checks & installs
│  │  ├─ check_git.sh  →  (fail?) install_git.sh  →  recheck  →  (fail?) ABORT
│  │  ├─ check_uv.sh   →  (fail?) install_uv.sh   →  recheck  →  (fail?) ABORT
│  │  ├─ check_rg.sh   →  (fail?) install_rg.sh   →  recheck  →  (fail?) ABORT
│  │  ├─ check_ugrep.sh→  (fail?) install_ugrep.sh→  recheck  →  (fail?) ABORT
│  │  ├─ check_astgrep.sh → (fail?) install_astgrep.sh → recheck → (fail?) ABORT
│  │  ├─ check_serena.sh  → (fail?) install_serena.sh  → recheck → (fail?) ABORT
│  │  ├─ check_semble.sh  → (fail?) install_semble.sh  → recheck → (fail?) ABORT
│  │  └─ check_python_deps.sh → (fail?) install_python_deps.sh → recheck → ABORT
│  │
│  ├─ [2/3] Python smoke tests
│  │  ├─ verify_basic_tools.py   →  (fail?) ABORT
│  │  ├─ verify_grep_tools.py    →  (fail?) ABORT
│  │  └─ verify_rag_tool.py      →  (fail?) ABORT
│  │
│  └─ [3/3] Agno MCP verification
│     ├─ verify_serena_mcp.py    →  (fail?) ABORT
│     └─ verify_semble_mcp.py    →  (fail?) ABORT
│
├─ pytest tests/ -q              →  (fail?) ABORT
├─ python main.py --dry-run      →  (fail?) ABORT
└─ python main.py                ← только сюда если ВСЁ выше прошло
```

---

## Матрица гарантий

| Инструмент | Check | Install | Smoke test | Agno MCP verify |
|---|---|---|---|---|
| git | check_git.sh | install_git.sh | — | — |
| ripgrep | check_rg.sh | install_rg.sh | verify_grep_tools.py | — |
| ugrep | check_ugrep.sh | install_ugrep.sh | verify_grep_tools.py | — |
| ast-grep | check_astgrep.sh | install_astgrep.sh | verify_grep_tools.py | — |
| uv/uvx | check_uv.sh | install_uv.sh | — | — |
| serena | check_serena.sh | install_serena.sh | — | **verify_serena_mcp.py** |
| semble | check_semble.sh | install_semble.sh | — | **verify_semble_mcp.py** |
| qdrant-client | check_python_deps.sh | install_python_deps.sh | verify_rag_tool.py | — |
| fastembed | check_python_deps.sh | install_python_deps.sh | verify_rag_tool.py | — |
| jedi (LSP) | check_python_deps.sh | install_python_deps.sh | verify_grep_tools.py | — |
| tree-sitter | check_python_deps.sh | install_python_deps.sh | verify_grep_tools.py | — |
| read/write/patch/glob | check_python_deps.sh | install_python_deps.sh | verify_basic_tools.py | — |

---

## Что означает "Agno видит и может вызвать"

Verify-скрипты для MCP делают именно это:

1. `StdioServerParameters(command=..., args=...)` — конфигурация запуска
2. `async with MCPTools(server_params=params) as mcp_tools:` — Agno сам стартует процесс MCP-сервера
3. `mcp_tools.tools` — список Agno-совместимых Function инструментов (должен быть > 0)
4. Тестовый вызов через агента — не просто "инструмент есть", а "вызов возвращает результат без ошибки"
5. Context manager выходит — Agno корректно закрывает stdio-процесс

Только если всё это прошло → бенчмарк стартует.

"""
OpenCode CLI subprocess wrapper.

Requires: npm install -g opencode (in WSL)
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import tiktoken

from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool
from src.features.rate_limiter import RateLimiter

_FALLBACK_MODELS = ["opencode/big-pickle", "opencode/deepseek-v4-flash-free"]
_MAX_QUOTA_RETRIES = 3
_log = logging.getLogger(__name__)


def _resolve_opencode_exe() -> str:
    """Find the opencode executable, preferring the direct .exe over a .cmd wrapper on Windows."""
    cmd_path = shutil.which("opencode")
    if sys.platform == "win32" and cmd_path and cmd_path.lower().endswith(".cmd"):
        # npm .CMD wrapper: C:\<prefix>\opencode.CMD -> C:\<prefix>\node_modules\opencode-ai\bin\opencode.exe
        exe = os.path.join(os.path.dirname(cmd_path), "node_modules", "opencode-ai", "bin", "opencode.exe")
        if os.path.exists(exe):
            return exe
    return cmd_path or "opencode"


def _win_to_wsl_path(win_path: str) -> str:
    """Convert C:\\foo\\bar to /mnt/c/foo/bar for WSL access."""
    m = re.match(r'^([A-Za-z])[:/\\](.*)', win_path.replace("\\", "/"))
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return win_path


class OpenCodeRunner:
    """
    Runs OpenCode CLI as a subprocess and collects metrics from its JSONL output.
    In mock/dry-run mode, skips the CLI entirely.
    """

    def __init__(self, config: AgentConfig, tools: list[Tool], mock: bool = False, timeout_sec: int = 600):
        self.config = config
        self.tools = tools
        self.mock = mock
        self.timeout_sec = timeout_sec
        # Use cl100k_base as a general approximation for token counting fallback
        try:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._tokenizer = None
        self._rate_limiter = RateLimiter(requests_per_minute=10)

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # Very rough approximation if tiktoken fails: ~4 chars per token
        return len(text) // 4

    def _model_flag(self) -> str:
        """Convert model name to opencode provider/model format."""
        model = self.config.model
        if "/" in model:
            return model
        if model.startswith("gemini-"):
            return f"google/{model}"
        if model.startswith("claude-"):
            return f"anthropic/{model}"
        if model.startswith("gpt-"):
            return f"openai/{model}"
        return model

    def _check_api_keys(self):
        """Verify required API keys are present in environment."""
        if self.mock:
            return

        model = self._model_flag()
        if "google/" in model:
            if not any(os.getenv(k) for k in ["GOOGLE_API_KEY", "GEMINI_API_KEY"]):
                raise EnvironmentError(
                    "GOOGLE_API_KEY not set. Set it with: export GOOGLE_API_KEY=your-key"
                )
        elif "openai/" in model and not os.getenv("OPENAI_API_KEY"):
            raise ValueError(f"Model {model} requires OPENAI_API_KEY.")
        elif "anthropic/" in model and not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError(f"Model {model} requires ANTHROPIC_API_KEY.")
        elif "openrouter/" in model and not os.getenv("OPENROUTER_API_KEY"):
            raise ValueError(f"Model {model} requires OPENROUTER_API_KEY.")

    def _parse_metrics(self, stdout: str) -> dict[str, Any]:
        """Parse JSONL output to extract usage and tool metrics."""
        m = {
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "model_calls": 0, "tool_calls": 0, "files_read": 0,
            "files_changed": 0, "patch_lines": 0, "errors": 0
        }

        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                etype = event.get("type", "")

                if etype == "step_finish":
                    usage = event.get("usage", {})
                    m["input_tokens"] += usage.get("inputTokens", usage.get("input_tokens", 0))
                    m["output_tokens"] += usage.get("outputTokens", usage.get("output_tokens", 0))
                    m["model_calls"] += 1

                elif etype == "tool_use":
                    m["tool_calls"] += 1
                    part = event.get("part", {})
                    tool_name = part.get("name", part.get("tool", ""))
                    tool_output = str(part.get("output", ""))
                    m["tool_tokens"] += self._count_tokens(tool_output)

                    if tool_name in {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}:
                        m["files_read"] += 1
                    elif tool_name in {"patch", "write"}:
                        m["files_changed"] += 1
                        m["patch_lines"] += tool_output.count("\n")

                elif etype == "error":
                    m["errors"] += 1

            except json.JSONDecodeError:
                m["tool_tokens"] += self._count_tokens(line)
        return m

    def _probe_quota(self) -> tuple[bool, float]:
        """Check Google generateContent quota. Returns (quota_ok, retry_after_seconds).
        Probes the generateContent endpoint directly — /v1beta/models has a separate
        quota bucket and always returns 200 even when generateContent is 429."""
        if "google/" not in self._model_flag():
            return True, 0.0
        api_key = (
            os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        if not api_key:
            return True, 0.0
        # Extract bare model name from e.g. "google/gemini-2.5-flash" → "gemini-2.5-flash"
        model_id = self._model_flag().split("/", 1)[-1]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_id}:generateContent?key={api_key}"
        )
        body = json.dumps({"contents": [{"parts": [{"text": "hi"}]}]}).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            return True, 0.0
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                resp_body = exc.read().decode(errors="ignore")
                m = re.search(r"retry in ([\d.]+)s", resp_body)
                wait = float(m.group(1)) + 5.0 if m else 65.0
                return False, wait
            # 400 (bad request format) or other non-quota errors → assume quota ok
            return True, 0.0
        except Exception:
            return True, 0.0

    def _run_with_model(
        self, model_flag: str, task_description: str, worktree_path: str
    ) -> subprocess.CompletedProcess:
        """Run opencode via WSL on Windows, or directly on Linux/Mac."""
        abs_path = os.path.abspath(worktree_path)

        if sys.platform == "win32":
            # Run opencode inside WSL so it can use native Linux tools (rg, bash, etc.)
            wsl_dir = _win_to_wsl_path(abs_path)
            # Escape single-quotes in task_description for bash -c '...'
            safe_task = task_description.replace("'", "'\\''")
            # Source nvm so nvm-managed node/opencode are active; also add
            # ~/.local/bin (uv, rg, etc.) to PATH
            bash_cmd = (
                'export NVM_DIR="$HOME/.nvm" && '
                '. "$NVM_DIR/nvm.sh" 2>/dev/null; '
                'export PATH="$HOME/.local/bin:$PATH" && '
                f"cd '{wsl_dir}' && "
                f"opencode run --format json --dir '{wsl_dir}' "
                f"--model '{model_flag}' "
                f"--dangerously-skip-permissions '{safe_task}'"
            )
            cmd = ["wsl", "bash", "-c", bash_cmd]
        else:
            cmd = [
                _resolve_opencode_exe(),
                "run", "--format", "json",
                "--dir", abs_path,
                "--model", model_flag,
                "--dangerously-skip-permissions", task_description,
            ]

        return subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=self.timeout_sec, check=False,
            cwd=abs_path,
        )

    def run(self, task_description: str, worktree_path: str = ".") -> RunMetrics:
        """Execute task via OpenCode CLI with quota-retry and free-model fallback."""
        self._check_api_keys()
        start_time = time.time()

        if self.mock:
            return self._run_mock(task_description, start_time)

        model_flag = self._model_flag()
        result = None

        with self._rate_limiter:
            # Fallback 1: retry after quota reset (up to _MAX_QUOTA_RETRIES times)
            for attempt in range(_MAX_QUOTA_RETRIES + 1):
                quota_ok, wait_sec = self._probe_quota()
                if quota_ok:
                    break
                if attempt < _MAX_QUOTA_RETRIES:
                    _log.warning(
                        "Quota exhausted for %s, waiting %.0fs (retry %d/%d)",
                        model_flag, wait_sec, attempt + 1, _MAX_QUOTA_RETRIES,
                    )
                    time.sleep(wait_sec)
                else:
                    # Fallback 2: switch to free opencode-hosted model
                    model_flag = _FALLBACK_MODELS[0]
                    _log.warning(
                        "Quota retries exhausted, falling back to free model: %s", model_flag,
                    )

            result = self._run_with_model(model_flag, task_description, worktree_path)

        duration = time.time() - start_time
        m = self._parse_metrics(result.stdout)

        if m["input_tokens"] == 0 and m["output_tokens"] == 0:
            m["input_tokens"] = self._count_tokens(task_description)
            m["output_tokens"] = self._count_tokens(result.stdout)

        return RunMetrics(
            success=result.returncode == 0,
            eval_score=1.0 if result.returncode == 0 else 0.0,
            duration_sec=duration,
            model_name=model_flag,
            **m
        )

    def _run_mock(self, task_description: str, start_time: float) -> RunMetrics:
        sim_out = f"Task: {task_description}\nTASK_COMPLETE"
        return RunMetrics(
            success=True, eval_score=1.0,
            input_tokens=self._count_tokens(sim_out),
            output_tokens=self._count_tokens("TASK_COMPLETE"),
            tool_tokens=0, duration_sec=time.time() - start_time,
            model_calls=1, tool_calls=0, model_name=self.config.model
        )

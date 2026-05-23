"""
OpenCode CLI subprocess wrapper.

Requires: npm install -g opencode (in WSL)
"""
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

import tiktoken

from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool
from src.features.rate_limiter import RateLimiter


class OpenCodeRunner:
    """
    Runs OpenCode CLI as a subprocess and collects metrics from its JSONL output.
    In mock/dry-run mode, skips the CLI entirely.
    """

    def __init__(self, config: AgentConfig, tools: list[Tool], mock: bool = False):
        self.config = config
        self.tools = tools
        self.mock = mock
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

    def run(self, task_description: str, worktree_path: str = ".") -> RunMetrics:
        """Execute task via OpenCode CLI."""
        self._check_api_keys()
        start_time = time.time()

        if self.mock:
            return self._run_mock(task_description, start_time)

        with self._rate_limiter:
            opencode_cmd = shutil.which("opencode") or "opencode"
            run_args = [
                "run", "--format", "json",
                "--dir", os.path.abspath(worktree_path),
                "--model", self._model_flag(),
                "--dangerously-skip-permissions", task_description,
            ]
            # On Windows, .cmd/.ps1 scripts require cmd /c to execute via CreateProcess
            if sys.platform == "win32" and opencode_cmd.lower().endswith((".cmd", ".ps1")):
                cmd = ["cmd", "/c", opencode_cmd] + run_args
            else:
                cmd = [opencode_cmd] + run_args
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)

        duration = time.time() - start_time
        m = self._parse_metrics(result.stdout)

        if m["input_tokens"] == 0 and m["output_tokens"] == 0:
            m["input_tokens"] = self._count_tokens(task_description)
            m["output_tokens"] = self._count_tokens(result.stdout)

        return RunMetrics(
            success=result.returncode == 0,
            eval_score=1.0 if result.returncode == 0 else 0.0,
            duration_sec=duration,
            model_name=self.config.model,
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

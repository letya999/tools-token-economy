"""
OpenCode CLI subprocess wrapper.

Requires: npm install -g opencode (in WSL)
"""
import json
import os
import subprocess
import time

import tiktoken

from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool
from src.features.opencode_config import build_tool_restriction_prefix
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
            if not os.getenv("GOOGLE_API_KEY") and not os.getenv("GOOGLE_GENAI_API_KEY") and not os.getenv("GEMINI_API_KEY"):
                raise ValueError(f"Model {model} requires GOOGLE_API_KEY, GOOGLE_GENAI_API_KEY or GEMINI_API_KEY environment variable.")
        elif "openai/" in model:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError(f"Model {model} requires OPENAI_API_KEY environment variable.")
        elif "anthropic/" in model:
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise ValueError(f"Model {model} requires ANTHROPIC_API_KEY environment variable.")
        elif "openrouter/" in model:
            if not os.getenv("OPENROUTER_API_KEY"):
                raise ValueError(f"Model {model} requires OPENROUTER_API_KEY environment variable.")

    def run(self, task_description: str, worktree_path: str = ".") -> RunMetrics:
        """
        Execute the task via OpenCode CLI and collect metrics.
        """
        self._check_api_keys()

        restriction = build_tool_restriction_prefix(self.config)
        effective_task = restriction + task_description

        start_time = time.time()

        if self.mock:
            simulated_output = f"Task: {effective_task}\nTASK_COMPLETE"
            token_count = self._count_tokens(simulated_output)
            return RunMetrics(
                success=True,
                eval_score=1.0,
                input_tokens=token_count,
                output_tokens=self._count_tokens("TASK_COMPLETE"),
                tool_tokens=0,
                duration_sec=time.time() - start_time,
                model_calls=1,
                tool_calls=0,
                model_name=self.config.model
            )

        # Use rate limiter for real runs
        with self._rate_limiter:
            # opencode run --format json --dir [path] --model [provider/model] [task]
            cmd = [
                "opencode", "run",
                "--format", "json",
                "--dir", os.path.abspath(worktree_path),
                "--model", self._model_flag(),
                "--dangerously-skip-permissions",
                effective_task,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

        duration = time.time() - start_time

        input_tokens = 0
        output_tokens = 0
        tool_tokens = 0
        model_calls = 0
        tool_call_count = 0
        files_read = 0
        files_changed = 0
        patch_lines = 0
        errors = 0
        success = result.returncode == 0

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "step_finish":
                    usage = event.get("usage", {})
                    input_tokens += usage.get("inputTokens", usage.get("input_tokens", 0))
                    output_tokens += usage.get("outputTokens", usage.get("output_tokens", 0))
                    model_calls += 1

                elif event_type == "tool_use":
                    tool_call_count += 1
                    part = event.get("part", {})
                    tool_name = part.get("name", part.get("tool", ""))
                    tool_output = str(part.get("output", ""))
                    tool_tokens += self._count_tokens(tool_output)

                    read_tools = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
                    write_tools = {"patch", "write"}
                    if tool_name in read_tools:
                        files_read += 1
                    elif tool_name in write_tools:
                        files_changed += 1
                        patch_lines += tool_output.count("\n")

                elif event_type == "error":
                    errors += 1

            except json.JSONDecodeError:
                tool_tokens += self._count_tokens(line)

        if input_tokens == 0 and output_tokens == 0:
            input_tokens = self._count_tokens(effective_task)
            output_tokens = self._count_tokens(result.stdout)

        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_tokens=tool_tokens,
            duration_sec=duration,
            model_calls=model_calls,
            tool_calls=tool_call_count,
            model_name=self.config.model,
            files_read=files_read,
            files_changed=files_changed,
            patch_lines=patch_lines,
            errors=errors,
        )

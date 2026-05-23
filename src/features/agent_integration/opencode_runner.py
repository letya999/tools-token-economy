"""
OpenCode CLI subprocess wrapper.

Requires: npm install -g opencode (in WSL)
"""
import subprocess
import json
import time
import tiktoken
from typing import List
from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool
from src.features.rate_limiter import RateLimiter


class OpenCodeRunner:
    """
    Runs OpenCode CLI as a subprocess and collects metrics from its JSONL output.
    In mock/dry-run mode, skips the CLI entirely.
    """

    def __init__(self, config: AgentConfig, tools: List[Tool], mock: bool = False):
        self.config = config
        self.tools = tools
        self.mock = mock
        self._tokenizer = tiktoken.get_encoding("cl100k_base")
        self._rate_limiter = RateLimiter(requests_per_minute=10)

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tokenizer.encode(text))

    def _model_flag(self) -> str:
        """Convert model name to opencode provider/model format."""
        model = self.config.model
        # gemini-2.5-flash -> google/gemini-2.5-flash
        if model.startswith("gemini-"):
            return f"google/{model}"
        # claude-* -> anthropic/claude-*
        if model.startswith("claude-"):
            return f"anthropic/{model}"
        # Already in provider/model format
        return model

    def run(self, task_description: str, worktree_path: str = ".") -> RunMetrics:
        """
        Execute the task via OpenCode CLI and collect metrics.
        """
        start_time = time.time()

        if self.mock:
            simulated_output = f"Task: {task_description}\nTASK_COMPLETE"
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
            )

        # Use rate limiter for real runs
        with self._rate_limiter:
            cmd = [
                "opencode", "run",
                "--format", "json",
                "--dir", worktree_path,
                "--model", self._model_flag(),
                # opencode has no --max-turns; session runs until idle
                # --dangerously-skip-permissions grants full tool access
                "--dangerously-skip-permissions",
                task_description,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

        duration = time.time() - start_time

        # Parse JSONL output for metrics.
        # opencode --format json emits JSONL with events:
        #   type="tool_use"   -> part.input (args), part.output (result)
        #   type="step_finish" -> contains assistant message with usage
        #   type="text"        -> final text output
        #   type="error"       -> session error
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
                    # step_finish carries assistant message; usage is nested
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

        # Fallback token estimation if structured events had no usage
        if input_tokens == 0 and output_tokens == 0:
            input_tokens = self._count_tokens(task_description)
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
            files_read=files_read,
            files_changed=files_changed,
            patch_lines=patch_lines,
            errors=errors,
        )

import inspect
import logging
import os
import time
from typing import Any

import tiktoken
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.models.openai import OpenAIChat
from agno.tools import tool as agno_tool
from dotenv import load_dotenv

from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool
from src.features.rate_limiter import RateLimiter

_log = logging.getLogger(__name__)

class AgnoRunner:
    """
    Runs an Agno Agent to complete tasks using registered tools.
    """

    def __init__(self, config: AgentConfig, tools: list[Tool], mock: bool = False, timeout_sec: int = 600):
        self.config = config
        self.tools = tools
        self.mock = mock
        self.timeout_sec = timeout_sec
        try:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._tokenizer = None
        self._rate_limiter = RateLimiter(requests_per_minute=10)
        load_dotenv()

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        return len(text) // 4

    def _extract_model_id(self) -> str:
        model = self.config.model
        if model.startswith("openai/"):
            return model[len("openai/"):]
        if model.startswith("gpt-"):
            return model
        return model

    def _build_agno_tools(self) -> list:
        agno_tools_list = []
        for t in self.tools:
            def make_wrapper(tool_obj: Tool):
                sig = inspect.signature(tool_obj.execute)
                params = list(sig.parameters.keys())

                def wrapper(**kwargs):
                    try:
                        filtered = {k: v for k, v in kwargs.items() if k in params}
                        result = tool_obj.execute(**filtered)
                        return result.output
                    except Exception as e:
                        return f"Error executing tool {tool_obj.name}: {str(e)}"

                wrapper.__name__ = tool_obj.name
                wrapper.__doc__ = tool_obj.description
                # Expose real parameter signature so Agno builds correct OpenAI schema.
                # Without this, **kwargs causes schema {properties: {kwargs: {}}} and
                # the model calls tools with the wrong argument structure.
                wrapper.__signature__ = sig.replace(return_annotation=str)
                return agno_tool(wrapper)

            agno_tools_list.append(make_wrapper(t))
        return agno_tools_list

    def run(self, task_description: str, worktree_path: str = ".") -> RunMetrics:
        """Execute task via Agno Agent."""
        start_time = time.time()
        if self.mock:
            return self._run_mock(task_description, start_time)

        if not os.getenv("OPENAI_API_KEY"):
            raise EnvironmentError("OPENAI_API_KEY not set in environment.")

        model_id = self._extract_model_id()
        agno_tools_list = self._build_agno_tools()

        agent = Agent(
            model=OpenAIChat(id=model_id),
            tools=agno_tools_list,
            instructions=[
                f"You are a coding agent working in the repository at: {worktree_path}",
                "Complete the task using only the tools provided.",
                "When done, output exactly: TASK_COMPLETE",
            ],
            markdown=False,
            tool_call_limit=self.config.max_steps,
        )

        metrics_data = {
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "model_calls": 0, "tool_calls": 0, "files_read": 0,
            "files_changed": 0, "patch_lines": 0, "errors": 0
        }

        success = False
        try:
            with self._rate_limiter:
                response: RunOutput = agent.run(task_description)
            
            content_str = response.get_content_as_string() if hasattr(response, "get_content_as_string") else (str(response.content) if response.content else "")
            success = "TASK_COMPLETE" in content_str
            
            # Extract metrics from Agno response
            if response.metrics:
                metrics_data["input_tokens"] = response.metrics.input_tokens or 0
                metrics_data["output_tokens"] = response.metrics.output_tokens or 0
            
            # If metrics missing, fallback to counting
            if metrics_data["input_tokens"] == 0:
                metrics_data["input_tokens"] = self._count_tokens(task_description)
            if metrics_data["output_tokens"] == 0:
                metrics_data["output_tokens"] = self._count_tokens(content_str)

            # Count model calls and tool tokens from messages
            for msg in (response.messages or []):
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", "")
                if role == "assistant":
                    metrics_data["model_calls"] += 1
                elif role == "tool":
                    metrics_data["tool_tokens"] += self._count_tokens(str(content))

            # Count tool calls from ToolExecution list
            _read_tools = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
            _write_tools = {"patch", "write"}
            for tool_exec in (response.tools or []):
                metrics_data["tool_calls"] += 1
                name = tool_exec.tool_name or ""
                if name in _read_tools:
                    metrics_data["files_read"] += 1
                elif name in _write_tools:
                    metrics_data["files_changed"] += 1
                if tool_exec.tool_call_error:
                    metrics_data["errors"] += 1

        except Exception as e:
            import traceback as _tb
            _log.error("Agno agent execution failed: %s\n%s", str(e), _tb.format_exc())
            success = False

        duration = time.time() - start_time
        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            duration_sec=duration,
            model_name=self.config.model,
            **metrics_data
        )

    def _run_mock(self, task_description: str, start_time: float) -> RunMetrics:
        sim_out = f"Task: {task_description}\nTASK_COMPLETE"
        return RunMetrics(
            success=True, eval_score=1.0,
            input_tokens=self._count_tokens(task_description),
            output_tokens=self._count_tokens("TASK_COMPLETE"),
            tool_tokens=0, duration_sec=time.time() - start_time,
            model_calls=1, tool_calls=0, model_name=self.config.model,
            files_read=0, files_changed=0, patch_lines=0, errors=0
        )

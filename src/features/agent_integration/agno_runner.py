import asyncio
import contextlib
import inspect
import json
import logging
import os
import shlex
import subprocess
import time
from typing import Any

import tiktoken
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.models.openai import OpenAIChat
from agno.tools import tool as agno_tool
from agno.tools.mcp import MCPTools
from dotenv import load_dotenv
from mcp import StdioServerParameters, ClientSession
from mcp.client.stdio import stdio_client

from src.core.models import AgentConfig, McpServerConfig, RunMetrics
from src.core.tools import Tool
from src.features.evaluation import EvalEngine
from src.features.rate_limiter import RateLimiter

_log = logging.getLogger(__name__)

class AgnoRunner:
    """
    Runs an Agno Agent to complete tasks using registered tools.
    """

    def __init__(
        self,
        config: AgentConfig,
        tools: list[Tool],
        mock: bool = False,
        timeout_sec: int = 600,
        run_dir: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
    ):
        self.config = config
        self.tools = tools
        self.mock = mock
        self.timeout_sec = timeout_sec
        self.run_dir = run_dir
        self.mcp_configs = mcp_configs or []
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

                # Build a function with real named parameters via exec so Agno
                # can introspect them and attach per-parameter validators.
                globs: dict = {"_tool": tool_obj}
                parts: list[str] = []
                args: list[str] = []
                for name, param in sig.parameters.items():
                    ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
                    globs[f"_t_{name}"] = ann
                    args.append(f"{name}={name}")
                    if param.default is inspect.Parameter.empty:
                        parts.append(f"{name}: _t_{name}")
                    else:
                        globs[f"_d_{name}"] = param.default
                        parts.append(f"{name}: _t_{name} = _d_{name}")

                src = (
                    f"def {tool_obj.name}({', '.join(parts)}) -> str:\n"
                    f"    try:\n"
                    f"        return _tool.execute({', '.join(args)}).output\n"
                    f"    except Exception as _e:\n"
                    f"        return 'Error: ' + str(_e)\n"
                )
                exec(src, globs)  # noqa: S102
                fn = globs[tool_obj.name]
                fn.__doc__ = tool_obj.description
                return agno_tool(fn)

            agno_tools_list.append(make_wrapper(t))
        return agno_tools_list

    def _validate_run(self, worktree_path: str, test_cmd: str) -> tuple[bool, int, int]:
        """
        Validates the run by checking git status and running only changed test files.
        """
        try:
            # 1. Detect all changed files
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path, capture_output=True, text=True
            )
            changed_files = []
            for line in status.stdout.splitlines():
                if len(line) < 3:
                    continue
                fname = line[3:].strip()
                if " -> " in fname:
                    fname = fname.split(" -> ", 1)[1]
                changed_files.append(fname)

            if not changed_files:
                return False, 0, 0

            # 2. Count patch lines and save patch
            diff_result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=worktree_path, capture_output=True, text=True
            )
            patch_lines = len([
                line for line in diff_result.stdout.splitlines()
                if line.startswith('+') or line.startswith('-')
            ])
            
            if self.run_dir and os.path.isdir(self.run_dir):
                patch_path = os.path.join(self.run_dir, "changes.patch")
                with open(patch_path, "w", encoding="utf-8") as f:
                    f.write(diff_result.stdout)

            # 3. Filter to test files only
            test_files = [
                f for f in changed_files
                if f.startswith("tests/") or os.path.basename(f).startswith("test_") or f.endswith("_test.py")
            ]

            if not test_files:
                return False, 0, patch_lines

            # 4. Build command
            cmd_parts = shlex.split(test_cmd)
            try:
                pytest_idx = next(i for i, p in enumerate(cmd_parts) if p in ('pytest', 'py.test'))
                runner_parts = cmd_parts[:pytest_idx + 1]
            except StopIteration:
                runner_parts = []
                for part in cmd_parts:
                    if part.startswith('-') or '/' in part or os.sep in part:
                        break
                    runner_parts.append(part)

            specific_cmd = shlex.join(runner_parts + test_files + ["-x", "-q"])

            # 5. Run via EvalEngine
            engine = EvalEngine()
            outcome = engine.evaluate(worktree_path, specific_cmd)

            if not outcome.success:
                _log.warning("Validation failed. Test output:\n%s", outcome.output[-3000:])

            return outcome.success, outcome.tests_passed, patch_lines

        except subprocess.TimeoutExpired:
            _log.error("Validation timed out")
            return False, 0, 0
        except Exception as e:
            _log.error("Validation failed: %s", str(e))
            return False, 0, 0

    def _extract_metrics_from_response(
        self,
        response: RunOutput,
        task_description: str,
        log_path: str | None,
    ) -> dict[str, Any]:
        metrics_data: dict[str, Any] = {
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "model_calls": 0, "tool_calls": 0, "files_read": 0,
            "files_changed": 0, "patch_lines": 0, "errors": 0,
            "tests_passed": 0,
        }

        if log_path:
            try:
                messages = []
                for m in (response.messages or []):
                    messages.append({
                        "role": getattr(m, "role", "unknown"),
                        "content": getattr(m, "content", ""),
                        "tool_calls": getattr(m, "tool_calls", None),
                    })
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(messages, f, indent=2)
            except Exception as e:
                _log.error("Failed to save conversation log: %s", e)

        if response.metrics:
            metrics_data["input_tokens"] = response.metrics.input_tokens or 0
            metrics_data["output_tokens"] = response.metrics.output_tokens or 0

        content_str = (
            response.get_content_as_string()
            if hasattr(response, "get_content_as_string")
            else (str(response.content) if response.content else "")
        )
        if metrics_data["input_tokens"] == 0:
            metrics_data["input_tokens"] = self._count_tokens(task_description)
        if metrics_data["output_tokens"] == 0:
            metrics_data["output_tokens"] = self._count_tokens(content_str)

        _read_tools = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
        _write_tools = {"patch", "write"}

        for msg in (response.messages or []):
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "")
            if role == "assistant":
                metrics_data["model_calls"] += 1
            elif role == "tool":
                metrics_data["tool_tokens"] += self._count_tokens(str(content))

        for tool_exec in (response.tools or []):
            metrics_data["tool_calls"] += 1
            name = tool_exec.tool_name or ""
            is_error = tool_exec.tool_call_error
            res_str = str(getattr(tool_exec, "result", "") or "")
            if res_str.startswith("Error:"):
                is_error = True
            if name in _read_tools:
                metrics_data["files_read"] += 1
            elif name in _write_tools and not is_error:
                metrics_data["files_changed"] += 1
            if is_error:
                metrics_data["errors"] += 1

        return metrics_data

    async def _run_with_mcp(
        self,
        task_description: str,
        worktree_path: str,
        test_cmd: str,
        log_path: str | None,
    ) -> RunMetrics:
        start_time = time.time()
        if not os.getenv("OPENAI_API_KEY"):
            raise EnvironmentError("OPENAI_API_KEY not set in environment.")

        model_id = self._extract_model_id()
        success = False
        metrics_data: dict[str, Any] = {}

        # Warm up RAG tools only if not already pre-ingested by the orchestrator.
        for tool in self.tools:
            if hasattr(tool, "_init_rag") and not getattr(tool, "_ingested", False):
                _log.info("Warming up RAG tool (not pre-ingested): %s", tool.name)
                try:
                    tool._init_rag()  # type: ignore[attr-defined]
                except Exception as e:
                    _log.warning("RAG warm-up failed: %s", e)

        try:
            async with contextlib.AsyncExitStack() as stack:
                mcp_tool_instances = []
                for cfg in self.mcp_configs:
                    params = StdioServerParameters(
                        command=cfg.command,
                        args=cfg.resolve_args(worktree_path),
                    )
                    
                    # WORKAROUND for WSL/Agno async bugs: 
                    # Manually initialize the session and hand it to Agno.
                    stdio_transport = await stack.enter_async_context(stdio_client(params))
                    read, write = stdio_transport[0:2]
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    
                    mcp_inst = MCPTools(session=session)
                    await mcp_inst.initialize()
                    mcp_tool_instances.append(mcp_inst)

                all_tools = self._build_agno_tools() + mcp_tool_instances
                agent = Agent(
                    model=OpenAIChat(id=model_id),
                    tools=all_tools,
                    instructions=[
                        f"You are a coding agent working in the repository at: {worktree_path}",
                        "Complete the task using only the tools provided.",
                        "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
                        "If a tool returns an error, try a different approach - do not repeat the exact same tool call.",
                        "When done, output exactly: TASK_COMPLETE",
                    ],
                    markdown=False,
                    tool_call_limit=self.config.max_steps,
                )

                with self._rate_limiter:
                    response: RunOutput = await agent.arun(task_description)

            metrics_data = self._extract_metrics_from_response(response, task_description, log_path)

            if worktree_path and os.path.isdir(worktree_path):
                success, tests_passed, patch_lines = self._validate_run(worktree_path, test_cmd)
                metrics_data["tests_passed"] = tests_passed
                metrics_data["patch_lines"] = patch_lines
            else:
                content_str = (
                    response.get_content_as_string()
                    if hasattr(response, "get_content_as_string")
                    else (str(response.content) if response.content else "")
                )
                success = "TASK_COMPLETE" in content_str

        except Exception:
            _log.exception("Agno MCP agent execution failed")
            success = False

        duration = time.time() - start_time
        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            duration_sec=duration,
            model_name=self.config.model,
            **(metrics_data or {
                "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
                "model_calls": 0, "tool_calls": 0, "files_read": 0,
                "files_changed": 0, "patch_lines": 0, "errors": 0,
                "tests_passed": 0,
            }),
        )

    def run(self, task_description: str, worktree_path: str = ".", test_cmd: str = "uv run pytest", log_path: str | None = None) -> RunMetrics:
        """Execute task via Agno Agent."""
        start_time = time.time()
        if self.mock:
            return self._run_mock(task_description, start_time)

        # Warm up RAG tools only if not already pre-ingested by the orchestrator.
        if not self.mcp_configs:
            for tool in self.tools:
                if hasattr(tool, "_init_rag") and not getattr(tool, "_ingested", False):
                    _log.info("Warming up RAG tool (not pre-ingested): %s", tool.name)
                    try:
                        tool._init_rag()  # type: ignore[attr-defined]
                    except Exception as e:
                        _log.warning("RAG warm-up failed: %s", e)

        if self.mcp_configs:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._run_with_mcp(task_description, worktree_path, test_cmd, log_path),
                    )
                    return future.result()
            return asyncio.run(self._run_with_mcp(task_description, worktree_path, test_cmd, log_path))

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
                "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
                "If a tool returns an error, try a different approach - do not repeat the exact same tool call.",
                "When done, output exactly: TASK_COMPLETE",
            ],
            markdown=False,
            tool_call_limit=self.config.max_steps,
        )

        success = False
        metrics_data: dict[str, Any] = {}
        try:
            with self._rate_limiter:
                response: RunOutput = agent.run(task_description)

            metrics_data = self._extract_metrics_from_response(response, task_description, log_path)

            if worktree_path and os.path.isdir(worktree_path):
                success, tests_passed, patch_lines = self._validate_run(worktree_path, test_cmd)
                metrics_data["tests_passed"] = tests_passed
                metrics_data["patch_lines"] = patch_lines
            else:
                content_str = (
                    response.get_content_as_string()
                    if hasattr(response, "get_content_as_string")
                    else (str(response.content) if response.content else "")
                )
                success = "TASK_COMPLETE" in content_str

        except Exception:
            _log.exception("Agno agent execution failed")
            success = False

        duration = time.time() - start_time
        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            duration_sec=duration,
            model_name=self.config.model,
            **(metrics_data or {
                "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
                "model_calls": 0, "tool_calls": 0, "files_read": 0,
                "files_changed": 0, "patch_lines": 0, "errors": 0,
                "tests_passed": 0,
            }),
        )

    def _run_mock(self, task_description: str, start_time: float) -> RunMetrics:
        return RunMetrics(
            success=True, eval_score=1.0,
            input_tokens=self._count_tokens(task_description),
            output_tokens=self._count_tokens("TASK_COMPLETE"),
            tool_tokens=0, duration_sec=time.time() - start_time,
            model_calls=1, tool_calls=0, model_name=self.config.model,
            files_read=0, files_changed=0, patch_lines=0, errors=0
        )

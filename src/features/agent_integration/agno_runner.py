import asyncio
import concurrent.futures
import contextlib
import inspect
import json
import keyword
import logging
import os
import subprocess
import sys
import time
from typing import Any

import tiktoken
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.tools import tool as agno_tool
from agno.tools.mcp import MCPTools
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.core.models import AgentConfig, McpServerConfig, RunMetrics
from src.core.tools import Tool
from src.features.execution_validator import ExecutionValidator
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
        validation_cmd: str | None = None,
        baseline_pass_count: int | None = None,
        max_iterations: int = 15,
        required_files: list[str] | None = None,
    ):
        self.config = config
        self.tools = tools
        self.mock = mock
        self.timeout_sec = timeout_sec
        self.run_dir = run_dir
        self.mcp_configs = mcp_configs or []
        self.validation_cmd = validation_cmd
        self.baseline_pass_count = baseline_pass_count
        self.max_iterations = max_iterations
        self.required_files = required_files or []
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
                    if not name.isidentifier() or keyword.iskeyword(name):
                        raise ValueError(f"Tool {tool_obj.name!r} has invalid parameter name: {name!r}")
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

    def _build_agent(self, model_id: str, tools: list, worktree_path: str) -> Agent:
        effective_limit = min(self.config.max_steps, self.max_iterations)
        return Agent(
            model=OpenAIChat(id=model_id, max_tokens=4096),
            tools=tools,
            instructions=[
                f"You are a coding agent working in the repository at: {worktree_path}",
                "Complete the task using only the tools provided.",
                "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
                "MANDATORY: You MUST call the `write` or `patch` tool to save your code changes to disk before saying TASK_COMPLETE. Reading files and thinking about changes is not enough - you must persist changes with a tool call.",
                "Workflow: (1) Use retrieval tools to understand the codebase. (2) Write your changes using `write` (full file) or `patch` (unified diff). (3) Verify by reading the file back. (4) Output exactly: TASK_COMPLETE",
                "If a tool returns an error, try a different approach - do not repeat the exact same tool call.",
                "Never output TASK_COMPLETE if you have not called write or patch at least once.",
                "CRITICAL: NEVER delete, truncate, or overwrite existing code. When adding to an existing file, preserve ALL existing content. If using 'write', copy all original content and append/insert only your new code. If using 'patch', only add lines — NEVER remove existing functions, classes, or tests.",
                "CRITICAL: NEVER remove or replace existing tests. The test file already contains tests. You must ADD a new test without touching any existing test.",
                "Efficiency: Use the `shell` tool's `multi_cmd` parameter to run multiple related commands in a single turn (e.g. `ls` then `cat`).",
            ],
            markdown=False,
            tool_call_limit=effective_limit,
        )

    def _validate_run(self, worktree_path: str, test_cmd: str) -> tuple[bool, int, int, int, str, bool]:
        """
        Validates the run using ExecutionValidator.
        Returns (success, tests_passed, tests_failed, patch_lines, execution_result, made_changes).
        """
        validator = ExecutionValidator(worktree_path, run_dir=self.run_dir, timeout_sec=self.timeout_sec)

        # 1. Capture patch details
        patch_lines = 0
        try:
            diff_result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=worktree_path, capture_output=True, text=True, timeout=10
            )
            patch_lines = len([
                line for line in diff_result.stdout.splitlines()
                if line.startswith('+') or line.startswith('-')
            ])
            if self.run_dir and os.path.isdir(self.run_dir):
                patch_path = os.path.join(self.run_dir, "final.patch")
                with open(patch_path, "w", encoding="utf-8") as f:
                    f.write(diff_result.stdout)
        except Exception as e:
            _log.warning("Failed to capture patch: %s", e)

        # 2. Run validation
        res = validator.validate(
            validation_cmd=self.validation_cmd,
            test_cmd=test_cmd,
            baseline_pass_count=self.baseline_pass_count
        )

        # 3. Decision: success = made changes AND didn't fail execution
        made_changes = patch_lines > 0
        success = made_changes and res.outcome != "failed"

        if not success and made_changes:
            _log.warning("Validation failed (%s). Stdout:\n%s\nStderr:\n%s",
                         res.method_used, res.stdout[-500:], res.stderr[-500:])

        return success, res.tests_passed, res.tests_failed, patch_lines, res.outcome, made_changes

    def _extract_metrics_from_response(
        self,
        response: RunOutput,
        task_description: str,
        log_path: str | None,
    ) -> dict[str, Any]:
        metrics_data: dict[str, Any] = {
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "model_calls": 0, "tool_calls": 0, "files_read": 0,
            "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
            "tests_passed": 0,
            "agent_cycles": 0,
            "time_to_target": 0,
            "context_waste_ratio": 0.0,
        }

        msgs = []
        for m in (response.messages or []):
            raw_tc = getattr(m, "tool_calls", None)
            if raw_tc is not None:
                try:
                    # Attempt to serialize to a clean JSON-compatible structure
                    tc_safe = json.loads(json.dumps(raw_tc, default=str))
                except Exception:
                    # Fallback for complex, non-serializable objects
                    tc_safe = str(raw_tc)
            else:
                tc_safe = None

            msgs.append({
                "role": getattr(m, "role", ""),
                "content": str(getattr(m, "content", "") or "")[:4000],
                "tool_calls": tc_safe,
            })
        
        if self.run_dir:
            log_path = os.path.join(self.run_dir, "agent_messages.json")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(msgs, f, ensure_ascii=False, indent=2)

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

        _read_tool_names = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
        _write_tools = {"patch", "write"}

        agent_cycles = sum(1 for m in (response.messages or []) if getattr(m, "role") == "tool")
        metrics_data["agent_cycles"] = agent_cycles

        for msg in msgs:
            role = msg["role"]
            content = msg["content"]
            if role == "assistant":
                metrics_data["model_calls"] += 1
            elif role == "tool":
                metrics_data["tool_tokens"] += self._count_tokens(str(content))

        total_read_tok = 0
        useful_read_tok = 0
        time_to_target = 0
        cycle_count = 0

        # Cycle counting for time_to_target
        for msg in msgs:
            role = msg["role"]
            if role == "tool":
                cycle_count += 1
                if time_to_target == 0 and self.required_files:
                    content_str = str(msg.get("content", "") or "")
                    if any(req in content_str for req in self.required_files):
                        time_to_target = cycle_count

        for tool_exec in (response.tools or []):
            metrics_data["tool_calls"] += 1
            name = tool_exec.tool_name or ""
            is_error = tool_exec.tool_call_error
            res_str = str(getattr(tool_exec, "result", "") or "")
            if res_str.startswith("Error:"):
                is_error = True

            if name in _read_tool_names:
                metrics_data["files_read"] += 1
                tok = self._count_tokens(res_str)
                total_read_tok += tok
                args = getattr(tool_exec, "input", {}) or {}
                file_arg = (
                    args.get("path") or args.get("file_path") or
                    args.get("query") or args.get("pattern") or ""
                )
                if self.required_files and any(
                    req in file_arg or file_arg in req
                    for req in self.required_files
                ):
                    useful_read_tok += tok

            elif name in _write_tools and not is_error:
                metrics_data["files_changed"] += 1
            if is_error:
                metrics_data["tool_errors"] += 1

        metrics_data["context_waste_ratio"] = (
            (total_read_tok - useful_read_tok) / total_read_tok
            if total_read_tok > 0 else 0.0
        )
        metrics_data["time_to_target"] = time_to_target

        return metrics_data

    async def _run_with_mcp(
        self,
        task_description: str,
        worktree_path: str,
        test_cmd: str,
        log_path: str | None,
    ) -> RunMetrics:
        if not os.getenv("OPENAI_API_KEY"):
            raise OSError("OPENAI_API_KEY not set in environment.")

        model_id = self._extract_model_id()
        success = False
        metrics_data: dict[str, Any] = {}
        warmup_total = 0.0
        start_time = time.time()  # fallback; overwritten after MCP warmup below

        # Warm up RAG tools
        for tool in self.tools:
            if hasattr(tool, "_init_rag") and not getattr(tool, "_ingested", False):
                _log.info("Warming up RAG tool (not pre-ingested): %s", tool.name)
                t_w = time.time()
                try:
                    tool._init_rag()  # type: ignore[attr-defined]
                except Exception as e:
                    _log.warning("RAG warm-up failed: %s", e)
                warmup_total += time.time() - t_w

        try:
            async with contextlib.AsyncExitStack() as stack:
                mcp_env = os.environ.copy()
                if sys.platform != "win32":
                    extra = [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin")]
                    cur = mcp_env.get("PATH", "")
                    additions = [p for p in extra if p not in cur and os.path.isdir(p)]
                    if additions:
                        mcp_env["PATH"] = ":".join(additions) + ":" + cur

                mcp_tool_instances = []
                sessions_list = []
                for cfg in self.mcp_configs:
                    params = StdioServerParameters(
                        command=cfg.command,
                        args=cfg.resolve_args(worktree_path),
                        cwd=worktree_path,
                        env=mcp_env,
                    )
                    stdio_transport = await stack.enter_async_context(stdio_client(params))
                    read, write = stdio_transport[0:2]
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    sessions_list.append(session)

                    mcp_inst = MCPTools(session=session)
                    await mcp_inst.initialize()
                    mcp_tool_instances.append(mcp_inst)

                # MCP Warmup calls
                for mcp_cfg, session in zip(self.mcp_configs, sessions_list, strict=False):
                    if mcp_cfg.warmup_call:
                        _log.info("Warming up MCP tool: %s", mcp_cfg.tool_name)
                        t_w = time.time()
                        try:
                            await session.call_tool(mcp_cfg.warmup_call, mcp_cfg.warmup_args or {})
                        except Exception as e:
                            _log.warning("MCP warmup call failed for %s: %s", mcp_cfg.tool_name, e)
                        warmup_total += time.time() - t_w

                start_time = time.time()
                all_tools = self._build_agno_tools() + mcp_tool_instances
                agent = self._build_agent(model_id, all_tools, worktree_path)

                response: RunOutput = await asyncio.wait_for(
                        agent.arun(task_description),
                        timeout=float(self.timeout_sec),
                    )

            duration = time.time() - start_time
            metrics_data = self._extract_metrics_from_response(response, task_description, log_path)

            if worktree_path and os.path.isdir(worktree_path):
                success, tests_passed, tests_failed, patch_lines, exec_result, made_changes = self._validate_run(worktree_path, test_cmd)
                metrics_data["tests_passed"] = tests_passed
                metrics_data["patch_lines"] = patch_lines
                metrics_data["errors"] = tests_failed
                metrics_data["execution_result"] = exec_result
                metrics_data["made_changes"] = made_changes
            else:
                content_str = (
                    response.get_content_as_string()
                    if hasattr(response, "get_content_as_string")
                    else (str(response.content) if response.content else "")
                )
                success = "TASK_COMPLETE" in content_str

        except TimeoutError:
            _log.warning("Agent async run timed out after %ss", self.timeout_sec)
            success = False
            duration = float(self.timeout_sec)
        except Exception:
            _log.exception("Agno MCP agent execution failed")
            success = False
            duration = time.time() - start_time

        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            duration_sec=duration,
            model_name=self.config.model,
            warmup_sec=warmup_total,
            **(metrics_data or {
                "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
                "model_calls": 0, "tool_calls": 0, "files_read": 0,
                "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
                "tests_passed": 0, "execution_result": "not_verified", "made_changes": False,
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
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._run_with_mcp(task_description, worktree_path, test_cmd, log_path),
                    )
                    return future.result()
            return asyncio.run(self._run_with_mcp(task_description, worktree_path, test_cmd, log_path))

        if not os.getenv("OPENAI_API_KEY"):
            raise OSError("OPENAI_API_KEY not set in environment.")

        model_id = self._extract_model_id()
        agno_tools_list = self._build_agno_tools()
        agent = self._build_agent(model_id, agno_tools_list, worktree_path)
        _log.info("Agent starting: model=%s tools=%d timeout=%ss", model_id, len(agno_tools_list), self.timeout_sec)

        success = False
        metrics_data: dict[str, Any] = {}
        try:
            with self._rate_limiter:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                    _future = _pool.submit(agent.run, task_description)
                    response: RunOutput = _future.result(timeout=self.timeout_sec)
            _log.info("Agent finished: model=%s", model_id)

            metrics_data = self._extract_metrics_from_response(response, task_description, log_path)

            if worktree_path and os.path.isdir(worktree_path):
                success, tests_passed, tests_failed, patch_lines, exec_result, made_changes = self._validate_run(worktree_path, test_cmd)
                metrics_data["tests_passed"] = tests_passed
                metrics_data["patch_lines"] = patch_lines
                metrics_data["errors"] = tests_failed
                metrics_data["execution_result"] = exec_result
                metrics_data["made_changes"] = made_changes
            else:
                content_str = (
                    response.get_content_as_string()
                    if hasattr(response, "get_content_as_string")
                    else (str(response.content) if response.content else "")
                )
                success = "TASK_COMPLETE" in content_str

        except concurrent.futures.TimeoutError:
            _log.warning("Agent sync run timed out after %ss", self.timeout_sec)
            success = False
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
                "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
                "tests_passed": 0, "execution_result": "not_verified", "made_changes": False,
            }),
        )

    def _run_mock(self, task_description: str, start_time: float) -> RunMetrics:
        return RunMetrics(
            success=True, eval_score=1.0,
            input_tokens=self._count_tokens(task_description),
            output_tokens=self._count_tokens("TASK_COMPLETE"),
            tool_tokens=0, duration_sec=time.time() - start_time,
            model_calls=1, tool_calls=0, model_name=self.config.model,
            files_read=0, files_changed=0, patch_lines=0, errors=0, tool_errors=0
        )

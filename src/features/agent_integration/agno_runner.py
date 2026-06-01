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
from agno.exceptions import InputCheckError
from agno.run.agent import RunOutput
from agno.tools import tool as agno_tool
from agno.tools.mcp import MCPTools
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:
    import agentbudget
    from agentbudget import BudgetExhausted, LoopDetected
    _HAS_AGENTBUDGET = True
except ImportError:
    _HAS_AGENTBUDGET = False
    BudgetExhausted = type("BudgetExhausted", (Exception,), {})
    LoopDetected = type("LoopDetected", (Exception,), {})

from src.core.models import AgentConfig, McpServerConfig, RunMetrics, ProviderConfig
from src.core.provider_factory import build_agent_model
from src.core.tools import Tool
from src.features.cost_guard import BudgetExceededError
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
        provider_cfg: ProviderConfig | None = None,
        mock: bool = False,
        timeout_sec: int = 600,
        run_dir: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        validation_cmd: str | None = None,
        baseline_pass_count: int | None = None,
        max_iterations: int = 15,
        required_files: list[str] | None = None,
        max_config_cost_usd: float = 0.50,
        seed: int | None = None,
    ):
        self.config = config
        self.tools = tools
        self.provider_cfg = provider_cfg or ProviderConfig(model=config.model)
        self.mock = mock
        self.timeout_sec = timeout_sec
        self.run_dir = run_dir
        self.mcp_configs = mcp_configs or []
        self.validation_cmd = validation_cmd
        self.baseline_pass_count = baseline_pass_count
        self.max_iterations = max_iterations
        self.required_files = required_files or []
        self.max_config_cost_usd = max_config_cost_usd
        self.seed = seed
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
        # Token accumulation now happens in the tool_hooks middleware,
        # not in this wrapper. This keeps the wrapper minimal.
        if not hasattr(self, "_tool_output_token_counter"):
            self._tool_output_token_counter = [0]
        agno_tools_list = []
        for t in self.tools:
            def make_wrapper(tool_obj: Tool):
                sig = inspect.signature(tool_obj.execute)

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

    def _build_budget_tool_hook(self, max_tool_output_tokens: int = 150_000):
        """Per-tool-call middleware. Fires before AND after each tool call.
        """
        counter = self._tool_output_token_counter
        count_tok = self._count_tokens

        def budget_hook(function_name, function_call, arguments):
            # PRE: hard cap BEFORE calling — catches read-loops on subsequent calls.
            if counter[0] > max_tool_output_tokens:
                raise InputCheckError(
                    f"BUDGET_EXCEEDED: accumulated tool output {counter[0]} tokens "
                    f"exceeds {max_tool_output_tokens} — aborting (read-loop detected)"
                )
            result = function_call(**arguments)
            if inspect.iscoroutine(result):
                async def _counted():
                    actual = await result
                    actual_tok = count_tok(str(actual))
                    counter[0] += actual_tok
                    # POST check: catches single-call explosions (e.g. read_all).
                    if counter[0] > max_tool_output_tokens:
                        raise InputCheckError(
                            f"BUDGET_EXCEEDED after {function_name}: "
                            f"accumulated {counter[0]} tokens exceeds {max_tool_output_tokens}"
                        )
                    return actual
                return _counted()
            # Sync tool path: count and post-check immediately.
            tok = count_tok(str(result))
            counter[0] += tok
            if counter[0] > max_tool_output_tokens:
                raise InputCheckError(
                    f"BUDGET_EXCEEDED after {function_name}: "
                    f"accumulated {counter[0]} tokens exceeds {max_tool_output_tokens}"
                )
            return result

        return budget_hook

    def _build_budget_pre_hook(self, max_cost_usd: float = 0.50):
        """Returns a pre_hook with three independent budget guards.
        """
        MAX_MODEL_CALLS = 20
        MAX_TOOL_OUTPUT_TOKENS = 150_000  # Sum across all tool calls in run.
        UNDERESTIMATE_CORRECTION = 20
        MAX_PER_CALL_CHARS = 400_000

        call_count = [0]
        accumulated_estimated_cost = [0.0]
        # Reset in-place so tool wrappers built earlier keep their reference.
        if hasattr(self, "_tool_output_token_counter"):
            self._tool_output_token_counter[0] = 0
        else:
            self._tool_output_token_counter = [0]

        pricing = {
            "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
            "openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
            "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
            "openai/gpt-4.1-nano": {"input": 0.10, "output": 0.40},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
        }
        p = pricing.get(self.config.model, pricing.get("openai/gpt-4.1-mini"))

        def budget_hook(**kwargs):
            # Guard 1: hard model-call counter
            call_count[0] += 1
            if call_count[0] > MAX_MODEL_CALLS:
                _log.warning("Budget pre-hook: hard model-call limit %d reached", MAX_MODEL_CALLS)
                raise InputCheckError(
                    f"Hard model-call limit of {MAX_MODEL_CALLS} exceeded — aborting to stay within budget"
                )

            # Guard 2: cumulative tool-output tokens (populated by tool wrappers).
            tool_out_total = self._tool_output_token_counter[0]
            if tool_out_total > MAX_TOOL_OUTPUT_TOKENS:
                _log.warning(
                    "Budget pre-hook: cumulative tool-output tokens %d exceeds %d",
                    tool_out_total, MAX_TOOL_OUTPUT_TOKENS,
                )
                raise InputCheckError(
                    f"Pre-hook aborted: cumulative tool-output tokens {tool_out_total} "
                    f"exceeds limit {MAX_TOOL_OUTPUT_TOKENS} — read-loop detected"
                )

            run_context = kwargs.get('run_context')
            if run_context is None:
                return
            msg_list = getattr(run_context, 'messages', None) or []
            if not msg_list:
                return

            total_chars = 0
            for m in msg_list:
                content = getattr(m, 'content', None)
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, str):
                            total_chars += len(item)
                        elif isinstance(item, dict):
                            total_chars += len(str(item.get('text', '') or ''))
                        else:
                            total_chars += len(str(item))
                for tc in (getattr(m, 'tool_calls', None) or []):
                    total_chars += len(str(tc))

            # Guard cost
            estimated_tokens = total_chars // 4
            this_call_cost = (estimated_tokens / 1_000_000) * p["input"]
            accumulated_estimated_cost[0] += this_call_cost
            corrected_accumulated = accumulated_estimated_cost[0] * UNDERESTIMATE_CORRECTION
            if corrected_accumulated > max_cost_usd:
                _log.warning(
                    "Budget pre-hook: accumulated corrected cost $%.4f exceeds limit $%.2f",
                    corrected_accumulated, max_cost_usd
                )
                raise InputCheckError(
                    f"Pre-hook aborted: accumulated estimated cost ${corrected_accumulated:.4f} "
                    f"exceeds per-config limit ${max_cost_usd:.2f}"
                )

            # Guard 3: per-call context size
            if total_chars > MAX_PER_CALL_CHARS:
                _log.warning(
                    "Budget pre-hook: per-call context %d chars exceeds limit %d",
                    total_chars, MAX_PER_CALL_CHARS,
                )
                raise InputCheckError(
                    f"Pre-hook aborted: per-call context {total_chars} chars "
                    f"exceeds limit {MAX_PER_CALL_CHARS} — context explosion detected"
                )

        return budget_hook

    def _build_agent(self, model_id: str, tools: list, system_prefix: str = "") -> Agent:
        effective_limit = min(self.config.max_steps, self.max_iterations)
        
        instructions = []
        if system_prefix:
            instructions.append(system_prefix)
            
        instructions.extend([
            "You are a coding agent. Complete the task using only the tools provided.",
            "Always use RELATIVE file paths (relative to the repository root) when calling file tools.",
            "MANDATORY: You MUST call at least one file-modification tool before TASK_COMPLETE.",
            "Workflow: (1) Retrieve context. (2) Save changes. (3) Verify. (4) Output TASK_COMPLETE",
            "CRITICAL: preserve ALL existing content when adding to a file.",
            "CONVERGENCE RULE: After reading 3-5 files START writing your fix immediately.",
        ])

        budget_hook = self._build_budget_pre_hook(max_cost_usd=self.max_config_cost_usd)
        effective_tool_cap = min(effective_limit, 50)

        _has_read_all = any(getattr(t, "name", "") == "read_all" for t in self.tools)
        _tool_out_limit = 60_000 if _has_read_all else 150_000
        budget_tool_hook = self._build_budget_tool_hook(max_tool_output_tokens=_tool_out_limit)

        return Agent(
            model=build_agent_model(self.provider_cfg),
            tools=tools,
            instructions=instructions,
            markdown=False,
            tool_call_limit=effective_tool_cap,
            pre_hooks=[budget_hook],
            tool_hooks=[budget_tool_hook],
        )

    def _validate_run(self, worktree_path: str, test_cmd: str) -> tuple[bool, int, int, int, str, bool, str, str]:
        validator = ExecutionValidator(worktree_path, run_dir=self.run_dir, timeout_sec=self.timeout_sec)
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

        res = validator.validate(
            validation_cmd=self.validation_cmd,
            test_cmd=test_cmd,
            baseline_pass_count=self.baseline_pass_count
        )
        made_changes = patch_lines > 0
        success = made_changes and res.outcome != "failed"
        return success, res.tests_passed, res.tests_failed, patch_lines, res.outcome, made_changes, res.stderr, res.stdout

    def _estimate_tool_schema_bytes(self, tools: list[Any]) -> int:
        """Estimate the number of bytes the tool definitions consume in the prompt."""
        total = 0
        for t in tools:
            try:
                name = getattr(t, "name", str(t))
                desc = getattr(t, "description", "")
                total += len(name) + len(desc)
                # Approx 100 bytes per function for parameters/metadata
                if hasattr(t, "functions"):
                    total += len(t.functions) * 100
                else:
                    total += 100
            except Exception:
                continue
        return total

    def _extract_metrics_from_response(
        self,
        response: RunOutput,
        task_description: str,
        log_path: str | None,
        tools: list[Any] = None,
    ) -> dict[str, Any]:
        metrics_data: dict[str, Any] = {
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "model_calls": 0, "tool_calls": 0, "files_read": 0,
            "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
            "tests_passed": 0, "agent_cycles": 0, "time_to_target": 0,
            "context_waste_ratio": 0.0,
            "tool_schema_bytes": self._estimate_tool_schema_bytes(tools) if tools else 0
        }

        msgs = []
        for m in (response.messages or []):
            raw_tc = getattr(m, "tool_calls", None)
            msgs.append({
                "role": getattr(m, "role", ""),
                "content": str(getattr(m, "content", "") or "")[:4000],
                "tool_calls": json.loads(json.dumps(raw_tc, default=str)) if raw_tc else None,
            })
        
        if self.run_dir:
            log_path = os.path.join(self.run_dir, "agent_messages.json")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(msgs, f, ensure_ascii=False, indent=2)

        if response.metrics:
            metrics_data["input_tokens"] = response.metrics.input_tokens or 0
            metrics_data["output_tokens"] = response.metrics.output_tokens or 0
            metrics_data["cache_read_tokens"] = (
                getattr(response.metrics, "prompt_cache_hit_tokens", 0) or
                getattr(response.metrics, "cache_read_input_tokens", 0) or
                getattr(response.metrics, "cached_tokens", 0) or 0
            )

        if metrics_data["input_tokens"] == 0:
            metrics_data["input_tokens"] = self._count_tokens(task_description)
        
        _read_tool_names = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols", "rg", "grep", "git_grep", "ugrep", "ast_grep"}
        _write_tools = {"patch", "write", "edit", "insert_after"}

        for msg in msgs:
            if msg["role"] == "assistant":
                metrics_data["model_calls"] += 1
            elif msg["role"] == "tool":
                metrics_data["tool_tokens"] += self._count_tokens(str(msg["content"]))
                metrics_data["agent_cycles"] += 1

        for tool_exec in (response.tools or []):
            metrics_data["tool_calls"] += 1
            name = tool_exec.tool_name or ""
            is_error = tool_exec.tool_call_error or str(getattr(tool_exec, "result", "")).startswith("Error:")
            if name in _read_tool_names:
                metrics_data["files_read"] += 1
            elif name in _write_tools and not is_error:
                metrics_data["files_changed"] += 1
            if is_error:
                metrics_data["tool_errors"] += 1

        return metrics_data

    async def _run_with_mcp(
        self,
        task_description: str,
        worktree_path: str,
        test_cmd: str,
        log_path: str | None,
        system_prefix: str = "",
        preingest_sec: float = 0.0,
    ) -> RunMetrics:
        repo_context = f"[Repository path: {worktree_path}]\n\n"
        full_task = repo_context + task_description
        model_id = self._extract_model_id()
        warmup_total = preingest_sec

        try:
            async with contextlib.AsyncExitStack() as stack:
                mcp_tool_instances = []
                for cfg in self.mcp_configs:
                    try:
                        _log.info("Starting MCP server: %s", cfg.tool_name)
                        params = StdioServerParameters(
                            command=cfg.command, 
                            args=cfg.resolve_args(worktree_path), 
                            cwd=worktree_path
                        )
                        stdio_transport = await stack.enter_async_context(stdio_client(params))
                        session = await stack.enter_async_context(ClientSession(stdio_transport[0], stdio_transport[1]))
                        await session.initialize()
                        mcp_inst = MCPTools(session=session)
                        await mcp_inst.initialize()
                        mcp_tool_instances.append(mcp_inst)
                    except Exception as mcp_err:
                        _log.error("Failed to start MCP server %s: %s", cfg.tool_name, mcp_err)
                        # Decide whether to fail fast or continue without this tool
                        # For benchmark reliability, we should probably fail fast
                        raise RuntimeError(f"MCP server {cfg.tool_name} failed to start") from mcp_err

                start_time = time.time()
                agent = self._build_agent(model_id, self._build_agno_tools() + mcp_tool_instances, system_prefix=system_prefix)
                response: RunOutput = await asyncio.wait_for(agent.arun(full_task), timeout=float(self.timeout_sec))

            duration = time.time() - start_time
            metrics_data = self._extract_metrics_from_response(response, task_description, log_path, tools=self._build_agno_tools() + mcp_tool_instances)
            success, tests_passed, tests_failed, patch_lines, exec_result, made_changes, test_stderr, test_stdout = self._validate_run(worktree_path, test_cmd)
            metrics_data.update({"tests_passed": tests_passed, "patch_lines": patch_lines, "errors": tests_failed, "execution_result": exec_result, "made_changes": made_changes})
        except Exception:
            _log.exception("Agno MCP agent execution failed")
            success, duration = False, 0.0
            metrics_data = {}

        run_metrics = RunMetrics(success=success, success_binary=success, eval_score=1.0 if success else 0.0, duration_sec=duration, model_name=self.config.model, warmup_sec=warmup_total, **metrics_data)
        
        # Compute runaway, telemetry, and decomposition flags
        agent_runaway = (
            run_metrics.token_exceeded
            or run_metrics.tool_errors > 10
            or run_metrics.agent_cycles > 40
        )
        telemetry_ok = (run_metrics.total_tokens > 0)
        
        schema_overhead = int((run_metrics.tool_schema_bytes / 4) * run_metrics.model_calls)
        reasoning_tokens = max(run_metrics.total_tokens - schema_overhead, 1)
        net_spt = (1000.0 / reasoning_tokens) if success else 0.0

        return run_metrics.model_copy(update={
            "agent_runaway": agent_runaway,
            "telemetry_ok": telemetry_ok,
            "schema_overhead_tokens": schema_overhead,
        })

    def run(self, task_description: str, worktree_path: str = ".", test_cmd: str = "uv run pytest", log_path: str | None = None, system_prefix: str = "", preingest_sec: float = 0.0) -> RunMetrics:
        if self.mock: return self._run_mock(task_description, time.time())
        if self.mcp_configs:
             return asyncio.run(self._run_with_mcp(task_description, worktree_path, test_cmd, log_path, system_prefix, preingest_sec))

        repo_context = f"[Repository path: {worktree_path}]\n\n"
        full_task = repo_context + task_description
        model_id = self._extract_model_id()
        agent = self._build_agent(model_id, self._build_agno_tools(), system_prefix=system_prefix)
        
        start_time = time.time()
        try:
            response: RunOutput = agent.run(task_description)
            metrics_data = self._extract_metrics_from_response(response, task_description, log_path, tools=self._build_agno_tools())
            success, tests_passed, tests_failed, patch_lines, exec_result, made_changes, test_stderr, test_stdout = self._validate_run(worktree_path, test_cmd)

            metrics_data.update({"tests_passed": tests_passed, "patch_lines": patch_lines, "errors": tests_failed, "execution_result": exec_result, "made_changes": made_changes})
        except Exception:
            _log.exception("Agno agent execution failed")
            success, metrics_data = False, {}
        
        run_metrics = RunMetrics(success=success, success_binary=success, eval_score=1.0 if success else 0.0, duration_sec=time.time() - start_time, model_name=self.config.model, warmup_sec=preingest_sec, **metrics_data)

        # Compute runaway, telemetry, and decomposition flags
        agent_runaway = (
            run_metrics.token_exceeded
            or run_metrics.tool_errors > 10
            or run_metrics.agent_cycles > 40
        )
        telemetry_ok = (run_metrics.total_tokens > 0)

        schema_overhead = int((run_metrics.tool_schema_bytes / 4) * run_metrics.model_calls)
        reasoning_tokens = max(run_metrics.total_tokens - schema_overhead, 1)
        net_spt = (1000.0 / reasoning_tokens) if success else 0.0

        return run_metrics.model_copy(update={
            "agent_runaway": agent_runaway,
            "telemetry_ok": telemetry_ok,
            "schema_overhead_tokens": schema_overhead,
        })

    def _run_mock(self, task_description: str, start_time: float) -> RunMetrics:
        return RunMetrics(
            success=True, success_binary=True, eval_score=1.0,
            input_tokens=self._count_tokens(task_description),
            output_tokens=self._count_tokens("TASK_COMPLETE"),
            tool_tokens=0, duration_sec=time.time() - start_time,
            model_calls=1, tool_calls=0, model_name=self.config.model,
            files_read=0, files_changed=0, patch_lines=0, errors=0, tool_errors=0
        )

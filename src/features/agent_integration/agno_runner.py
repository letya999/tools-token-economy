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
from agno.models.openai import OpenAIChat
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

from src.core.models import AgentConfig, McpServerConfig, RunMetrics
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

        Unlike pre_hooks (which fire once per agent.run in Agno), tool_hooks
        wrap every individual tool invocation — giving real mid-run budget
        enforcement. Raising any exception aborts the run.

        MCP tools are async coroutines. The hook must await them; otherwise
        Agno receives a coroutine object and passes "<coroutine ...>" as the
        tool result to the model — making all MCP search/nav tools blind.
        """
        counter = self._tool_output_token_counter
        count_tok = self._count_tokens

        async def budget_hook(function_name, function_call, arguments):
            # PRE: hard cap on accumulated tool-output tokens (read-loop guard).
            if counter[0] > max_tool_output_tokens:
                raise InputCheckError(
                    f"BUDGET_EXCEEDED: accumulated tool output {counter[0]} tokens "
                    f"exceeds {max_tool_output_tokens} — aborting (read-loop detected)"
                )
            # Execute the real tool — await if it's an async MCP coroutine.
            result = function_call(**arguments)
            if inspect.iscoroutine(result):
                result = await result
            # POST: count output tokens for next call's pre-check.
            try:
                counter[0] += count_tok(str(result))
            except Exception:
                pass
            return result

        return budget_hook

    def _build_budget_pre_hook(self, max_cost_usd: float = 0.50):
        """Returns a pre_hook with three independent budget guards.

        Three parallel fallbacks (any can fire):
        1. Hard model-call counter (MAX_MODEL_CALLS=20) — primary, deterministic.
        2. Cumulative tool-output token counter — accumulator filled by
           tool wrappers via self._tool_output_token_counter. Catches
           read-loop and read_all patterns flooding context.
        3. Per-call context size guard (MAX_PER_CALL_CHARS) — catches single
           explosive read of one huge file.

        Plus the legacy char×20 estimate is kept as a soft signal.

        Must raise InputCheckError — agno's execute_pre_hooks re-raises only
        InputCheckError/OutputCheckError; any other Exception is swallowed.
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

            # Guard 2: accumulated cost across all calls (with correction factor).
            # Accumulating per-call estimates captures the triangular billing growth
            # that results from each call paying for the full accumulated context.
            estimated_tokens = total_chars // 4
            this_call_cost = (estimated_tokens / 1_000_000) * p["input"]
            accumulated_estimated_cost[0] += this_call_cost
            corrected_accumulated = accumulated_estimated_cost[0] * UNDERESTIMATE_CORRECTION
            if corrected_accumulated > max_cost_usd:
                _log.warning(
                    "Budget pre-hook: accumulated corrected cost $%.4f exceeds limit $%.2f "
                    "(raw accumulated $%.6f, call %d)",
                    corrected_accumulated, max_cost_usd, accumulated_estimated_cost[0], call_count[0],
                )
                raise InputCheckError(
                    f"Pre-hook aborted: accumulated estimated cost ${corrected_accumulated:.4f} "
                    f"exceeds per-config limit ${max_cost_usd:.2f}"
                )

            # Guard 3: per-call context size (400KB ≈ 100K tokens per single call).
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
            "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
            "MANDATORY: You MUST call at least one file-modification tool to save your code changes to disk before saying TASK_COMPLETE.",
            (
                "Write tool guide — choose the right tool for each job:\n"
                "  edit         — str_replace: replace an EXACT substring in an existing file. Best for modifying existing code.\n"
                "  insert       — line-number insert (SWE-agent style): read the file first to get line numbers, then call insert(file, line_number, new_code) to add code AFTER that line. Best for adding new functions/tests.\n"
                "  append       — appends new_code to the very END of the file. Simplest way to add a new test or function — no line number or anchor needed.\n"
                "  patch        — apply a unified diff. Use when you already have a precise diff.\n"
                "  write        — rewrites the ENTIRE file. Only for new files or when >50% of content changes.\n"
                "WORKFLOW for adding a new test: (1) read the test file, (2) use append(file, new_test_code) — it always adds at the end safely.\n"
                "NEVER use insert_after with a function def line as anchor — it places code inside the body."
            ),
            "Workflow: (1) Retrieve context. (2) Save changes with the appropriate tool above. (3) Verify by reading back. (4) Output exactly: TASK_COMPLETE",
            "If a tool returns an error, try a different approach — do not repeat the exact same tool call.",
            "CRITICAL: NEVER delete, truncate, or overwrite existing code. When adding to an existing file, preserve ALL existing content.",
            "CRITICAL: NEVER remove or replace existing tests. You must ADD new tests at the END of the test file, after all existing tests.",
            "CRITICAL: New tests MUST be written as proper pytest functions: `def test_name():`. NEVER write bare assert statements outside a function body — they cause SyntaxError during pytest collection.",
            "CONVERGENCE RULE: After reading 3-5 relevant files you have enough context. STOP exploring and START writing your fix immediately. Do not spend more than half your tool budget on retrieval — the other half must be for writing and verifying.",
            "Read files in LARGE blocks (at least 100-200 lines per read call). Do NOT read the same file in small chunks of 20-30 lines.",
            "Efficiency: Use the shell tool's multi_cmd parameter to run multiple related commands in a single turn.",
        ])

        budget_hook = self._build_budget_pre_hook(max_cost_usd=self.max_config_cost_usd)

        # Guard #4 (Agno-built-in): hard ceiling on total tool calls across run.
        # This is THE primary budget control — Agno's pre_hooks fire once per run,
        # not per model call, so the in-hook counters don't trigger mid-run.
        # tool_call_limit IS enforced across the run by Agno.
        AGNO_TOOL_CALL_HARD_CAP = 50
        effective_tool_cap = min(effective_limit, AGNO_TOOL_CALL_HARD_CAP)

        # Schema bloat: each tool's name+docstring is replicated in every prompt.
        # Log per-archetype total bytes — relevant for prompt-cache analysis.
        try:
            schema_bytes = 0
            for fn in tools:
                fn_name = getattr(fn, "name", None) or getattr(fn, "__name__", "?")
                fn_doc = getattr(fn, "description", None) or getattr(fn, "__doc__", "") or ""
                schema_bytes += len(fn_name.encode("utf-8")) + len(fn_doc.encode("utf-8"))
            self._tool_schema_bytes = schema_bytes
            _log.info("Tool schema bloat: ~%d bytes across %d tools", schema_bytes, len(tools))
        except Exception:
            self._tool_schema_bytes = 0

        budget_tool_hook = self._build_budget_tool_hook(max_tool_output_tokens=150_000)

        return Agent(
            model=OpenAIChat(id=model_id, max_tokens=4096, seed=self.seed if self.seed is not None else 42),
            tools=tools,
            instructions=instructions,
            markdown=False,
            tool_call_limit=effective_tool_cap,
            pre_hooks=[budget_hook],
            tool_hooks=[budget_tool_hook],
        )

    def _validate_run(self, worktree_path: str, test_cmd: str) -> tuple[bool, int, int, int, str, bool, str]:
        """
        Validates the run using ExecutionValidator.
        Returns (success, tests_passed, tests_failed, patch_lines, execution_result, made_changes, test_stderr).
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

        return success, res.tests_passed, res.tests_failed, patch_lines, res.outcome, made_changes, res.stderr, res.stdout

    def _extract_metrics_from_response(
        self,
        response: RunOutput,
        task_description: str,
        log_path: str | None,
    ) -> dict[str, Any]:
        metrics_data: dict[str, Any] = {
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
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
            metrics_data["cache_read_tokens"] = getattr(response.metrics, "cache_read_tokens", 0) or 0
            metrics_data["cache_write_tokens"] = getattr(response.metrics, "cache_write_tokens", 0) or 0

        # Sanity check: if we have huge input tokens but zero message trace, something went wrong
        if (metrics_data["input_tokens"] > 200_000 and 
            not any(m.get("role") == "assistant" for m in msgs)):
            _log.error(
                "PHANTOM TOKENS DETECTED: input_tokens=%d but no assistant messages in trace. "
                "Likely agno internal retry or exception during model call. "
                "Setting execution_result=telemetry_corrupt.",
                metrics_data["input_tokens"]
            )
            metrics_data["execution_result"] = "telemetry_corrupt"
            # Zero out the phantom tokens so cost_usd is not inflated
            metrics_data["input_tokens"] = 0
            metrics_data["output_tokens"] = 0

        content_str = (
            response.get_content_as_string()
            if hasattr(response, "get_content_as_string")
            else (str(response.content) if response.content else "")
        )
        # Only use fallback token counts when telemetry is healthy — don't overwrite
        # the intentional zeros set by the PHANTOM TOKENS handler above.
        if metrics_data["input_tokens"] == 0 and metrics_data.get("execution_result") != "telemetry_corrupt":
            metrics_data["input_tokens"] = self._count_tokens(task_description)
        if metrics_data["output_tokens"] == 0 and metrics_data.get("execution_result") != "telemetry_corrupt":
            metrics_data["output_tokens"] = self._count_tokens(content_str)

        _read_tool_names = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols",
                            "rg", "grep", "git_grep", "ugrep", "ast_grep"}
        _write_tools = {"patch", "write", "edit", "insert_after"}

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
                args = tool_exec.tool_args or {}
                file_arg = (
                    args.get("path") or args.get("file_path") or
                    args.get("query") or args.get("pattern") or ""
                )
                if file_arg and self.required_files and any(
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
        metrics_data["tool_output_tokens_total"] = (
            self._tool_output_token_counter[0]
            if hasattr(self, "_tool_output_token_counter") else 0
        )
        metrics_data["tool_schema_bytes"] = getattr(self, "_tool_schema_bytes", 0)

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
        if not os.getenv("OPENAI_API_KEY"):
            raise OSError("OPENAI_API_KEY not set in environment.")

        repo_context = f"[Repository path: {worktree_path}]\n\n"
        full_task = repo_context + task_description

        model_id = self._extract_model_id()
        success = False
        metrics_data: dict[str, Any] = {}
        warmup_total = preingest_sec  # include orchestrator pre-ingest time
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
                t_mcp_init = time.time()
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
                if self.mcp_configs:
                    warmup_total += time.time() - t_mcp_init

                # MCP Warmup calls
                for mcp_cfg, session in zip(self.mcp_configs, sessions_list, strict=False):
                    if mcp_cfg.warmup_call:
                        _log.info("Warming up MCP tool: %s", mcp_cfg.tool_name)
                        t_w = time.time()
                        try:
                            await session.call_tool(mcp_cfg.warmup_call, mcp_cfg.resolve_warmup_args(worktree_path))
                        except Exception as e:
                            _log.warning("MCP warmup call failed for %s: %s", mcp_cfg.tool_name, e)
                        warmup_total += time.time() - t_w

                start_time = time.time()
                all_tools = self._build_agno_tools() + mcp_tool_instances
                agent = self._build_agent(model_id, all_tools, system_prefix=system_prefix)

                await asyncio.to_thread(lambda: self._rate_limiter.__enter__())
                _ab_active = False
                _has_mcp_semantic = any(
                    c.tool_name in ("serena", "semble") for c in self.mcp_configs
                )
                if _HAS_AGENTBUDGET and not _has_mcp_semantic:
                    try:
                        agentbudget.init(
                            self.max_config_cost_usd,
                            soft_limit=0.9,
                            max_repeated_calls=50,
                        )
                        _ab_active = True
                    except Exception as _abe:
                        _log.warning("agentbudget.init failed: %s", _abe)
                try:
                    response: RunOutput = await asyncio.wait_for(
                            agent.arun(full_task),
                            timeout=float(self.timeout_sec),
                        )
                finally:
                    if _ab_active:
                        try:
                            _log.info("agentbudget spent: $%.4f", agentbudget.spent())
                            agentbudget.teardown()
                        except Exception:
                            pass
                    await asyncio.to_thread(lambda: self._rate_limiter.__exit__(None, None, None))

            duration = time.time() - start_time
            metrics_data = self._extract_metrics_from_response(response, task_description, log_path)

            if worktree_path and os.path.isdir(worktree_path):
                success, tests_passed, tests_failed, patch_lines, exec_result, made_changes, test_stderr, test_stdout = self._validate_run(worktree_path, test_cmd)
                metrics_data["tests_passed"] = tests_passed
                metrics_data["patch_lines"] = patch_lines
                metrics_data["errors"] = tests_failed
                if metrics_data.get("execution_result") != "telemetry_corrupt":
                    metrics_data["execution_result"] = exec_result
                metrics_data["made_changes"] = made_changes
                metrics_data["test_stderr"] = test_stderr[-500:] if test_stderr else ""
                metrics_data["test_stdout"] = test_stdout[-1000:] if test_stdout else ""
            else:
                content_str = (
                    response.get_content_as_string()
                    if hasattr(response, "get_content_as_string")
                    else (str(response.content) if response.content else "")
                )
                success = "TASK_COMPLETE" in content_str

        except BudgetExceededError:
            _log.warning("Budget pre-hook aborted agent run")
            success = False
            duration = time.time() - start_time
            if "execution_result" not in metrics_data:
                metrics_data["execution_result"] = "budget_exceeded"
        except BudgetExhausted as _be:
            _log.warning("AgentBudget SDK-level budget exhausted: %s", _be)
            success = False
            duration = time.time() - start_time
            if "execution_result" not in metrics_data:
                metrics_data["execution_result"] = "budget_exhausted_sdk"
        except LoopDetected as _ld:
            _log.warning("AgentBudget loop detected: %s", _ld)
            success = False
            duration = time.time() - start_time
            if "execution_result" not in metrics_data:
                metrics_data["execution_result"] = "loop_detected"
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
            **{
                "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
                "model_calls": 0, "tool_calls": 0, "files_read": 0,
                "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
                "tests_passed": 0, "execution_result": "not_verified", "made_changes": False,
                **metrics_data,
            },
        )

    def run(self, task_description: str, worktree_path: str = ".", test_cmd: str = "uv run pytest", log_path: str | None = None, system_prefix: str = "", preingest_sec: float = 0.0) -> RunMetrics:
        """Execute task via Agno Agent."""
        mock_start = time.time()
        if self.mock:
            return self._run_mock(task_description, mock_start)

        warmup_total = preingest_sec

        # Warm up RAG tools only if not already pre-ingested by the orchestrator.
        if not self.mcp_configs:
            for tool in self.tools:
                if hasattr(tool, "_init_rag") and not getattr(tool, "_ingested", False):
                    _log.info("Warming up RAG tool (not pre-ingested): %s", tool.name)
                    t_w = time.time()
                    try:
                        tool._init_rag()  # type: ignore[attr-defined]
                    except Exception as e:
                        _log.warning("RAG warm-up failed: %s", e)
                    warmup_total += time.time() - t_w

        if self.mcp_configs:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._run_with_mcp(task_description, worktree_path, test_cmd, log_path, system_prefix=system_prefix, preingest_sec=preingest_sec),
                    )
                    return future.result()
            return asyncio.run(self._run_with_mcp(task_description, worktree_path, test_cmd, log_path, system_prefix=system_prefix, preingest_sec=preingest_sec))

        if not os.getenv("OPENAI_API_KEY"):
            raise OSError("OPENAI_API_KEY not set in environment.")

        repo_context = f"[Repository path: {worktree_path}]\n\n"
        full_task = repo_context + task_description

        model_id = self._extract_model_id()
        agno_tools_list = self._build_agno_tools()
        agent = self._build_agent(model_id, agno_tools_list, system_prefix=system_prefix)
        _log.info("Agent starting: model=%s tools=%d timeout=%ss", model_id, len(agno_tools_list), self.timeout_sec)

        start_time = time.time()  # agent clock starts after warmup
        success = False
        metrics_data: dict[str, Any] = {}
        _ab_active = False
        _has_mcp_semantic = any(
            c.tool_name in ("serena", "semble") for c in self.mcp_configs
        )
        if _HAS_AGENTBUDGET and not _has_mcp_semantic:
            try:
                agentbudget.init(
                    self.max_config_cost_usd,
                    soft_limit=0.9,
                    max_repeated_calls=50,
                )
                _ab_active = True
            except Exception as _abe:
                _log.warning("agentbudget.init failed: %s", _abe)
        try:
            with self._rate_limiter:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                    _future = _pool.submit(agent.run, full_task)
                    response: RunOutput = _future.result(timeout=self.timeout_sec)
            _log.info("Agent finished: model=%s", model_id)

            metrics_data = self._extract_metrics_from_response(response, task_description, log_path)

            if worktree_path and os.path.isdir(worktree_path):
                success, tests_passed, tests_failed, patch_lines, exec_result, made_changes, test_stderr, test_stdout = self._validate_run(worktree_path, test_cmd)
                metrics_data["tests_passed"] = tests_passed
                metrics_data["patch_lines"] = patch_lines
                metrics_data["errors"] = tests_failed
                if metrics_data.get("execution_result") != "telemetry_corrupt":
                    metrics_data["execution_result"] = exec_result
                metrics_data["made_changes"] = made_changes
                metrics_data["test_stderr"] = test_stderr[-500:] if test_stderr else ""
                metrics_data["test_stdout"] = test_stdout[-1000:] if test_stdout else ""
            else:
                content_str = (
                    response.get_content_as_string()
                    if hasattr(response, "get_content_as_string")
                    else (str(response.content) if response.content else "")
                )
                success = "TASK_COMPLETE" in content_str

        except BudgetExceededError:
            _log.warning("Budget pre-hook aborted agent run")
            success = False
            if "execution_result" not in metrics_data:
                metrics_data["execution_result"] = "budget_exceeded"
        except BudgetExhausted as _be:
            _log.warning("AgentBudget SDK-level budget exhausted: %s", _be)
            success = False
            if "execution_result" not in metrics_data:
                metrics_data["execution_result"] = "budget_exhausted_sdk"
        except LoopDetected as _ld:
            _log.warning("AgentBudget loop detected: %s", _ld)
            success = False
            if "execution_result" not in metrics_data:
                metrics_data["execution_result"] = "loop_detected"
        except concurrent.futures.TimeoutError:
            _log.warning("Agent sync run timed out after %ss", self.timeout_sec)
            success = False
        except Exception:
            _log.exception("Agno agent execution failed")
            success = False
        finally:
            if _ab_active:
                try:
                    _log.info("agentbudget spent: $%.4f", agentbudget.spent())
                    agentbudget.teardown()
                except Exception:
                    pass

        duration = time.time() - start_time
        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            duration_sec=duration,
            model_name=self.config.model,
            warmup_sec=warmup_total,
            **{
                "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
                "model_calls": 0, "tool_calls": 0, "files_read": 0,
                "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
                "tests_passed": 0, "execution_result": "not_verified", "made_changes": False,
                **metrics_data,
            },
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

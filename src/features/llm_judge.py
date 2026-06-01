import json
import logging
import os
import statistics
import time
from typing import Any
from datetime import datetime

from pydantic import BaseModel
from src.core.models import JudgeConfig
from src.core.provider_factory import build_agent_model

logger = logging.getLogger("LLMJudge")

_READ_TOOLS = {"read", "read_file", "read_all"}
_PATH_KEYS = ("path", "file_path", "filename", "filepath")


def compute_retrieval_metrics(
    agent_messages: list[dict],
    required_files: list[str],
) -> tuple[float, float]:
    """
    precision = (files agent read that are in required_files) / (all files agent read)
    recall    = (required_files that agent read) / len(required_files)

    Both return 0.0 when there are no reads or no required_files.
    """
    files_read: set[str] = set()
    for msg in agent_messages:
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        for call in msg["tool_calls"]:
            if isinstance(call, dict):
                func = call.get("function", {})
                name = func.get("name", "")
                args_str = func.get("arguments", "{}")
            else:
                name = call.function.name
                args_str = call.function.arguments

            if name not in _READ_TOOLS:
                continue

            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                for key in _PATH_KEYS:
                    if key in args:
                        p = str(args[key]).replace("\\", "/").lstrip("./")
                        files_read.add(p)
                        break
            except Exception:
                pass

    if not required_files or not files_read:
        return 0.0, 0.0

    req = {f.replace("\\", "/").lstrip("./") for f in required_files}
    relevant = files_read & req

    precision = len(relevant) / len(files_read)
    recall = len(relevant) / len(req)
    return round(precision, 4), round(recall, 4)


class JudgeReport(BaseModel):
    task_solved_score: float = 0.0
    task_solved_reasoning: str = ""
    tool_correctness_score: float = 0.0
    tool_correctness_reasoning: str = ""
    context_quality_score: float = 0.0
    context_quality_reasoning: str = ""
    correctness_score: float = 0.0
    correctness_reasoning: str = ""
    minimality_score: float = 0.0
    minimality_reasoning: str = ""
    pattern_adherence_score: float = 0.0
    pattern_adherence_reasoning: str = ""
    tool_sequence_score: float = 0.0
    tool_sequence_reasoning: str = ""
    judge_model: str = ""
    # Token & Cost tracking
    judge_cost_usd: float = 0.0
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0
    judge_skipped: bool = False


class LLMJudge:
    _TASK_SYSTEM = (
        "You are an objective evaluator for a software engineering benchmark.\n"
        "You will be shown: a task description, success criteria, the git diff of changes made by an AI agent, and execution results.\n"
        'Return ONLY a JSON object with two fields: "score" (float 0.0 to 1.0) and "reasoning" (1-2 sentences).\n'
        "Score 1.0 = task fully solved according to ALL criteria. Score 0.0 = task not attempted or completely wrong.\n"
        "Be strict: partial solutions that miss key requirements score 0.3-0.6.\n"
        "If the agent only explained what to do but made no code changes, score MUST be 0.0."
    )

    _TOOLS_SYSTEM = (
        "You are an objective evaluator for a software engineering benchmark.\n"
        "You will be shown: the list of tools the agent was supposed to use, and the actual sequence of tool calls.\n"
        'Return ONLY a JSON object with two fields: "score" (float 0.0 to 1.0) and "reasoning" (1-2 sentences).\n'
        "Score 1.0 = all prescribed tools were used meaningfully.\n"
        "Score 0.0 = prescribed tools entirely ignored."
    )

    _CONTEXT_SYSTEM = (
        "You are an objective evaluator for a software engineering benchmark.\n"
        "You will be shown: the task description, required files, and the agent's tool calls.\n"
        'Return ONLY a JSON object: {"score": float, "reasoning": "1-2 sentences"}\n\n'
        "Scoring rubric (use values 0.0/0.25/0.5/0.75/1.0):\n"
        "1.0 = Agent read exactly the required files. No irrelevant files.\n"
        "0.75 = Good retrieval with minimal noise.\n"
        "0.5 = Found target but read many irrelevant files.\n"
        "0.0 = Missed required files or hallucinated."
    )

    _CORRECTNESS_SYSTEM = (
        "Evaluate code correctness. Return ONLY a JSON object: {\"score\": float, \"reasoning\": \"1-2 sentences\"}\n"
        "1.0 = correct. 0.0 = broken."
    )

    _MINIMALITY_SYSTEM = (
        "Evaluate change minimality. Return ONLY a JSON object: {\"score\": float, \"reasoning\": \"1-2 sentences\"}\n"
        "1.0 = minimal. 0.0 = bloated."
    )

    _PATTERN_ADHERENCE_SYSTEM = (
        "Evaluate pattern adherence. Return ONLY a JSON object: {\"score\": float, \"reasoning\": \"1-2 sentences\"}\n"
        "1.0 = adhered. 0.0 = deviated."
    )

    _TOOL_SEQUENCE_SYSTEM = (
        "Evaluate tool sequence logic. Return ONLY a JSON object: {\"score\": float, \"reasoning\": \"1-2 sentences\"}\n"
        "1.0 = logical. 0.0 = chaotic."
    )

    def __init__(
        self, 
        judge_config: JudgeConfig | None = None, 
        judge_model: str | None = None,
        max_judge_usd: float = 1.0,
        run_dir: str | None = None
    ):
        from src.core.models import ProviderConfig
        if judge_config is not None:
            self.cfg = judge_config
        else:
            self.cfg = JudgeConfig(
                model=judge_model or os.getenv("JUDGE_MODEL", "gpt-5.4-nano")
            )
        
        p_cfg = ProviderConfig(
            provider=self.cfg.provider,
            model=self.cfg.model,
            api_base=self.cfg.api_base,
            api_key_env=self.cfg.api_key_env,
            temperature=self.cfg.temperature
        )
        self.model = build_agent_model(p_cfg)
        self.judge_model = f"{self.cfg.provider}/{self.cfg.model}"
        self.max_judge_usd = max_judge_usd
        self.run_dir = run_dir
        
        # Internal log for judge_log.json
        self._judge_calls_log = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0

    def _get_pricing(self):
        """Returns pricing for current judge model."""
        # Defaults to gpt-5.4-nano pricing per plan
        return {"input": 0.20, "output": 1.25}

    def _call_model(self, criterion: str, system: str, user: str) -> dict[str, Any]:
        """Call the Agno model with self-consistency (median of N)."""
        samples = []
        pricing = self._get_pricing()
        
        for _ in range(self.cfg.self_consistency):
            try:
                from agno.models.message import Message
                msgs = [
                    Message(role="system", content=system),
                    Message(role="user", content=user)
                ]
                resp = self.model.response(msgs)
                content = resp.content
                
                # Extract tokens (guard against MagicMock in tests)
                try:
                    itok = int(getattr(resp.metrics, "input_tokens", 0) or 0)
                    otok = int(getattr(resp.metrics, "output_tokens", 0) or 0)
                except (TypeError, ValueError):
                    itok = otok = 0
                cost = (itok / 1_000_000 * pricing["input"]) + (otok / 1_000_000 * pricing["output"])
                
                self._total_input_tokens += itok
                self._total_output_tokens += otok
                self._total_cost_usd += cost

                # Robust JSON extraction
                json_content = content
                if "```json" in content:
                    json_content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    json_content = content.split("```")[1].split("```")[0].strip()
                
                data = json.loads(json_content)
                samples.append(data)
                
                # Log this call
                self._judge_calls_log.append({
                    "criterion": criterion,
                    "prompt": user,
                    "response_raw": content,
                    "score": data.get("score", 0.0),
                    "reasoning": data.get("reasoning", ""),
                    "input_tokens": itok,
                    "output_tokens": otok,
                    "cost_usd": cost,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.warning("Judge sample failed: %s", e)
                self._judge_calls_log.append({
                    "criterion": criterion,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })
        
        if not samples:
            return {"score": 0.0, "reasoning": "judge failed all samples"}
        
        if len(samples) == 1:
            return samples[0]
            
        # Median score
        scores = [float(s.get("score", 0.0)) for s in samples]
        median_score = statistics.median(scores)
        best_sample = min(samples, key=lambda s: abs(float(s.get("score", 0.0)) - median_score))
        best_sample["score"] = median_score
        return best_sample

    def evaluate(
        self,
        task_description: str,
        agent_messages: list[dict],
        patch: str | None,
        config_tools: list[str],
        tests_passed: int,
        tests_total: int,
        success: bool,
        execution_result: str = "not_verified",
        success_criteria: list[str] | None = None,
        required_files: list[str] | None = None,
        detailed: bool = True,
    ) -> JudgeReport:
        api_key = os.getenv(self.cfg.api_key_env)
        if not api_key:
            logger.warning(f"{self.cfg.api_key_env} not set. Skipping LLM judge evaluation.")
            return JudgeReport(
                task_solved_reasoning="judge skipped: no API key",
                tool_correctness_reasoning="judge skipped: no API key",
                context_quality_reasoning="judge skipped: no API key",
                correctness_reasoning="judge skipped: no API key",
                minimality_reasoning="judge skipped: no API key",
                pattern_adherence_reasoning="judge skipped: no API key",
                tool_sequence_reasoning="judge skipped: no API key",
                judge_model="skipped",
                judge_skipped=True
            )

        rep = JudgeReport(judge_model=self.judge_model)
        
        criteria_calls = [
            ("task_solved", self._TASK_SYSTEM, (
                f"TASK:\n{task_description}\n\n"
                f"CRITERIA:\n{json.dumps(success_criteria or [], indent=2)}\n\n"
                f"STATUS: {execution_result}\n"
                f"RESULTS: {tests_passed}/{tests_total} passed. Success: {success}\n\n"
                f"DIFF:\n{patch or '(none)'}"
            )),
            ("tool_correctness", self._TOOLS_SYSTEM, f"PRESCRIBED: {config_tools}\nACTUAL: {json.dumps(agent_messages, default=str)[:10000]}"),
            ("context_quality", self._CONTEXT_SYSTEM, f"TASK: {task_description}\nREQUIRED: {required_files}\nCALLS: {json.dumps(agent_messages, default=str)[:10000]}"),
        ]
        
        if detailed:
            criteria_calls.extend([
                ("correctness", self._CORRECTNESS_SYSTEM, f"DIFF:\n{patch}"),
                ("minimality", self._MINIMALITY_SYSTEM, f"DIFF:\n{patch}"),
                ("pattern_adherence", self._PATTERN_ADHERENCE_SYSTEM, f"DIFF:\n{patch}"),
                ("tool_sequence", self._TOOL_SEQUENCE_SYSTEM, f"CALLS:\n{json.dumps(agent_messages, default=str)[:5000]}"),
            ])

        for crit, system, user in criteria_calls:
            if self._total_cost_usd >= self.max_judge_usd:
                logger.warning("Judge budget exceeded ($%.4f >= $%.4f). Skipping remaining criteria.", self._total_cost_usd, self.max_judge_usd)
                rep.judge_skipped = True
                break
            
            res = self._call_model(crit, system, user)
            score = res.get("score", 0.0)
            reason = res.get("reasoning", "")
            
            if crit == "task_solved":
                rep.task_solved_score = score
                rep.task_solved_reasoning = reason
            elif crit == "tool_correctness":
                rep.tool_correctness_score = score
                rep.tool_correctness_reasoning = reason
            elif crit == "context_quality":
                rep.context_quality_score = score
                rep.context_quality_reasoning = reason
            elif crit == "correctness":
                rep.correctness_score = score
                rep.correctness_reasoning = reason
            elif crit == "minimality":
                rep.minimality_score = score
                rep.minimality_reasoning = reason
            elif crit == "pattern_adherence":
                rep.pattern_adherence_score = score
                rep.pattern_adherence_reasoning = reason
            elif crit == "tool_sequence":
                rep.tool_sequence_score = score
                rep.tool_sequence_reasoning = reason

        rep.judge_cost_usd = self._total_cost_usd
        rep.judge_input_tokens = self._total_input_tokens
        rep.judge_output_tokens = self._total_output_tokens
        
        # Save judge log
        if self.run_dir and os.path.isdir(self.run_dir):
            try:
                log_path = os.path.join(self.run_dir, "judge_log.json")
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(self._judge_calls_log, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning("Failed to save judge log: %s", e)

        return rep

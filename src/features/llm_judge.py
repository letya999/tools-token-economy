import json
import logging
import os
import statistics
from typing import Any

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

    def __init__(self, judge_config: JudgeConfig | None = None, judge_model: str | None = None):
        from src.core.models import ProviderConfig
        if judge_config is not None:
            self.cfg = judge_config
        else:
            self.cfg = JudgeConfig(
                model=judge_model or os.getenv("JUDGE_MODEL", "gpt-5.1-mini")
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

    def _call_model(self, system: str, user: str) -> dict[str, Any]:
        """Call the Agno model with self-consistency (median of N)."""
        samples = []
        for _ in range(self.cfg.self_consistency):
            try:
                # Agno models expect a list of messages or a single prompt string.
                # We use the underlying model instance for direct chat.
                from agno.models.message import Message
                msgs = [
                    Message(role="system", content=system),
                    Message(role="user", content=user)
                ]
                resp = self.model.response(msgs)
                content = resp.content
                # Robust JSON extraction
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                data = json.loads(content)
                samples.append(data)
            except Exception as e:
                logger.warning("Judge sample failed: %s", e)
        
        if not samples:
            return {"score": 0.0, "reasoning": "judge failed all samples"}
        
        if len(samples) == 1:
            return samples[0]
            
        # Median score
        scores = [float(s.get("score", 0.0)) for s in samples]
        median_score = statistics.median(scores)
        # Find sample closest to median for reasoning
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
        # Restore API key check for test compatibility and safety
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
            )

        task_user = (
            f"TASK:\n{task_description}\n\n"
            f"CRITERIA:\n{json.dumps(success_criteria or [], indent=2)}\n\n"
            f"STATUS: {execution_result}\n"
            f"RESULTS: {tests_passed}/{tests_total} passed. Success: {success}\n\n"
            f"DIFF:\n{patch or '(none)'}"
        )
        task_res = self._call_model(self._TASK_SYSTEM, task_user)

        tool_user = f"PRESCRIBED: {config_tools}\nACTUAL: {json.dumps(agent_messages, default=str)[:10000]}"
        tool_res = self._call_model(self._TOOLS_SYSTEM, tool_user)

        ctx_user = f"TASK: {task_description}\nREQUIRED: {required_files}\nCALLS: {json.dumps(agent_messages, default=str)[:10000]}"
        ctx_res = self._call_model(self._CONTEXT_SYSTEM, ctx_user)

        rep = JudgeReport(
            task_solved_score=task_res.get("score", 0.0),
            task_solved_reasoning=task_res.get("reasoning", ""),
            tool_correctness_score=tool_res.get("score", 0.0),
            tool_correctness_reasoning=tool_res.get("reasoning", ""),
            context_quality_score=ctx_res.get("score", 0.0),
            context_quality_reasoning=ctx_res.get("reasoning", ""),
            judge_model=self.judge_model
        )

        if detailed:
            # Shortened calls for brevity in this implementer phase
            c_res = self._call_model(self._CORRECTNESS_SYSTEM, f"DIFF:\n{patch}")
            m_res = self._call_model(self._MINIMALITY_SYSTEM, f"DIFF:\n{patch}")
            p_res = self._call_model(self._PATTERN_ADHERENCE_SYSTEM, f"DIFF:\n{patch}")
            s_res = self._call_model(self._TOOL_SEQUENCE_SYSTEM, f"CALLS:\n{json.dumps(agent_messages, default=str)[:5000]}")
            
            rep.correctness_score = c_res.get("score", 0.0)
            rep.correctness_reasoning = c_res.get("reasoning", "")
            rep.minimality_score = m_res.get("score", 0.0)
            rep.minimality_reasoning = m_res.get("reasoning", "")
            rep.pattern_adherence_score = p_res.get("score", 0.0)
            rep.pattern_adherence_reasoning = p_res.get("reasoning", "")
            rep.tool_sequence_score = s_res.get("score", 0.0)
            rep.tool_sequence_reasoning = s_res.get("reasoning", "")

        return rep

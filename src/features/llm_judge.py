import json
import logging
import os

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger("LLMJudge")


class JudgeReport(BaseModel):
    task_solved_score: float = 0.0
    task_solved_reasoning: str = ""
    tool_correctness_score: float = 0.0
    tool_correctness_reasoning: str = ""
    judge_model: str = ""


class LLMJudge:
    _TASK_SYSTEM = (
        "You are an objective evaluator for a software engineering benchmark.\n"
        "You will be shown: a task description, the git diff of changes made by an AI agent, and execution results.\n"
        'Return ONLY a JSON object with two fields: "score" (float 0.0 to 1.0) and "reasoning" (1-2 sentences).\n'
        "Score 1.0 = task fully solved. Score 0.0 = task not attempted or completely wrong.\n"
        "Be strict: partial solutions that miss key requirements score 0.3-0.6.\n"
        "If the agent only explained what to do but made no code changes, score MUST be 0.0."
    )

    _TOOLS_SYSTEM = (
        "You are an objective evaluator for a software engineering benchmark.\n"
        "You will be shown: the list of tools the agent was supposed to use, and the actual sequence of retrieval/navigation tool calls the agent made.\n"
        'Return ONLY a JSON object with two fields: "score" (float 0.0 to 1.0) and "reasoning" (1-2 sentences).\n'
        "Score 1.0 = all prescribed tools were used meaningfully and in a sensible workflow.\n"
        "Score 0.5 = some tools used but others ignored or misused.\n"
        "Score 0.0 = prescribed tools entirely ignored.\n"
        "Note: Common tools like 'write', 'patch', and 'shell' have been filtered out of the list to focus on retrieval strategy."
    )

    def __init__(self, judge_model: str | None = None):
        self.judge_model = judge_model or os.getenv("JUDGE_MODEL", "gpt-4.1-mini")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None

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
    ) -> JudgeReport:
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set. Skipping LLM judge evaluation.")
            return JudgeReport(
                task_solved_reasoning="judge skipped: no API key",
                tool_correctness_reasoning="judge skipped: no API key",
                judge_model="skipped",
            )

        task_score, task_reasoning = self._judge_task_solved(
            task_description, patch, tests_passed, tests_total, success, execution_result
        )
        tool_score, tool_reasoning = self._judge_tool_correctness(config_tools, agent_messages)

        return JudgeReport(
            task_solved_score=task_score,
            task_solved_reasoning=task_reasoning,
            tool_correctness_score=tool_score,
            tool_correctness_reasoning=tool_reasoning,
            judge_model=self.judge_model,
        )

    def _judge_task_solved(
        self,
        task_description: str,
        patch: str | None,
        tests_passed: int,
        tests_total: int,
        success: bool,
        execution_result: str = "not_verified",
    ) -> tuple[float, str]:
        user_message = (
            f"TASK:\n{task_description}\n\n"
            f"EXECUTION STATUS: {execution_result}\n"
            f"EXECUTION RESULTS: {tests_passed} passed, {tests_total - tests_passed} failed/error. Overall Success: {success}\n\n"
            f"GIT DIFF (changes made by agent):\n{patch or '(no changes made)'}"
        )
        # Truncate very large patches to avoid context overflow
        if len(user_message) > 60000:
            user_message = user_message[:55000] + "\n... [TRUNCATED]"
            
        try:
            response = self.client.chat.completions.create(
                model=self.judge_model,
                messages=[
                    {"role": "system", "content": self._TASK_SYSTEM},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
            return float(data.get("score", 0.0)), str(data.get("reasoning", ""))
        except Exception as exc:
            logger.warning("Task solved judge call failed: %s", exc)
            return 0.0, f"judge call failed: {exc}"

    def _judge_tool_correctness(
        self,
        config_tools: list[str],
        agent_messages: list[dict],
    ) -> tuple[float, str]:
        _ignore_tools = {"write", "patch", "insert_after", "shell"}
        tool_call_sequence = []
        for msg in agent_messages:
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            for call in msg["tool_calls"]:
                if isinstance(call, dict):
                    func = call.get("function", {})
                    name = func.get("name", "unknown")
                    args = func.get("arguments", "{}")
                else:
                    name = call.function.name
                    args = call.function.arguments
                
                if name in _ignore_tools:
                    continue
                    
                # Truncate args to keep JSON manageable
                tool_call_sequence.append({"tool": name, "args": str(args)[:150]})

        user_message = (
            f"PRESCRIBED TOOLS FOR THIS CONFIG: {config_tools}\n\n"
            f"ACTUAL TOOL CALLS MADE (in order):\n"
            f"{json.dumps(tool_call_sequence, indent=2)}"
        )
        if len(user_message) > 60000:
             user_message = user_message[:55000] + "\n... [TRUNCATED]"

        try:
            response = self.client.chat.completions.create(
                model=self.judge_model,
                messages=[
                    {"role": "system", "content": self._TOOLS_SYSTEM},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
            return float(data.get("score", 0.0)), str(data.get("reasoning", ""))
        except Exception as exc:
            logger.warning("Tool correctness judge call failed: %s", exc)
            return 0.0, f"judge call failed: {exc}"

import os
import unittest
from unittest.mock import MagicMock, patch

from src.features.llm_judge import LLMJudge, JudgeReport
from src.core.models import JudgeConfig

class TestLLMJudge(unittest.TestCase):
    def setUp(self):
        self.task_description = "Fix the bug in the parser."
        self.agent_messages = [
            {"role": "user", "content": "Help me fix the bug."},
            {"role": "assistant", "content": "I will use rg to find it.", "tool_calls": [
                {"function": {"name": "rg", "arguments": '{"pattern": "bug"}'}}
            ]}
        ]
        self.patch_content = "diff --git a/file.py b/file.py\n-bug\n+fix"
        self.config_tools = ["rg", "read", "write"]

    @patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_judge_returns_zeroed_report_when_no_api_key(self):
        judge = LLMJudge()
        report = judge.evaluate(
            self.task_description,
            self.agent_messages,
            self.patch_content,
            self.config_tools,
            tests_passed=1,
            tests_total=1,
            success=True
        )
        self.assertEqual(report.judge_model, "skipped")
        self.assertEqual(report.task_solved_score, 0.0)
        self.assertEqual(report.tool_correctness_score, 0.0)

    @patch("src.features.llm_judge.build_agent_model")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_parses_task_solved_score(self, mock_build):
        mock_model = MagicMock()
        mock_build.return_value = mock_model

        mock_resp_task = MagicMock()
        mock_resp_task.content = '{"score": 0.85, "reasoning": "Good job"}'
        mock_resp_tools = MagicMock()
        mock_resp_tools.content = '{"score": 1.0, "reasoning": "Perfect tools"}'
        mock_resp_ctx = MagicMock()
        mock_resp_ctx.content = '{"score": 0.75, "reasoning": "Good reads"}'

        mock_model.response.side_effect = [
            mock_resp_task, mock_resp_tools, mock_resp_ctx,
            # For detailed judging if requested
            mock_resp_task, mock_resp_task, mock_resp_task, mock_resp_task
        ]

        judge = LLMJudge()
        report = judge.evaluate(
            self.task_description,
            self.agent_messages,
            self.patch_content,
            self.config_tools,
            tests_passed=1,
            tests_total=1,
            success=True
        )
        self.assertEqual(report.task_solved_score, 0.85)
        self.assertEqual(report.task_solved_reasoning, "Good job")

    @patch("src.features.llm_judge.build_agent_model")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_handles_api_error_gracefully(self, mock_build):
        mock_model = MagicMock()
        mock_build.return_value = mock_model
        
        mock_model.response.side_effect = Exception("API error")
        
        judge = LLMJudge()
        report = judge.evaluate(
            self.task_description,
            self.agent_messages,
            self.patch_content,
            self.config_tools,
            tests_passed=1,
            tests_total=1,
            success=True
        )
        self.assertEqual(report.task_solved_score, 0.0)
        self.assertIn("judge failed all samples", report.task_solved_reasoning)

if __name__ == "__main__":
    unittest.main()

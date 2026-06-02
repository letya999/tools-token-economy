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

    @patch("src.features.llm_judge.build_agent_model")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_reads_tokens_from_response_usage(self, mock_build):
        """Verify tokens are read from resp.response_usage, not resp.metrics (Agno API)."""
        mock_model = MagicMock()
        mock_build.return_value = mock_model

        # Simulate Agno ModelResponse: response_usage has tokens, resp.input_tokens is None
        mock_resp = MagicMock()
        mock_resp.content = '{"score": 0.5, "reasoning": "ok"}'
        mock_resp.input_tokens = None  # direct field is None (Agno design)
        mock_resp.output_tokens = None
        mock_usage = MagicMock()
        mock_usage.input_tokens = 1000
        mock_usage.output_tokens = 250
        mock_resp.response_usage = mock_usage

        mock_model.response.return_value = mock_resp

        judge = LLMJudge()
        report = judge.evaluate(
            self.task_description,
            self.agent_messages,
            self.patch_content,
            self.config_tools,
            tests_passed=1,
            tests_total=1,
            success=True,
            detailed=False,
        )
        # Judge should not crash and should have recorded tokens
        self.assertEqual(report.task_solved_score, 0.5)
        self.assertGreater(report.judge_input_tokens, 0)
        self.assertGreater(report.judge_output_tokens, 0)

    @patch("src.features.llm_judge.build_agent_model")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_falls_back_when_response_usage_none(self, mock_build):
        """When response_usage is None, fall back to resp.input_tokens without crash."""
        mock_model = MagicMock()
        mock_build.return_value = mock_model

        mock_resp = MagicMock()
        mock_resp.content = '{"score": 0.7, "reasoning": "fallback path"}'
        mock_resp.response_usage = None  # no usage object
        mock_resp.input_tokens = 500
        mock_resp.output_tokens = 100

        mock_model.response.return_value = mock_resp

        judge = LLMJudge()
        report = judge.evaluate(
            self.task_description,
            self.agent_messages,
            self.patch_content,
            self.config_tools,
            tests_passed=1,
            tests_total=1,
            success=True,
            detailed=False,
        )
        self.assertEqual(report.task_solved_score, 0.7)
        # Should not crash even when response_usage is None

    @patch("src.features.llm_judge.build_agent_model")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_does_not_crash_on_attribute_error(self, mock_build):
        """Original bug: resp.metrics AttributeError must not crash the judge."""
        mock_model = MagicMock()
        mock_build.return_value = mock_model

        mock_resp = MagicMock()
        mock_resp.content = '{"score": 0.6, "reasoning": "attribute error test"}'
        # Simulate AttributeError on response_usage access (defensive test)
        type(mock_resp).response_usage = property(lambda self: (_ for _ in ()).throw(AttributeError("no attr")))
        mock_resp.input_tokens = 0
        mock_resp.output_tokens = 0

        mock_model.response.return_value = mock_resp

        judge = LLMJudge()
        # Must not raise
        report = judge.evaluate(
            self.task_description,
            self.agent_messages,
            self.patch_content,
            self.config_tools,
            tests_passed=1,
            tests_total=1,
            success=True,
            detailed=False,
        )
        # Score should be extracted from content despite AttributeError on response_usage
        self.assertEqual(report.task_solved_score, 0.6)

if __name__ == "__main__":
    unittest.main()

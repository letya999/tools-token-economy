import os
import unittest
from unittest.mock import MagicMock, patch

from src.features.llm_judge import LLMJudge, JudgeReport

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

    @patch("src.features.llm_judge.OpenAI")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_parses_task_solved_score(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Mocking task solved response
        mock_response_task = MagicMock()
        mock_response_task.choices[0].message.content = '{"score": 0.85, "reasoning": "Good job"}'
        
        # Mocking tool correctness response
        mock_response_tools = MagicMock()
        mock_response_tools.choices[0].message.content = '{"score": 1.0, "reasoning": "Perfect tools"}'
        
        mock_client.chat.completions.create.side_effect = [mock_response_task, mock_response_tools]
        
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

    @patch("src.features.llm_judge.OpenAI")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_parses_tool_correctness_score(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Mocking responses
        mock_response_task = MagicMock()
        mock_response_task.choices[0].message.content = '{"score": 1.0, "reasoning": "Solved"}'
        mock_response_tools = MagicMock()
        mock_response_tools.choices[0].message.content = '{"score": 0.5, "reasoning": "Only used rg"}'
        
        mock_client.chat.completions.create.side_effect = [mock_response_task, mock_response_tools]
        
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
        self.assertEqual(report.tool_correctness_score, 0.5)
        self.assertEqual(report.tool_correctness_reasoning, "Only used rg")

    @patch("src.features.llm_judge.OpenAI")
    @patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"})
    def test_judge_handles_api_error_gracefully(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_client.chat.completions.create.side_effect = Exception("API error")
        
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
        self.assertIn("judge call failed", report.task_solved_reasoning)
        self.assertEqual(report.tool_correctness_score, 0.0)
        self.assertIn("judge call failed", report.tool_correctness_reasoning)

    def test_judge_extracts_tool_calls_from_messages(self):
        # This tests internal logic indirectly via mock check if I were to check the mock call
        # but here we can just verify it doesn't crash and handles the structure correctly
        judge = LLMJudge()
        # Mocking client to avoid API call
        judge.client = MagicMock()
        judge.api_key = "fake"
        
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"score": 1.0, "reasoning": "ok"}'
        judge.client.chat.completions.create.return_value = mock_resp
        
        # Case 1: Dict based tool calls (already in setUp)
        judge.evaluate(self.task_description, self.agent_messages, self.patch_content, self.config_tools, 1, 1, True)
        
        # Case 2: Object based tool calls
        class MockFunc:
            def __init__(self, name, args):
                self.name = name
                self.arguments = args
        class MockCall:
            def __init__(self, name, args):
                self.function = MockFunc(name, args)
                
        agent_messages_obj = [
            {"role": "assistant", "content": "using tool", "tool_calls": [MockCall("ls", '{"path": "."}')]}
        ]
        judge.evaluate(self.task_description, agent_messages_obj, self.patch_content, self.config_tools, 1, 1, True)
        
        # Verify the sequence was likely correct by looking at what was sent in the mock call
        last_call = judge.client.chat.completions.create.call_args_list[-1]
        user_msg = last_call.kwargs['messages'][1]['content']
        self.assertIn("ls", user_msg)
        # In JSON output summary, quotes are escaped
        self.assertIn('{\\"path\\": \\".\\"}', user_msg)

if __name__ == "__main__":
    unittest.main()

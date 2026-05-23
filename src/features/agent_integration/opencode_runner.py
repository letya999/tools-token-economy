import time
import json
import tiktoken
import google.generativeai as genai
from typing import List, Dict, Any, Optional
from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool, ToolResult

class OpenCodeRunner:
    """
    Рантайм-адаптер для цикла агента (Observe-Think-Act).
    Реализует логику взаимодействия с Gemini 2.5 Flash и вызова инструментов.
    """
    def __init__(self, config: AgentConfig, tools: List[Tool], mock: bool = False):
        self.config = config
        self.tools = {t.name: t for t in tools}
        self.step_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_tokens = 0
        self.model_calls = 0
        self.mock = mock
        self._tokenizer = tiktoken.get_encoding("cl100k_base")
        
        # Инструкция для агента (System Prompt)
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        tools_desc = "\n".join([f"- {t.name}: {t.description}" for t in self.tools.values()])
        return f"""You are a coding agent named OpenCode. Your goal is to solve the task using provided tools.
Available tools:
{tools_desc}

To call a tool, use JSON format:
{{"tool": "tool_name", "args": {{"arg1": "val1"}}}}

Wait for the tool output before proceeding. 
When finished, state 'TASK_COMPLETE' and provide a summary.
"""

    def _count_tokens(self, text: str) -> int:
        if not text: return 0
        return len(self._tokenizer.encode(text))

    def run(self, task_description: str) -> RunMetrics:
        """
        Запускает цикл агента для выполнения задачи.
        """
        start_time = time.time()
        messages = [
            {"role": "user", "content": f"{self.system_prompt}\n\nTask: {task_description}"}
        ]
        self.input_tokens += self._count_tokens(messages[0]["content"])

        if self.mock:
            # Simulate a simple successful run for dry-run
            res_text = 'Thinking... I will finish the task. TASK_COMPLETE'
            self.output_tokens += self._count_tokens(res_text)
            messages.append({"role": "assistant", "content": res_text})
            self.model_calls = 1
        else:
            # В реальности здесь была бы настройка genai.configure(api_key=...)
            model = genai.GenerativeModel(self.config.model)
            
            while self.step_count < self.config.max_steps:
                self.step_count += 1
                self.model_calls += 1
                
                # В тестовом окружении мы мокаем этот вызов
                response = model.generate_content(str(messages))
                res_text = response.text
                
                self.output_tokens += self._count_tokens(res_text)
                messages.append({"role": "assistant", "content": res_text})
                
                if "TASK_COMPLETE" in res_text:
                    break
                    
                # Простейший парсинг вызова тула (для бенчмарка)
                try:
                    # Пытаемся найти JSON блок
                    start_idx = res_text.find('{')
                    end_idx = res_text.rfind('}') + 1
                    if start_idx != -1 and end_idx > start_idx:
                        tool_call = json.loads(res_text[start_idx:end_idx])
                        tool_name = tool_call.get("tool")
                        tool_args = tool_call.get("args", {})
                        
                        if tool_name in self.tools:
                            tool_res = self.tools[tool_name].execute(**tool_args)
                            self.tool_tokens += tool_res.token_count
                            
                            obs_content = f"Observation (from {tool_name}):\n{tool_res.output}"
                            messages.append({"role": "user", "content": obs_content})
                            self.input_tokens += self._count_tokens(obs_content)
                        else:
                            err_msg = f"Error: Tool '{tool_name}' not found."
                            messages.append({"role": "user", "content": err_msg})
                            self.input_tokens += self._count_tokens(err_msg)
                except Exception as e:
                    err_msg = f"Error parsing tool call: {e}"
                    messages.append({"role": "user", "content": err_msg})
                    self.input_tokens += self._count_tokens(err_msg)

        duration = time.time() - start_time
        
        return RunMetrics(
            success="TASK_COMPLETE" in messages[-1]["content"],
            eval_score=1.0 if "TASK_COMPLETE" in messages[-1]["content"] else 0.0,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            tool_tokens=self.tool_tokens,
            duration_sec=duration,
            model_calls=self.model_calls,
            tool_calls=self.step_count - 1 if not self.mock else 0
        )

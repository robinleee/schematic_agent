"""
统一 LLM 客户端封装

支持：
  - Ollama (本地) — 默认
  - vLLM (OpenAI-compatible API)
  - 自动重试、超时、结构化 JSON 输出
  - Thinking 内容过滤（gemma4 等模型）

用法：
    from agent_system.llm_client import LLMClient
    client = LLMClient()
    result = client.chat("分析这个查询的意图", temperature=0.1)
    json_result = client.chat_json("返回 JSON", schema={...})
"""

from __future__ import annotations

import os
import json
import re
import logging
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # ollama | vllm
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:26b")
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL", "gemma4:26b")


@dataclass
class LLMResponse:
    """LLM 响应封装"""
    content: str
    thinking: Optional[str] = None
    raw_response: Optional[Dict] = None
    latency_ms: float = 0.0
    tokens_used: Optional[int] = None


class LLMClient:
    """
    统一 LLM 客户端

    自动处理：
    - Provider 切换 (Ollama/vLLM)
    - 超时 & 重试
    - Thinking 内容过滤
    - JSON 结构化输出
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.provider = (provider or DEFAULT_PROVIDER).lower()
        self.model = model or (OLLAMA_MODEL if self.provider == "ollama" else VLLM_MODEL)
        self.base_url = base_url or (OLLAMA_URL if self.provider == "ollama" else VLLM_URL)
        self.timeout = timeout
        self.max_retries = max_retries

        # 初始化对应客户端
        if self.provider == "ollama":
            self._client = _OllamaBackend(self.base_url, self.model)
        elif self.provider == "vllm":
            self._client = _VLLMBackend(self.base_url, self.model)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

        logger.info(f"LLMClient initialized: provider={self.provider}, model={self.model}, url={self.base_url}")

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        strip_thinking: bool = True,
    ) -> LLMResponse:
        """
        单次对话调用

        Args:
            prompt: 用户输入
            system_prompt: 系统提示（可选）
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            strip_thinking: 是否过滤 thinking 内容

        Returns:
            LLMResponse 对象
        """
        return self._call_with_retry(
            lambda: self._client.chat(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            strip_thinking=strip_thinking,
        )

    def chat_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        schema: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        调用 LLM 并解析为 JSON

        自动处理：
        - Markdown 代码块包裹
        - 截断 JSON 补全
        - 重试机制

        Args:
            prompt: 用户输入
            system_prompt: 系统提示（可选）
            temperature: 采样温度
            max_tokens: 最大生成 token 数（自动保底 512，防止 thinking 模型输出被截断）
            schema: JSON Schema（部分 provider 支持）

        Returns:
            解析后的 dict，失败返回 None
        """
        # gemma4:26b 等 thinking 模型需要至少 512 token 来完成推理+输出
        effective_max_tokens = max(max_tokens, 512)
        """
        调用 LLM 并解析为 JSON

        自动处理：
        - Markdown 代码块包裹
        - 截断 JSON 补全
        - 重试机制

        Args:
            prompt: 用户输入
            system_prompt: 系统提示（可选）
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            schema: JSON Schema（部分 provider 支持）

        Returns:
            解析后的 dict，失败返回 None
        """
        # 在 prompt 中强制 JSON 输出
        enhanced_prompt = prompt
        if "json" not in prompt.lower():
            enhanced_prompt += "\n\nRespond ONLY with valid JSON. No markdown, no explanation."

        # 尝试多次（自动重试已在内层）
        for attempt in range(self.max_retries + 1):
            resp = self.chat(
                prompt=enhanced_prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=effective_max_tokens,
                strip_thinking=True,
            )

            parsed = self._extract_json(resp.content)
            if parsed is not None:
                return parsed

            logger.warning(f"JSON parse failed (attempt {attempt + 1}), retrying...")
            time.sleep(0.5)

        logger.error("JSON parse failed after all retries")
        return None

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def _call_with_retry(
        self,
        fn: Callable[[], tuple[str, Optional[str], Optional[Dict]]],
        strip_thinking: bool = True,
    ) -> LLMResponse:
        """带重试的调用包装"""
        last_error = None

        for attempt in range(self.max_retries + 1):
            start = time.time()
            try:
                content, thinking, raw = fn()
                latency = (time.time() - start) * 1000

                if strip_thinking and thinking:
                    # 过滤掉 thinking 内容，只保留最终答案
                    pass  # content 已经是过滤后的

                return LLMResponse(
                    content=content,
                    thinking=thinking if not strip_thinking else None,
                    raw_response=raw,
                    latency_ms=latency,
                )

            except Exception as e:
                last_error = e
                logger.warning(f"LLM call failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}")
                if attempt < self.max_retries:
                    wait = 2 ** attempt  # 指数退避
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)

        raise last_error

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict]:
        """从文本中提取 JSON 对象"""
        if not text:
            return None

        text = text.strip()

        # 1. 尝试提取 ```json ... ``` 代码块
        md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1))
            except json.JSONDecodeError:
                pass

        # 2. 尝试提取 ``` ... ``` 中的内容（任意代码块）
        md_match = re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. 尝试找裸 JSON（最外层大括号）
        try:
            # 找到第一个 { 和最后一个 }
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

        # 4. 尝试修复截断的 JSON（补全括号）
        try:
            fixed = text + '"}' * 10
            start = fixed.find('{')
            end = fixed.rfind('}')
            if start >= 0 and end > start:
                return json.loads(fixed[start:end + 1])
        except Exception:
            pass

        return None


# ============================================================
# Backend Implementations
# ============================================================

class _OllamaBackend:
    """Ollama API 后端"""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.chat_url = f"{self.base_url}/api/chat"

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> tuple[str, Optional[str], Optional[Dict]]:
        """调用 Ollama /api/chat"""
        import urllib.request

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        req = urllib.request.Request(
            self.chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        message = data.get("message", {})
        content = message.get("content", "")
        thinking = message.get("thinking", None)

        # 如果 content 为空但有 thinking，尝试从 thinking 提取
        if not content and thinking:
            # 提取 thinking 中的最后一段作为答案
            lines = thinking.strip().split("\n")
            content = lines[-1] if lines else ""

        return content, thinking, data


class _VLLMBackend:
    """vLLM OpenAI-compatible API 后端"""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.chat_url = f"{self.base_url}/chat/completions"

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> tuple[str, Optional[str], Optional[Dict]]:
        """调用 vLLM OpenAI API"""
        import urllib.request

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            self.chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        # vLLM 通常没有 thinking 字段
        return content, None, data


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    print("=" * 60)
    print("LLM Client Self-test")
    print("=" * 60)

    client = LLMClient()
    print(f"Provider: {client.provider}, Model: {client.model}")

    # Test 1: Simple chat
    print("\n[Test 1] Simple chat...")
    try:
        resp = client.chat("Say hello in one word.", max_tokens=256)
        print(f"  Content: '{resp.content}'")
        print(f"  Latency: {resp.latency_ms:.0f}ms")
        print(f"  ✅ Pass")
    except Exception as e:
        print(f"  ❌ Fail: {e}")

    # Test 2: JSON output
    print("\n[Test 2] JSON output...")
    try:
        result = client.chat_json(
            'Classify intent: "What connects to I2C_SDA?" Return {"intent": "net_trace"}'
        )
        if result and "intent" in result:
            print(f"  Parsed: {result}")
            print(f"  ✅ Pass")
        else:
            print(f"  ❌ Fail: JSON parse failed")
    except Exception as e:
        print(f"  ❌ Fail: {e}")

    # Test 3: System prompt
    print("\n[Test 3] System prompt...")
    try:
        resp = client.chat(
            "Say ready.",
            system_prompt="You are a hardware schematic analysis AI. Be concise.",
            max_tokens=256
        )
        print(f"  Content: '{resp.content}'")
        print(f"  ✅ Pass")
    except Exception as e:
        print(f"  ❌ Fail: {e}")

    print("\n" + "=" * 60)
    print("LLM Client test completed")
    print("=" * 60)


if __name__ == "__main__":
    _run_tests()

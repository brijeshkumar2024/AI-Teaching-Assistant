"""
core/llm_config.py
───────────────────
Hot-swappable LLM provider config.

Current providers:
  - NVIDIA (OpenAI-compatible API via integrate.api.nvidia.com)
  - Gemini (optional)
  - OpenAI (optional)

Groq was intentionally removed as requested.
"""

import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

load_dotenv()


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _clamp_max_tokens(value: int) -> int:
    return max(512, min(1024, value))

LLM_PROVIDER   = os.getenv("LLM_PROVIDER", "nvidia").lower()

# Default sampling + generation limits
TEMPERATURE    = float(os.getenv("TEMPERATURE", os.getenv("GEMINI_TEMPERATURE", 0.3)))
MAX_TOKENS     = _clamp_max_tokens(_get_env_int("MAX_TOKENS", 800))

# ── NVIDIA (OpenAI-compatible) ───────────────────────────────────────────────
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = os.getenv(
    "NVIDIA_BASE_URL",
    "https://integrate.api.nvidia.com/v1",
).strip()
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "openai/gpt-oss-120b")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class NvidiaChatModel(BaseChatModel):
    """Minimal BaseChatModel implementation for NVIDIA's OpenAI-compatible endpoint."""

    model: str
    temperature: float = Field(default=0.3)
    max_tokens: int = Field(default=800)
    base_url: str
    api_key: str
    # Optional OpenAI client overrides (timeouts, proxies, etc.).
    # Using a plain attribute instead of pydantic Field to avoid FieldInfo leaking through `**client_kwargs`.
    client_kwargs: Optional[Dict[str, Any]] = None

    _client: OpenAI = PrivateAttr()

    def __init__(self, **data: Any):
        # Extract and normalize client_kwargs before pydantic/BaseModel init to guarantee a mapping.
        client_kwargs = data.pop("client_kwargs", None) or {}
        super().__init__(**data)
        self.client_kwargs = client_kwargs
        object.__setattr__(self, "_client", OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            **self.client_kwargs,
        ))

    @property
    def _llm_type(self) -> str:
        return "nvidia-openai-chat"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url,
        }

    def _bounded_max_tokens(self) -> int:
        return max(1, min(self.max_tokens, 1024))

    def _convert_messages(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        return [self._message_to_payload(message) for message in messages]

    def _message_to_payload(self, message: BaseMessage) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "role": self._resolve_role(message),
            "content": self._format_content(getattr(message, "content", None)),
        }
        name = getattr(message, "name", None)
        if name:
            payload["name"] = name
        extra = getattr(message, "additional_kwargs", None) or {}
        if isinstance(extra, dict):
            payload.update(extra)
        else:
            try:
                payload.update(dict(extra))
            except Exception:
                pass
        return payload

    def _resolve_role(self, message: BaseMessage) -> str:
        if isinstance(message, HumanMessage):
            return "user"
        if isinstance(message, SystemMessage):
            return "system"
        if isinstance(message, FunctionMessage):
            return "function"
        if isinstance(message, AIMessage):
            return "assistant"
        return getattr(message, "type", "user")

    def _format_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, (list, tuple)):
            return "".join(str(part) for part in content)
        if isinstance(content, dict):
            return json.dumps(content)
        return str(content)

    @staticmethod
    def _resolve_field(payload: Any, field: str) -> Any:
        if isinstance(payload, dict):
            return payload.get(field)
        return getattr(payload, field, None)

    def _get_first_choice(self, payload: Any) -> Any:
        choices = self._resolve_field(payload, "choices") or []
        if isinstance(choices, (list, tuple)):
            if not choices:
                raise ValueError("No choices returned from NVIDIA LLM")
            return choices[0]
        return choices

    def _create_ai_message(self, choice: Any) -> AIMessage:
        message_payload = self._resolve_field(choice, "message") or {}
        content = self._format_content(self._resolve_field(message_payload, "content"))
        return AIMessage(content=content)

    def _extract_stream_content(self, choice: Any) -> str:
        delta = self._resolve_field(choice, "delta") or {}
        return self._format_content(self._resolve_field(delta, "content"))

    def _build_request(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self._bounded_max_tokens(),
        }
        request.update(self.client_kwargs)
        if stop:
            request["stop"] = stop
        if stream:
            request["stream"] = True
        return request

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        request = self._build_request(messages, stop=stop, stream=False)
        response = self._client.chat.completions.create(**request)
        choice = self._get_first_choice(response)
        message = self._create_ai_message(choice)
        generation = ChatGeneration(message=message)
        return ChatResult(
            generations=[generation],
            llm_output=self._extract_llm_output(response),
        )

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        request = self._build_request(messages, stop=stop, stream=True)
        for chunk in self._client.chat.completions.create(**request):
            # Some providers may emit auxiliary events without choices; skip them.
            try:
                choice = self._get_first_choice(chunk)
            except ValueError:
                continue
            token = self._extract_stream_content(choice)
            if token:
                yield ChatGenerationChunk(message=AIMessageChunk(content=token))

    def _extract_llm_output(self, response: Any) -> Dict[str, Any]:
        output: Dict[str, Any] = {"model": self.model}
        usage = self._resolve_field(response, "usage")
        if usage:
            output["usage"] = usage
        return output

# ── Singleton cache ───────────────────────────────────────────────────────
_llm_cache: dict = {}


def get_llm(
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    streaming: bool = False,
) -> BaseChatModel:
    """
    Returns cached LLM instance based on LLM_PROVIDER in .env.

    Uses LangChain's BaseChatModel interface so agents can keep calling
    `.invoke(...)` and we can optionally use `.stream(...)` for UI streaming.
    """
    cache_key = f"{LLM_PROVIDER}_{temperature}_{max_tokens}_{streaming}"
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    if LLM_PROVIDER == "nvidia":
        if not NVIDIA_API_KEY:
            raise ValueError("NVIDIA_API_KEY is missing in .env")
        llm = NvidiaChatModel(
            model=NVIDIA_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=NVIDIA_BASE_URL,
            api_key=NVIDIA_API_KEY,
        )

    elif LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is missing in .env")
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model          = GEMINI_MODEL,
            google_api_key = GEMINI_API_KEY,
            temperature    = temperature,
            # Gemini streaming can work, but we keep it off unless explicitly enabled.
            streaming      = streaming,
            max_output_tokens = max_tokens,
        )

    elif LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is missing in .env")
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model          = OPENAI_MODEL,
            openai_api_key = OPENAI_API_KEY,
            temperature    = temperature,
            max_tokens    = max_tokens,
            streaming      = streaming,
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use 'nvidia', 'gemini', or 'openai'."
        )

    _llm_cache[cache_key] = llm
    return llm


def get_provider_name() -> str:
    labels = {
        "nvidia": f"NVIDIA ({NVIDIA_MODEL})",
        "gemini": f"Google Gemini ({GEMINI_MODEL})",
        "openai": f"OpenAI ({OPENAI_MODEL})",
    }
    return labels.get(LLM_PROVIDER, LLM_PROVIDER)


def call_llm_with_retry(prompt: str, temperature: float = TEMPERATURE, max_retries: int = 3) -> str:
    """Call LLM with automatic retry on rate limit errors."""
    wait_times = [10, 30, 60]
    llm = get_llm(temperature=temperature, streaming=False, max_tokens=MAX_TOKENS)

    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            err = str(e)
            if any(x in err for x in ["429", "RESOURCE_EXHAUSTED", "quota", "rate_limit"]):
                if attempt < max_retries - 1:
                    wait = wait_times[attempt]
                    print(f"[LLM] Rate limited. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    return "⚠️ Rate limit hit. Please wait a moment and try again."
            else:
                raise

    return "⚠️ Could not get a response. Please try again."


def stream_llm_with_retry(
    prompt: str,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    max_retries: int = 3,
) -> Iterator[str]:
    """
    Streams model output token-by-token (LangChain `.stream(...)`).
    Retries on rate-limit failures before starting the stream.
    """
    wait_times = [10, 30, 60]

    for attempt in range(max_retries):
        try:
            llm = get_llm(
                temperature=temperature,
                max_tokens=max_tokens,
                streaming=True,
            )

            # Streaming yields AIMessageChunk objects.
            for chunk in llm.stream([HumanMessage(content=prompt)]):
                token = getattr(chunk, "content", None)
                if token:
                    yield token
            return
        except Exception as e:
            err = str(e)
            if any(x in err for x in ["429", "RESOURCE_EXHAUSTED", "quota", "rate_limit"]):
                if attempt < max_retries - 1:
                    wait = wait_times[attempt]
                    print(f"[LLM] Rate limited (stream). Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                yield "⚠️ Rate limit hit. Please wait a moment and try again."
                return
            raise


if __name__ == "__main__":
    print(f"Provider : {get_provider_name()}")
    result = call_llm_with_retry("Say 'Connected!' and nothing else.")
    print(f"Response : {result}")

"""
LLM abstraction. `LLMService.generate_reply` takes the conversation history
(oldest -> newest, `{"role": ..., "content": ...}` dicts, same shape as the
Anthropic/OpenAI chat APIs) and returns the agent's next reply.

`MockLLMService` is a placeholder — swap it out in `get_llm_service()` once
a real provider/key is available.
"""
from abc import ABC, abstractmethod

from app.core.config import settings
from app.core.exceptions import LLMProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMService(ABC):
    @abstractmethod
    async def generate_reply(self, history: list[dict[str, str]]) -> str:
        """history: list of {"role": "user"|"agent"|"system", "content": str}."""
        raise NotImplementedError


class MockLLMService(LLMService):
    async def generate_reply(self, history: list[dict[str, str]]) -> str:
        if not history:
            raise LLMProcessingError("Cannot generate a reply from empty conversation history.")
        try:
            last_user_turn = next(
                (turn["content"] for turn in reversed(history) if turn["role"] == "user"),
                "",
            )
            logger.debug("MockLLM generating reply for: %r", last_user_turn)
            # A real provider call (Anthropic/OpenAI/etc.) would go here.
            return f"I heard you say: '{last_user_turn}'. How can I help further?"
        except Exception as exc:  # noqa: BLE001
            raise LLMProcessingError(f"LLM provider failed: {exc}") from exc


def get_llm_service() -> LLMService:
    if settings.LLM_PROVIDER == "mock":
        return MockLLMService()
    # TODO: plug in a real provider here, e.g.:
    # if settings.LLM_PROVIDER == "anthropic": return AnthropicLLMService(settings.LLM_API_KEY)
    raise LLMProcessingError(f"Unsupported LLM_PROVIDER '{settings.LLM_PROVIDER}'")

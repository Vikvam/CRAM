"""OpenAI-compatible LLM access (PLAN 3.6).

The API key lives on the server and never leaves it.
"""

from memo.llm.client import ChatMessage, LLMClient, LLMError
from memo.llm.probe import Capabilities, StructuredOutput, probe
from memo.llm.structured import StructuredError, complete_structured

__all__ = [
    "Capabilities",
    "ChatMessage",
    "LLMClient",
    "LLMError",
    "StructuredError",
    "StructuredOutput",
    "complete_structured",
    "probe",
]

"""One validated object out, whatever the provider can do (PLAN 3.6).

All three tiers end at the same validated model, so nothing downstream has to
know which one was used. Tiers 2 and 3 get a repair loop: the validation errors
are handed back to the model, which fixes its own output far more reliably than
any amount of prompt wording prevents the mistake.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from memo.llm.client import ChatMessage, LLMClient, LLMError
from memo.llm.jsonblock import extract_json_object
from memo.llm.probe import StructuredOutput
from memo.models.extraction import strict_json_schema

MAX_REPAIRS = 2


class StructuredError(LLMError):
    """The provider never produced something that validates."""


def _schema_prompt(schema: dict[str, Any], example: dict[str, Any] | None) -> str:
    parts = [
        "Answer with a single JSON object and nothing else — no prose, no code fence.",
        "It must validate against this JSON Schema:",
        json.dumps(schema, ensure_ascii=False),
    ]
    if example is not None:
        parts += [
            "Here is a correctly shaped (but unrelated) example:",
            json.dumps(example, ensure_ascii=False),
        ]
    return "\n\n".join(parts)


def complete_structured[T: BaseModel](
    client: LLMClient,
    model_type: type[T],
    messages: list[ChatMessage],
    *,
    tier: StructuredOutput | str,
    model: str | None = None,
    example: dict[str, Any] | None = None,
    schema_name: str = "extraction",
    max_repairs: int = MAX_REPAIRS,
) -> T:
    """Run one structured call and return a validated ``model_type``."""
    tier = StructuredOutput(tier)
    schema = strict_json_schema(model_type)

    conversation = list(messages)
    response_format: dict[str, Any] | None = None

    if tier is StructuredOutput.JSON_SCHEMA:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        }
    else:
        # No schema enforcement: it has to go in the prompt instead.
        conversation.insert(0, ChatMessage(role="system", content=_schema_prompt(schema, example)))
        if tier is StructuredOutput.JSON_OBJECT:
            response_format = {"type": "json_object"}

    problems: list[str] = []
    for attempt in range(max_repairs + 1):
        text = client.chat(conversation, model=model, response_format=response_format)
        try:
            return model_type.model_validate(extract_json_object(text))
        except (ValidationError, ValueError) as exc:
            problems.append(str(exc))
            if attempt == max_repairs or tier is StructuredOutput.JSON_SCHEMA:
                # Tier 1 promised the schema; retrying the same call will not help.
                break
            conversation += [
                ChatMessage(role="assistant", content=text),
                ChatMessage(
                    role="user",
                    content=(
                        "That did not validate. Fix these problems and answer again with the "
                        f"complete corrected JSON object only:\n{exc}"
                    ),
                ),
            ]

    raise StructuredError(
        f"no valid {model_type.__name__} after {len(problems)} attempt(s): {problems[-1][:500]}"
    )

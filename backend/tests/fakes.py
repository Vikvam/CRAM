"""A stand-in provider, so the whole pipeline can be exercised without an API key."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from memo.config import Settings
from memo.llm.client import ChatMessage, LLMClient, LLMError


class FakeLLM(LLMClient):
    """Replays canned answers; records what it was asked."""

    def __init__(
        self,
        answers: Sequence[str | Exception] | Callable[[list[ChatMessage]], str],
        *,
        settings: Settings | None = None,
    ):
        super().__init__(settings or Settings(llm_model="fake-model"))
        self._answers = answers
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model=None, response_format=None, temperature=None, max_tokens=None):
        self.calls.append({"messages": messages, "model": model, "response_format": response_format})
        if callable(self._answers):
            return self._answers(messages)
        index = min(len(self.calls) - 1, len(self._answers) - 1)
        answer = self._answers[index]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:  # nothing to close
        return


def write_pdf(path, pages: list[list[str]]) -> None:
    """A PDF with one page per list of lines, written by hand; an empty list is a page with no text."""
    texts = [
        "BT /F1 12 Tf 40 780 Td 14 TL\n" + "".join(f"({line}) Tj T*\n" for line in lines) + "ET"
        for lines in pages
    ]
    count = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    font = 3 + 2 * count
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {count} >>"]
    for i, text in enumerate(texts):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {4 + 2 * i} 0 R"
            f" /Resources << /Font << /F1 {font} 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(text)} >>\nstream\n{text}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


__all__ = ["FakeLLM", "LLMError", "as_json", "write_pdf"]

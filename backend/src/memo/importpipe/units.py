"""What one call reads: a photo, or a few pages of a PDF.

A PDF goes to the model in chunks of ``pages_per_call`` pages, either as its
text layer (cheap, and any model can read it) or as pictures of its pages (for
tables, layout and scans). Which one is the person's choice at upload. A chunk
with no text in it is sent as pictures anyway, since that is the only way to
read a scan.

Pages are numbered across the whole upload, photos counting one each, so the
printed number of the first page carries through a PDF and on to the photo
after it.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from memo.llm.client import image_part, text_part

PdfMode = Literal["text", "images"]
PDF_MODES: tuple[str, ...] = ("text", "images")
PDF_SUFFIX = ".pdf"
#: Resolution pages are rendered at: enough for small print, small enough to send.
RENDER_DPI = 150
JPEG_QUALITY = 85


class UnreadablePdf(ValueError):
    """A PDF that could not be opened at all."""


@dataclass(slots=True)
class Unit:
    file: Path
    #: Which uploaded file this came from, in upload order.
    file_index: int
    #: Position of its first page in the whole upload, from 0.
    offset: int
    #: Pages it covers: 1 for a photo.
    count: int
    #: For a PDF chunk, its pages within that PDF (from 1, inclusive).
    pdf_pages: tuple[int, int] | None = None
    pdf_mode: PdfMode | None = None
    #: Built only when the call is made, so a long PDF is never all in memory at once.
    build: Callable[[], list[dict[str, Any]]] | None = None

    @property
    def is_pdf(self) -> bool:
        return self.pdf_pages is not None

    def parts(self) -> list[dict[str, Any]]:
        return self.build() if self.build else [image_part(self.file)]

    def describe(self, position: int, total: int, printed: int | None) -> str:
        """The line a data-file importer is told about what is in front of it."""
        if not self.is_pdf:
            line = (
                f"This is photo {position} of {total} in one upload." if total > 1 else "This is one photo."
            )
            if printed is not None:
                line += f" It is printed page {printed}."
            return line
        first, last = self.pdf_pages or (1, 1)
        where = f"page {first}" if first == last else f"pages {first}–{last}"
        line = f"This is {where} of {self.file.name}."
        if total > 1:
            line += f" It is part {position} of {total} in one upload."
        if printed is not None:
            line += (
                f" It is printed page {printed}."
                if self.count == 1
                else f" They are printed pages {printed}–{printed + self.count - 1}."
            )
        return line


def page_count(path: Path) -> int:
    """How many pages a PDF has; also the check that it opens at all."""
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        raise UnreadablePdf(f"{path.name}: could not be opened as a PDF ({exc})") from None
    try:
        return len(document)
    finally:
        document.close()


def units_for(paths: list[Path], *, pdf_mode: PdfMode = "text", pages_per_call: int = 5) -> list[Unit]:
    units: list[Unit] = []
    offset = 0
    for index, path in enumerate(paths):
        if path.suffix.lower() != PDF_SUFFIX:
            units.append(Unit(file=path, file_index=index, offset=offset, count=1))
            offset += 1
            continue
        pages = page_count(path)
        for start in range(0, pages, max(1, pages_per_call)):
            end = min(pages, start + pages_per_call)
            units.append(
                Unit(
                    file=path,
                    file_index=index,
                    offset=offset + start,
                    count=end - start,
                    pdf_pages=(start + 1, end),
                    pdf_mode=pdf_mode,
                    build=_pdf_parts(path, start, end, pdf_mode),
                )
            )
        offset += pages
    return units


def _pdf_parts(path: Path, start: int, end: int, mode: PdfMode) -> Callable[[], list[dict[str, Any]]]:
    def build() -> list[dict[str, Any]]:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(path))
        try:
            pages = [document[i] for i in range(start, end)]
            if mode == "text":
                texts = [_text(page) for page in pages]
                if any(texts):
                    return [text_part(_text_block(path, start, texts))]
            return [_picture(page) for page in pages]  # chosen, or a scan with no text to send
        finally:
            document.close()

    return build


def _text(page) -> str:
    return page.get_textpage().get_text_bounded().replace("\r\n", "\n").strip()


def _text_block(path: Path, start: int, texts: list[str]) -> str:
    sections = [
        f"--- page {start + i + 1} ---\n{text or '(no text on this page)'}" for i, text in enumerate(texts)
    ]
    return f"The text of {path.name}, as extracted from the PDF:\n\n" + "\n\n".join(sections)


def _picture(page) -> dict[str, Any]:
    image = page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return image_part_bytes(buffer.getvalue(), "image/jpeg")


def image_part_bytes(data: bytes, media_type: str) -> dict[str, Any]:

    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}}

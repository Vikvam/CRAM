"""The import pipeline (PLAN 4).

Each photo, and each few pages of a PDF, is read by its own call and merged in
page order, so one unreadable page costs that page and nothing else — the rest
still reaches the review step (``units.py``). An
extraction importer's pages go through the adapter; a data-file importer's
answers are merged as they are (``direct.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from memo.importers.base import AnyImporter, DatafileImporter, Importer
from memo.importpipe.direct import merge_pages, read_page
from memo.importpipe.units import PdfMode, units_for
from memo.llm.client import ChatMessage, LLMClient, LLMError, image_part, text_part
from memo.llm.probe import StructuredOutput
from memo.llm.structured import complete_structured
from memo.models.adapter import Page, to_datafile
from memo.models.datafile import DataFile
from memo.models.extraction import ExtractionResult
from memo.models.ids import job_id


@dataclass(slots=True)
class PageOutcome:
    """What one call produced — a photo, or a few pages of a PDF — or why it produced nothing."""

    path: Path
    #: The (printed, if known) number of its first page.
    number: int
    result: ExtractionResult | list[DataFile] | None = None
    error: str | None = None
    #: Which uploaded file, in upload order, and how many of its pages this covers.
    file_index: int = 0
    count: int = 1

    @property
    def ok(self) -> bool:
        return self.result is not None


@dataclass(slots=True)
class ImportOutcome:
    job: str
    importer: str
    datafile: DataFile
    pages: list[PageOutcome] = field(default_factory=list)
    router_reason: str | None = None

    @property
    def failed_pages(self) -> list[PageOutcome]:
        return [p for p in self.pages if not p.ok]

    @property
    def pages_ok(self) -> list[PageOutcome]:
        return [p for p in self.pages if p.ok]


def extract_page(
    client: LLMClient,
    importer: Importer,
    path: str | Path | None = None,
    *,
    tier: StructuredOutput | str,
    page_number: int | None = None,
    total_pages: int | None = None,
    model: str | None = None,
    instructions: list[str] | None = None,
    parts: list[dict] | None = None,
) -> ExtractionResult:
    """One page (or a few PDF pages, as ``parts``), one LLM call, one validated extraction."""
    asked = "\n\n".join([importer.page_instruction(page_number, total_pages), *(instructions or [])])
    material = parts if parts is not None else [image_part(path)]
    messages = [
        ChatMessage(role="system", content=importer.system_prompt),
        ChatMessage(role="user", content=[text_part(asked), *material]),
    ]
    result = complete_structured(
        client,
        importer.extraction_model,
        messages,
        tier=tier,
        model=model,
        example=importer.example,
        schema_name="extraction",
    )
    return result  # type: ignore[return-value]


def run_import(
    client: LLMClient,
    importer: AnyImporter,
    paths: list[str | Path],
    *,
    tier: StructuredOutput | str,
    model: str | None = None,
    first_page_number: int | None = None,
    router_reason: str | None = None,
    source_kind: str | None = None,
    instructions: list[str] | None = None,
    pdf_mode: PdfMode = "text",
    pages_per_call: int = 5,
) -> ImportOutcome:
    """Read every photo and PDF and merge them into one draft data file.

    ``first_page_number`` is the printed number of the first page, or ``None``
    when nobody said; ``instructions`` are lines for the model (the category's
    languages, what the person typed), after anything about the page itself.
    A PDF is read ``pages_per_call`` pages at a time, as text or as pictures.
    """
    known = first_page_number is not None
    start = first_page_number if first_page_number is not None else 1
    units = units_for([Path(p) for p in paths], pdf_mode=pdf_mode, pages_per_call=pages_per_call)
    outcomes: list[PageOutcome] = []
    for position, unit in enumerate(units, 1):
        number = start + unit.offset
        outcome = PageOutcome(path=unit.file, number=number, file_index=unit.file_index, count=unit.count)
        try:
            parts = unit.parts()
            if isinstance(importer, DatafileImporter):
                line = unit.describe(position, len(units), number if known else None)
                outcome.result = read_page(
                    client, importer, instructions=[line, *(instructions or [])], model=model, parts=parts
                )
            else:
                outcome.result = extract_page(
                    client,
                    importer,
                    tier=tier,
                    page_number=number,
                    total_pages=len(units),
                    model=model,
                    instructions=instructions,
                    parts=parts,
                )
        except (LLMError, ValueError, OSError) as exc:
            outcome.error = str(exc)
        outcomes.append(outcome)

    job = job_id()
    used_model = model or client.settings.llm_model
    kind = source_kind or ("pdf" if units and all(u.is_pdf for u in units) else "image")
    if isinstance(importer, DatafileImporter):
        datafile = merge_pages(
            [
                (o.number if o.count == 1 else None, o.path.name, o.result)
                for o in outcomes
                if isinstance(o.result, list)
            ],
            importer=importer,
            model=used_model,
            job=job,
            known_pages=known,
            source_kind=kind,
        )
    else:
        pages = [
            Page(outcome.result, number=outcome.number, file=outcome.path.name)
            for outcome in outcomes
            if isinstance(outcome.result, ExtractionResult)
        ]
        datafile = to_datafile(
            pages,
            profile=importer.name,
            model=used_model,
            prompt_version=importer.prompt_version,
            job=job,
            default_type=importer.default_type,
            front_lang=importer.front_lang,
            back_lang=importer.back_lang,
            source_kind=kind,
        )
    return ImportOutcome(
        job=job,
        importer=importer.name,
        datafile=datafile,
        pages=outcomes,
        router_reason=router_reason,
    )

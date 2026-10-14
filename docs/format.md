# The data format

Everything in memo is notes inside **data files** inside **categories**. This page is the reference
for the files: what an import produces, what an export writes, and what you can write by hand or have
an LLM write ([llm-prompt.md](llm-prompt.md)). The reasoning behind each rule is in
[PLAN.md §3](../PLAN.md#3-data-format-core-of-the-project). The machine-readable version is
`backend/schema/memo.datafile.schema.json` (`uv run memo schema` regenerates it).

The database, not these files, is the truth. A data file is how notes get in and how a snapshot gets
out (see [Importing and exporting](#importing-and-exporting)).

## A data file

One JSON object per lesson, chapter or upload:

```json
{
  "format": "memo.datafile",
  "version": 1,
  "title": "2-1 · 어휘와 표현 · Vocabulary & Expressions",
  "default_type": "bidirectional",
  "front_lang": "ko",
  "back_lang": "en",
  "source": {
    "kind": "image",
    "files": ["raw/vocab1.jpg"],
    "page": 6,
    "context": { "lesson": { "number": "2-1", "ko": "저는 첸이에요", "en": "I'm Chen" } }
  },
  "groups": [
    { "id": "countries", "label": { "ko": "나라", "en": "Countries" } },
    { "id": "additional", "label": { "ko": "기타 추가 어휘", "en": "Additional Vocabulary" } }
  ],
  "notes": [
    { "group": "countries", "front": "러시아", "back": "Russia" },
    { "group": "countries", "front": "미국", "back": "USA", "accept": { "back": ["America", "the US"] } },
    {
      "group": "additional",
      "front": "어느",
      "back": "what, which",
      "accept": { "back": ["what", "which"] }
    },
    {
      "group": "additional",
      "front": "-씨",
      "back": "Mr., Ms.",
      "accept": { "back": ["Mr.", "Ms.", "Mr", "Ms"] },
      "note": "Added after another person's name, never after your own.",
      "fields": { "romanization": "-ssi" }
    }
  ]
}
```

| key | | |
|---|---|---|
| `format` | required | always `"memo.datafile"` |
| `version` | required | `1`. Older versions are migrated on load; a newer one is refused |
| `id` | | `df_…`, assigned by the server. Leave it out when writing a file |
| `title` | | one plain line, whatever scripts it mixes. Old files with a `{lang: text}` map are read as one line, native side first |
| `default_type` | | `bidirectional` or `directional` for every note that sets none; else inherited from the category, else `directional` |
| `front_lang`, `back_lang` | | BCP-47 codes. They choose the voice for *hear it* and the font, and help duplicate detection. Inherited from the category |
| `source` | | provenance, all optional: `kind` (`image`, `pdf`, `text`, `json`, `csv`, `anki`, `manual`), `files`, `page`, free-form `context`, and `import` (which importer, model and prompt, with `extra.prompt_sha` when it was a data-file reader such as the general one; written by memo) |
| `groups` | | the headings inside the file: `id`, `label` (a `{lang: text}` map), optional `note` |
| `notes` | | the notes |
| `tags`, `extra` | | free; kept and written back out |

Unknown keys anywhere are kept and written back out, so nothing is lost on a round trip.

## A note

| key | | |
|---|---|---|
| `id` | | `n_…`, assigned by the server. Progress is keyed on it |
| `front`, `back` | | Markdown with `$…$` / `$$…$$` KaTeX. A note missing either is kept, flagged in review, and makes no cards |
| `type` | | overrides `default_type` for this note. An unknown value reads as `directional` |
| `group` | | a group `id` from the same file |
| `accept` | | `{"front": [...], "back": [...]}`: other answers that count as correct when typed. Explicit only; nothing is split on commas or slashes at runtime |
| `note` | | Markdown, shown after answering |
| `fields` | | `{name: value}`, shown after answering as a small table. For extra columns (romanization, plural, symbol…) |
| `modes` | | restricts how this note may be asked (below). Missing means all that apply |
| `tags` | | free tags |
| `status` | | `unverified` until the import is reviewed, then `confirmed` |
| `confidence` | | 0–1. Below 0.7 marks the row *check this row* in review |
| `suspended` | | `true` keeps the note out of practice: *Set aside* on Progress, *suspended* in the grid editor |
| `priority` | | `low`, `high` or `crucial`; missing is normal and is never stored. How much a mark counts fades as the word becomes known (see [`../backend/README.md`](../backend/README.md#how-often-a-word-comes-up)) |
| `page` | | the source page |
| `extra` | | anything else |

### Cards

A `directional` note makes one card, `fwd` (front → back). A `bidirectional` note makes two, `fwd`
and `rev` (back → front), scheduled separately. A card is keyed `note_id:fwd` or `note_id:rev`, and
the text is not part of that key, so editing a note's text never touches its history.

**In a bidirectional note the back is a prompt too.** Two notes in reach of each other with the same
back ask one question with two right answers. `memo audit` and the Collection page look for this.
There are two fixes, both conventions in the existing data:

- **They differ:** say how in the back, `this + 이 (subject)`, and keep the bare meaning, `this`, in
  `accept.back` so the forward direction gets no harder.
- **They are the same thing:** keep the shared back and list each one's front in the other's
  `accept.front` (뭐 ↔ 무엇).

### Modes

| mode | asking | needs |
|---|---|---|
| `flip` | reveal, grade yourself | — |
| `typed` | type the answer, differences shown | — |
| `choice` | pick one of several | enough other notes to draw wrong options from (the category's *Options from*) |
| `match` | pair up a handful of notes | at least 3 notes in reach |
| `build` | assemble from shuffled pieces | 2–6 words, or one word of 2–12 characters |

A mode that cannot work for a card is skipped silently, so `modes` is only for those that would work
and be unfair: a long free-form answer or a formula → `["flip", "choice"]`. The category can narrow
the modes for a whole branch, and a sitting can override them.

## A category

A folder in the tree, written as `_category.json` beside its data files. Every field is optional and
inherited from the parent; nested blocks merge key by key.

```jsonc
{
  "format": "memo.category",
  "version": 1,
  "label": { "ko": "한국어", "en": "Korean" },
  "default_type": "bidirectional",
  "front_lang": "ko",
  "back_lang": "en",
  "practice": {
    "modes": ["flip", "typed", "choice", "match", "build"],
    "adaptive": true,                    // the app picks a mode per card
    "distractor_scope": "auto",          // auto | group | file | category
    "scheduler": "fsrs",                 // fsrs | sm2
    "typed": { "split": "auto" }         // auto | whitespace | grapheme | terms
  }
}
```

In the app, a category's **⋯** panel sets the modes and where the options come from. The
scheduler is chosen in **Settings** for the whole collection; `practice.scheduler` in a file is
the same setting, made for one branch.

## Importing and exporting

**Importing** is always a draft → review → commit, whatever the source:

| upload | how it is read |
|---|---|
| a photo, or a `.pdf` | by the configured LLM, with the prompt in [llm-prompt.md](llm-prompt.md), or with a local importer ([development.md](development.md#importers)); `uv run memo importers` lists them |
| `.json`, a `memo.datafile` | as it is, every field kept. **Ids are blanked and every note becomes `unverified`**: an uploaded file is always new notes |
| `.json`, a plain list | `[{"front": …, "back": …}, …]`; also `term`/`meaning`, `question`/`answer` and similar names, plus `group` and `note` |
| `.csv` / `.tsv` | columns found by header (`front`/`term`/`word`/`question`…, `back`/`meaning`/`answer`/`definition`…, `group`/`section`/`lesson`…, `note`/`example`…, `tags`), else the first two columns in order |
| `.txt` / `.md` | one pair per line, split on the separator most lines share (tab, ` = `, ` — `, ` - `, ` : `, `;`, `=`, `\|`). A line without one is a heading for the lines below |
| `.apkg` / `.colpkg` | an Anki deck's first two fields |

A PDF goes to the model a few pages per call (`MEMO_PDF_PAGES_PER_CALL`, 5 by default), as its text
layer or as pictures of its pages, which you choose at upload; a scan is always sent as pictures.
Files uploaded together become one draft. Formats other than a `memo.datafile` come in as
`bidirectional`, which you can change in review.

**Exporting** writes the database out: `uv run memo export <file id>` for one file,
`uv run memo export-tree` for the whole collection into `data/`, one folder per category. The export
is a snapshot. **Editing an exported file and uploading it again does not edit anything**: it makes
new notes with no history. Change committed notes in the grid editor, or in bulk with `memo patch`
(a reviewed file of `{id, expect, set}`, dry-run until `--apply`), then run `memo export-tree` to
bring `data/` back in step.

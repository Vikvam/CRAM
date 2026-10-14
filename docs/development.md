# Working on memo

For anyone changing the code, people and coding LLMs alike. How to *use* the app is in
[user-guide.md](user-guide.md). How the data is shaped is in [format.md](format.md).

## Where things are

```
PLAN.md            the decision record: every design question asked and how it was settled
serve.sh           migrate, build the frontend if missing, run the server
backend/           Python 3.13, FastAPI, SQLAlchemy, alembic, Typer — README has the module map
  src/memo/        models · db · collection · importers · importpipe · llm · scheduling ·
                   practice · overview · api · cli.py
  tests/           pytest; tests/fakes.py stands in for the LLM provider
  patches/         reviewed bulk edits, applied with `memo patch`
  examples/importers/  a local importer spec to copy
  importers.local/ your own importers: gitignored, loaded at runtime
  var/memo.db      THE database: the only copy of every review
frontend/          SvelteKit 5, built static and served by the backend — README has the map
  packages/answer-check/   the one answer checker, spec in spec/answer-check.md
spec/              the answer checker's spec and shared test vectors
data/              a snapshot of the collection as JSON, written by `memo export-tree`
docs/              these pages
```

The module maps are in [`backend/README.md` → Layout](../backend/README.md#layout) and
[`frontend/README.md` → Layout](../frontend/README.md#layout).

## Setting up and running

```sh
cd backend
uv sync
uv run alembic upgrade head
uv run memo hash-password         # optional: put the hash in .env as MEMO_AUTH_PASSWORD_HASH
cd ../frontend && npm install && npm run build
cd .. && ./serve.sh               # http://127.0.0.1:8000
```

Settings come from `backend/.env` with the `MEMO_` prefix (`backend/src/memo/config.py`). Photo
import needs `MEMO_LLM_API_KEY` and the provider settings there. `MEMO_VAR_DIR` moves the database
and uploads, which is how to experiment without touching the real one.

For frontend work, `npm run dev` in `frontend/` gives hot reload and proxies `/api` to a running
`memo serve`. When an API shape changes, run `uv run memo openapi` in `backend/`, then
`npm run types` in `frontend/`.

`uv run memo --help` lists the command line. The ones used in maintenance are `audit` (read-only
check of the data), `patch` (the only bulk edit), `export-tree`, `backup` and `import-answers`.

## Importers

A photo is read by an importer. Every install has one, `general`, which sends the prompt from
[llm-prompt.md](llm-prompt.md) (`src/memo/importers/prompts/general.md`, kept identical to the doc by
`tests/test_docs.py`) and takes back whole data files. Anything narrower, such as a reader for one
textbook's layout, is a **local importer**: a file in `backend/importers.local/`, which git ignores.
`MEMO_IMPORTERS_DIR` points somewhere else. `uv run memo importers` lists what loaded, and why anything
did not. With a local importer present, the app chooses between them from the first page, and the
upload page offers the choice.

A spec is TOML:

```toml
kind = "extraction"          # the strict extraction shape (PLAN 3.6); or "datafile", like general
name = "my-book"
description = "One sentence the router chooses by."
default_type = "bidirectional"
front_lang = "ko"
back_lang = "en"
prompt = '''
How to read this book's pages…
'''                          # or prompt_file = "my-book.md" beside it
example = '''{ …an extraction, as JSON… }'''   # extraction only; or example_file
```

`backend/examples/importers/korean-textbook-vocab.toml` is a complete one; copy it into
`importers.local/` to use it. A `.py` file defining `IMPORTER` (an `Importer` or `DatafileImporter` from
`memo.importers`) works too, for anything a spec cannot say. It runs as code, so only ever put your
own files there. The decisions behind all of this are PLAN §4.1.

## Checking a change

```sh
cd backend  && uv run pytest && uv run ruff check src tests
cd frontend && npm test && npm run check
```

No test touches the network or `var/memo.db`. `tests/test_docs.py` checks that every data-file
example in `docs/` loads, survives the upload path and passes the audit, and that every
`memo <command>` the docs mention exists. Change a doc example and the suite tells you if it is
wrong.

To see a change in the browser, build the frontend and run the server against a copy of the
database:

```sh
mkdir -p /tmp/memo-var
sqlite3 backend/var/memo.db ".backup /tmp/memo-var/memo.db"   # not cp: the WAL holds recent writes
MEMO_VAR_DIR=/tmp/memo-var ./serve.sh --build
```

## Working on this as an LLM agent

Read this before changing anything. Each rule exists because breaking it once cost real data or a
redesign.

**The data**

- **`backend/var/memo.db` is the only copy of every review.** Never run experiments, migrations or
  imports against it. Use `MEMO_VAR_DIR` with a copy, and run `memo backup` first if the real one
  must change.
- **`review_log` is append-only, and the card state is a cache of it.** `practice.replay()` rebuilds
  state from the log. Never write a feature that edits or deletes log rows. Derive what you need from
  them, as mastery does (`overview/progress.py:standing()`).
- **A card is keyed `note_id:direction`**, with no text in the key. Editing a note's text is safe;
  changing its id is the same as deleting its history.
- **Never fix data by editing `data/**.json` and re-importing.** `store_datafile` only inserts, and
  an upload blanks every id, so the result is new notes with no history. Write a patch file for
  `memo patch` (dry run, then `--apply`), then `memo export-tree`. See
  `backend/patches/` for examples.

**The design**

- **Keep it general.** The practice side knows no language (PLAN §3.7). Anything specific to one
  language or one book belongs in a local importer spec ([Importers](#importers)), never in practice,
  scheduling or the frontend.
- **Plain, hand-written data over clever generators.** Never invent linguistic relations (antonyms,
  translations) and present them as the collection's own.
- **No counts, scores or streak pressure on practice screens.** They came out in phase 3 on request.
- **Copy is cut hard.** One short line on screen. A load-bearing rule goes behind the `?`
  (`Help.svelte`), not into a paragraph.
- **Data-file format changes** go through `models/datafile.py` (lenient: unknown keys kept, nothing
  required but `format`/`version`), get a version migration if they are not additive, and are
  reflected in [format.md](format.md) and, if they affect what an LLM should write,
  [llm-prompt.md](llm-prompt.md).

**Deciding things**

- **PLAN.md is the record.** §1 and the ✅ marks are settled: do not re-open them. §7 lists what was
  deliberately deferred (profiles, LLM categorisation). Do not build those unprompted.
- **Ask the owner about genuine forks** instead of picking a strong default, and record the answer in
  PLAN.md.
- **The "why" lives next to the code it explains.** Each README section below is a decision, written
  when it was made. Read the relevant one before changing that area:

| area | where |
|---|---|
| data format, note types, modes, answer checking | PLAN §3, `spec/answer-check.md` |
| import pipeline, the two schemas | PLAN §3.6, §4 |
| mastery and the four buckets | backend README *What counts as mastered* |
| practising early, sitting size | backend README *Practising a lesson you chose*, *How long a sitting will take*; frontend README *How much one sitting is* |
| priority marks | backend + frontend README *How often a word comes up* |
| search, lists for a test | backend + frontend README *Finding a word*, *A list for a test* |
| ambiguous glosses, audit, patch | backend README *A gloss read backwards* |
| offline and sync | backend README *Answers earned offline*, frontend README *With no network*, [serving.md](serving.md) |
| look, skins, tokens | frontend README *Looks* |
| keyboard | frontend README *Keyboard* |
| storage choice | [storage-options.md](storage-options.md) |

**Testing the UI.** Do not install browsers. Drive the system Chromium over the DevTools protocol
against a server started on a copy of the database (above).

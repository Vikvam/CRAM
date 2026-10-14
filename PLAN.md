# Memorization app — plan

Custom Anki-like cards (**practice**) with a better structured **overview** (learn).
Content is mostly created by parsing documents/pictures with an LLM (OpenAI-compatible API, custom provider).
First target: Korean vocabulary from textbook photos (`data/korean/raw/vocab1.jpg`); later equations etc.

Status markers: ✅ decided with user · 💡 proposal (not yet confirmed) · ❓ open question

**Where things stand:** phases 0–3 are built, plus most of phase 4 (§6). Profiles and LLM categorisation
are deferred (§7). This file is the decision record; how to use the app is in
[docs/user-guide.md](docs/user-guide.md), and how to work on it is in [docs/development.md](docs/development.md).

**Contents:** [1. Decisions so far](#1-decisions-so-far) · [2. What the sample image tells us](#2-what-the-sample-image-tells-us) · [3. Data format (core of the project)](#3-data-format-core-of-the-project) · [4. Import pipeline](#4-import-pipeline) · [5. Architecture ✅](#5-architecture-) · [6. Phases ✅ (slicing is my proposal, contents decided)](#6-phases--slicing-is-my-proposal-contents-decided) · [7. Open questions ❓](#7-open-questions-)

---

## 1. Decisions so far

| Topic | Decision |
|---|---|
| Server | ✅ Basic server; nothing has to be local-first |
| Users | ✅ One shared password (bot gate), then an open profile picker (a few trusted people) |
| LLM API | ✅ OpenAI-compatible (base URL + key + model configurable) |
| Import flow | ✅ Review/edit staged cards before saving |
| Scheduler | ✅ Pluggable; keep raw review logs so any algorithm can be (re)computed |
| Notes → cards | ✅ Anki-style: one note generates one or more cards, each with its own schedule |
| Note types | ✅ By practice shape, not domain: `bidirectional` (e.g. Korean vocab) and `directional` (Q→A, equations); keys `front`/`back` + optional extra fields with safe fallbacks |
| Practice modes | ✅ Interactive, beyond Anki: flip, typed answer (fuzzy-scored), multiple choice, matching/build — all in MVP |
| Mode selection | ✅ Adaptive by default, overridable per category and per session |
| Answer checking | ✅ Goal is learning, not scoring: result is `correct` / `almost` (diff shown) / `wrong`, never a number; user can always override |
| Accepted answers | ✅ Come from the import (LLM lists them explicitly) or are added by you during practice — never guessed from punctuation at runtime |
| Multi-page upload | ✅ Several pictures → one import job → one data file; pages can be added to an existing file later |
| Korean fields | ✅ Whatever the source contains (currently KO↔EN pairs); support more formats later |
| Storage | ✅ SQLite is the truth (option D); JSON data file format stays as interchange/LLM/export format; manual export only, no auto-export yet |
| Organisation | ✅ Tree of categories (a table, mirroring a directory path); one import job = one data file. LLM content-based categorisation later |
| One raw upload | ✅ → exactly one data file (all its cards grouped together) |
| Rich content | ✅ Markdown + KaTeX strings |
| File syntax | ✅ JSON (best for LLM output); friendly UI editor instead of hand-editing |
| Backend lang | ✅ Python — FastAPI + Pydantic v2 + SQLite |
| Frontend | ✅ SvelteKit (static build, PWA), served by FastAPI |
| Scheduler impl | ✅ SM-2 **and** FSRS behind one interface, switchable per profile/category |
| Deployment | ✅ laptop + Tailscale now; Docker on an always-on box later (no PaaS) — `docs/serving.md` |
| Language-neutrality | ✅ Practice logic knows no Korean: comparison in Unicode NFD, build mode splits on grapheme clusters; Korean lives in the content and the extractor |
| MVP | ✅ Image→LLM→review, raw data file upload, manual CRUD, **full SRS practice** |
| Learn view (later) | ✅ Hierarchical categories, grouped study sheets, progress stats |

## 2. What the sample image tells us

`data/korean/raw/vocab1.jpg` (textbook page 6):

- Hierarchy is on the page: chapter `02 소개 / Introduction` → lesson `2-1 저는 첸이에요 / I'm Chen`
  → section `어휘와 표현 / Vocabulary & Expressions` → groups `나라 Countries`, `직업 Jobs`, `기타 추가 어휘 Additional Vocabulary`.
- Labels are bilingual (ko + en) → labels should be language maps, not single strings.
- Footnotes attach to items (`-씨¹` → usage note) → per-note `note` field.
- Meanings can be multi-valued (`what, which`) or annotated (`I/me (honorific)`).
- Table layout is **two KO/EN pairs per row** → the "known format" prompt must say so.
- Photo is skewed with bleed-through from the next page → vision model + strict schema + review step are essential.
- The page also contains a grammar TOC (`N이에요/예요`, `N은/는`, …) → future grammar content (still `directional`/`bidirectional`); MVP ignores it.

## 3. Data format (core of the project)

**Where it lives** ✅: SQLite is the runtime truth (see §5). The format below is still fully binding — it is
the **import, export and LLM-extraction** shape, and the DB tables mirror it field for field. A data file is what
an import job produces, what an export writes, and what a round-trip test compares; it is not read at runtime.

Design rules:

1. **Null tolerant**: every field except `format`/`version` is optional; readers fill defaults, never crash.
   Invalid notes are loaded as *flagged*, not dropped.
2. **Extensible / lossless**: unknown keys are preserved on round-trip (Pydantic `extra="allow"`),
   plus an explicit `extra` bag for importer-specific data.
3. **Versioned**: `version` integer + migration functions `v1→v2…` applied on load.
4. **Stable IDs** assigned by the server (never trusted from the LLM) — progress is keyed on them,
   so re-importing/editing text never loses review history.
5. **Types describe practice shape, not domain**: only `bidirectional` and `directional`.
   Domain-specific data (romanization, examples…) goes into optional `fields`, rendered generically.
6. **Pydantic models define it** → exported **JSON Schema** validates import/export files and generates TS types for the
   frontends; the strict LLM-facing variant is separate (§3.6). DB migrations (alembic) keep the tables in step with `version`.

### 3.1 Data file (one per raw upload)

Path example: `data/korean/<book>/02-introduction/2-1-vocabulary.json`

```jsonc
{
  "format": "memo.datafile",
  "version": 1,
  "id": "df_01JABCDEF...",                 // ULID, server-assigned
  "title": "2-1 · 어휘와 표현 · Vocabulary & Expressions",   // one plain line, not a language map
  "default_type": "bidirectional",         // optional; else inherited from category
  "source": {                               // provenance, all optional
    "kind": "image",                        // image | pdf | text | json | csv | anki | manual
    "files": ["raw/vocab1.jpg"],
    "page": 6,
    "context": {                            // free-form, LLM-proposed hierarchy
      "chapter": { "number": "02", "ko": "소개", "en": "Introduction" },
      "lesson":  { "number": "2-1", "ko": "저는 첸이에요", "en": "I'm Chen" }
    },
    "import": { "profile": "korean-textbook-vocab", "model": "…", "prompt_version": 3, "at": "2026-09-17T10:00:00Z" }
  },
  "groups": [
    { "id": "countries", "label": { "ko": "나라", "en": "Countries" } },
    { "id": "jobs",      "label": { "ko": "직업", "en": "Jobs" } },
    { "id": "additional","label": { "ko": "기타 추가 어휘", "en": "Additional Vocabulary" } }
  ],
  "notes": [
    { "id": "n_01J…", "group": "countries", "front": "러시아", "back": "Russia" },
    { "id": "n_01J…", "group": "additional", "front": "어느", "back": "what, which" },
    { "id": "n_01J…", "group": "additional",
      "front": "-씨", "back": "Mr., Ms.",
      "note": "Added after another person's name, never after your own.",
      "fields": { "romanization": "-ssi" } }
  ],
  "extra": {}
}
```

### 3.2 Note

| key | type | notes |
|---|---|---|
| `id` | string? | assigned on save if missing |
| `type` | `bidirectional` \| `directional`? | fallback: file → category → `directional`; unknown value → `directional` |
| `front` | markdown? | missing → note kept + flagged, generates no cards |
| `back` | markdown? | missing → note kept + flagged, generates no cards |
| `front_lang` / `back_lang` | string? | e.g. `ko`/`en`; inherited from category; only for fonts, TTS, duplicate detection |
| `fields` | map<string, markdown \| null>? | any extra data (romanization, examples…); unknown keys shown as key/value info after reveal |
| `accept` | { `front`?: string[], `back`?: string[] }? | **explicit** list of answers counted as correct when typed (from import or added during practice); missing → only the displayed text counts (see 3.5). Two conventions, both from the 2026-10-11 data fix: a gloss narrowed so the reverse direction can be answered (`this` → `this + 이 (subject)`) keeps the bare meaning in `accept.back`, so the forward direction gets no harder; and two words that share one gloss on purpose each carry the other in `accept.front`, which is what makes the shared gloss answerable either way |
| `modes` | string[]? | restrict allowed practice modes for this note (e.g. long sentence → no `build`); missing → all applicable |
| `note` | markdown? | footnotes, usage |
| `group` | string? | ref into `groups`; ungrouped allowed |
| `tags` | string[]? | free tags |
| `status` | `confirmed` \| `unverified`? | from review step |
| `confidence` | number? | LLM self-reported, for highlighting in review |
| `suspended` | bool? | exclude from practice |
| `priority` | `low` \| `high` \| `crucial`? | how often it should come up; **missing = normal**, and what the mark is worth is damped by how well the card is known (§3.5) |
| `extra` | object? | anything else |

`front`/`back`/`fields` values are Markdown + KaTeX (`$…$`, `$$…$$`), images by relative reference (`![](media/x.png)`).

### 3.3 Category config (inherited down the tree)

Stored as a row per category (`path`, `parent`, settings JSON); exported/imported as `_category.json`:

```jsonc
{
  "format": "memo.category", "version": 1,
  "label": { "en": "Korean" },
  "default_type": "bidirectional",
  "front_lang": "ko", "back_lang": "en",
  "practice": {                                // all optional, overridable per session
    "modes": ["flip", "typed", "choice", "match", "build"],
    "adaptive": true,
    "typed": { "script_aware": true }          // compare Hangul at jamo level
  },
  "import": { "profiles": ["korean-textbook-vocab", "generic"], "upload_page": true }
}
```

### 3.4 Note types & cards

- `directional` → one card `fwd` (front → back). Used for Q&A, equations/results.
- `bidirectional` → two cards `fwd` (front → back) and `rev` (back → front), scheduled independently
  (recognition vs. production). Used for vocabulary.
- Extra `fields` are shown on the answer side; nothing in them is required.
- More than two sides (e.g. ko + en + cs) doesn't fit: keep main pair in front/back, rest in `fields`;
  a `multi` type can be added later if really needed.
- **Card key** = `note_id + ":" + ("fwd" | "rev")` → used for scheduling and review logs.

### 3.5 Practice modes & answer checking

Card type (data shape) and practice mode (interaction) are **orthogonal**: any card can be practised in any applicable mode.

| mode | interaction | outcome |
|---|---|---|
| `flip` | reveal, judge yourself (Anki-like) | you pick |
| `typed` | type the answer; differences highlighted | checked (see below), overridable |
| `choice` | pick from N options; distractors from same group → data file → category subtree, same side/lang | checked, overridable |
| `match` | pair up items of a group/data file (e.g. 5 ko ↔ 5 en) | checked per pair |
| `build` | assemble answer from shuffled pieces (words, else grapheme clusters — §3.7) | checked |

Not applicable → skipped silently (`match` needs ≥ 3 notes in scope, `build` needs short text, maths → `flip`/`choice` until an equivalence checker exists).

**Mode selection** ✅ — adaptive, driven by the scheduler's own state (thresholds in config):

| card state | mode |
|---|---|
| new | `choice` / `match` |
| interval ≳ 1 day | `typed` recognition (`fwd`) |
| interval ≳ 1 week | `typed` production (`rev`), optionally `build` |

Overridable in category config and in the session start dialog ("force typed", "flip only", …).

**Queue order** ✅ — shuffled, with overdue priority kept (decided 2026-09-29, after noticing the queue was
handing the same page order back every session). Due cards are ordered by the **day** they came due, most overdue
first, and shuffled within that day; new cards are still *taken* in page order — you work through the book from the
front — but are *asked* in a random order. A note's two directions are pushed at least `SIBLING_GAP` (4) cards apart,
relaxing only when the queue is too short to manage it: answering `→` then `←` back to back is answered from
short-term memory and teaches nothing. `due_queue(rng=...)` makes a session reproducible for tests.

**Amended 2026-10-11, for the mark**: a marked word sorts ahead of the backlog, not merely ahead of the rest of
today — "asked first" is no promise at all when forty other cards are overdue. Within one level the order above is
unchanged, and `_space_siblings` takes the mark as its *first* key rather than its last: every note with both
directions due was outranking the one word that had actually been asked for. The gap itself is not at stake either
way, because the `free` window is what enforces it.

**How often a word comes up** ✅ (asked for 2026-10-11: *"adding a priority to the words … test items with high
probability to appear"*). Four steps per word — `low` · normal · `high` · `crucial` — set one row at a time in
the file editor, and worth whatever **damping by mastery** leaves of them:

| | new | learning | known | mastered |
|---|---|---|---|---|
| `crucial` | ahead of high, and twice | ahead of high, and twice | first, and twice | first |
| `high` | first, and twice | first, and twice | first | — |
| `low` | last | last | last | last |

**Amended 2026-10-11**: `crucial` added above `high` and `quiet` renamed `low` (migration `e3b9c27d4f15`). The
user chose for `crucial` to damp one step later than `high` and **never all the way**, so a mastered crucial word
is still asked first. Push `3 / 3 / 2 / 1`. In the editor the control is a **segmented −1 · 0 · +1 · +2** under its own
"priority" column header, the chosen segment filled cool → warm (low `--accent`, normal `--muted` grey so it still
reads as a choice, high `--almost`, crucial `--bad`); the sheet shows the same number as a coloured tag.

**Amended 2026-10-11, for `low`**: *"Mastery should not be necessary for them (unless all other is mastered)."*
Display only, by the user's choice: on the Progress bars (and the sheet's summary) a **known low word counts as
done** while any other card in the same scope is short of mastered; once everything else there is mastered it has
to be mastered too. The scope is whatever the bar is for — a file judges the file, a category its whole subtree.
The rule is `overview/progress.py:_count`; `mastered` in `/progress` now means done, and `settled` says how many of
those are such low words. A card's own bucket, the word lists, scheduling and mode choice are untouched — nothing
in practice ever pushed a card toward mastery in the first place.

`push` is `3 / 2 / 1 / 0 / -1` (`practice/priority.py`); `2` is also what asks the card a second time inside the
sitting, which the client does through `SessionOptions.twice` rather than by putting the card in the queue twice.
Nothing is stored and nothing expires: the bucket comes from `standing()`, which is re-read from the append-only
log, so a word that starts going wrong is demoted by the accuracy window and gets its push back unasked — *"the
priority effect gets damped with mastery, shoots back again if the mastery drops."* `low` is **not** damped;
damping withdraws a boost a word no longer needs and has no business overruling "I care about this one less".
The bucket is the card's, not the note's, so a word mastered `→` keeps its push on `←`.

Deliberately **not** part of it, having been offered and declined: shorter intervals for marked words, and marks
winning the bring-forward slots (those stay soonest-due-first). The third refusal, a *"practise only the marked
ones"* filter, was **reversed on 2026-10-11** — see "A list for a test" below. Not for marks, though: what the
user actually wanted was a *set*, which is a different thing from a mark, and marks still never get a filter.
Distractors never see a mark. `standings()` is not called at all unless something in scope is marked, so an
unmarked collection costs exactly what it did.

**A scope you chose is never a dead end** ✅ (asked for 2026-10-10, from the first phone session: *"I want to
be able to practise any file I want — and master it even though I have not started learning other files.
This is crucial."*). Picking a lesson whose cards were all scheduled for later used to answer "nothing to
practise right now", which is the app telling you to come back tomorrow about a book you own. Now, once the
due and new cards run out, `due_queue(ahead=True)` brings the **soonest-scheduled** cards forward to fill a
session of 20, flagged `early`. Three things make that safe rather than destructive:

- **An answer given well ahead of time counts but does not reschedule.** `schedule_answer` returns the state
  it was handed, with `reps` and `last_review` moved on, when the card has more than `EARLY_FLOOR` (a day)
  still to run. Not a floor on the due date, which is what it looks like it should be: neither scheduler
  moves `due` backwards on a success, so there would be nothing to catch. The loss is elsewhere — SM-2
  ignores elapsed time and restarts the same interval from today, forfeiting the remainder, while FSRS reads
  it and damps the stability gain, which shortens the interval and writes it into `data`. Measured on a
  163-day card answered Good: **163 days if answered the same instant, against 498 answered on time.**
  A miss is exempt: getting it wrong early is the best information the system can get, and the card has to
  come back. The rule is a pure function of `(state, now)`, so `replay` reaches it from the log alone —
  tested for both schedulers, including for a row that arrives days late from a phone.
- **The floor is a day, and a constant rather than a fraction.** It is what stops practising ahead stalling:
  a card due within the day advances normally, so a session still clears. `due - now > 1 day` is only
  reachable from `State.REVIEW` with an interval over a day, so the rule's domain is exactly mature cards.
- **Mastery never needed this.** `standing()` already scored each card from its own log rows, so mastering
  one file never depended on another. It was only the queue that stood in the way.

**No cap on new cards** ✅ — `new_limit` was 20 by default; it is now `None`, meaning all of them, and the
setup screen's number is left empty. How much to take on in one sitting is the user's call, not a policy.
A whole 52-card lesson in one go is a legitimate thing to ask for.

**The queue says what the scope holds** ✅ — `QueueOut` carries `due_count`, `new_count`, `ahead_count`,
`total` and `next_due`. An empty list used to be all the client was told, so the screen hard-coded one
sentence — "every card here is scheduled for later" — and said it for an empty file, an all-suspended file
and a `new_limit` of 0 alike. It can now tell *caught up* (and when the next card comes round) from *there
is nothing here*.

**Distractor scope** ✅ — a setting, not a hidden rule: `auto` (default: same group → data file → category subtree until
enough options) · `group` · `file` · `category`. Per category, overridable per session; all four ship in the MVP.
Within the chosen scope, prefer candidates of similar length/script so the answer doesn't stand out.

**And a wrong answer has to be wrong** ✅ (added 2026-10-11). A candidate that answers the *same question* is never
offered, alongside the existing bans on the right answer itself and on anything in its `accept` list. Two notes glossed
"that" are a thing an extractor makes by accident, and without this rule a four-option question built from them has two
right options with one of them marked wrong — which does not merely feel unfair, it teaches the wrong thing. `Candidate`
carries its prompt for this and nothing else.

**And recognising is for words still being recognised** ✅ (added 2026-10-11). `matchRound` took any card not yet
answered this session, which meant a word held for a fortnight kept being dropped into a matching grid — and
`RECOGNITION_CAP` then pinned it at a one-day interval, for ever. Measured on the real log before fixing it: of the 98
cards never once answered wrong, **72 were still at ≤ 1 day, and 71 of those had last been answered by `match` or
`choice`**. So the daily pile was not a backlog; it was the whole collection, held at one day by the exercise it was
being given. A round now takes only cards whose own `suggest` is a recognition mode, which is what the comment above
it already claimed. The cap itself is unchanged.

**How much is one sitting** ✅ (asked for 2026-10-11: *"sometimes I wish to just press Practice but I do not want to do
all 190 cards"*). There was no cap on a session at all — `new_limit` bounded only the new cards, and `due_limit` (200)
was exposed nowhere, so Start meant the entire pile: 256 cards and about an hour. Now `due_queue(limit=…)` sizes the
whole sitting, due cards included, and the start screen offers four named steps per device (`short` 20 · `normal` 40 ·
`long` 80 · everything), **`normal` by default**, each labelled with how long it will take.

- The estimate is **measured, not assumed** (`overview.progress.pace`): the median of the last 200 timed answers times
  how many answers one card takes in a day, because the in-session loop asks a missed card again until it is right
  twice. On the real log that is 8.7 s × 1.96 ≈ 17 s a card. `null` with too little history, and the screen then
  assumes 15 s.
- `NEW_SHARE` (a quarter) of a sized sitting is held for cards not met yet, so a backlog cannot own every session and
  leave the lesson it came from standing still. Whichever side is short, the other fills the room (`_shares`).
  `new_limit` survives as a *ceiling* on that share.
- **The screen says nothing about how much is waiting** — the step labels read "up to 40 cards", and *Everything*
  carries no number, because that number is the size of the pile and phase 3 took due/new counts out of the UI.
- Bringing cards forward is bounded by the size too: `ahead` is there to rescue a scope with nothing due, not to
  overrule how much was asked for.
- Offline, the kept batch is several sittings' worth on purpose, so the same rule is restated in
  `offline/batch.ts:sized` — a phone with no signal has to answer the question by itself.
- And a `match` pair now logs its `duration_ms` (the time since the grid appeared, or since the pair before it). It
  used to log none, which was **379 of 1053 rows** untimed — and the pace above is read off exactly those.

#### Answer checking — learning first, grading second ✅

The check produces **one of three outcomes**, never a numeric score:

| outcome | when | what the app does |
|---|---|---|
| `correct` | matches the shown answer or an entry in `accept`, after normalisation (Unicode NFC, whitespace, case, trailing punctuation) | continue |
| `almost` | differs by one or two units in Unicode NFD (§3.7): `학생`→`학샘` and `café`→`cafe` are each one unit | show the diff, **repeat the card later in the same session**, offer "that's the same thing → add to accepted" |
| `wrong` | anything else | show the answer, repeat in the same session |

"Slightly" is a small, fixed, readable rule (edit distance ≤ 1 for short answers, ≤ 2 above ~8 units, transposition counts as one),
not a tunable similarity score. No timing, no weighting formulas.

**Where accepted answers come from** ✅ — never guessed from punctuation at runtime (`N이/가` and maths would break):

1. **From the import**: the extraction asks the LLM for a `display` string *and* an explicit `accepted` list
   (it understands that `I/me (honorific)` means `I` and `me`, `what, which` means either). Shown as editable chips in the review screen.
2. **From practice**: when a typed answer is `almost` or `wrong` but you consider it right, one click adds it to `accept` in the data file.
   The collection gets better as you use it — no heuristics needed.
3. **Nothing else**: with no `accept` list, only the displayed answer counts. Markdown/KaTeX markup is stripped before comparing.

**Learning loop, not a scorekeeper**: a session keeps a queue; anything not `correct` comes back before the session ends
(default: needs to be right twice). Whether a card also advances in the scheduler is a separate, simple rule:

- `correct` in a productive mode (`typed`/`build`) → advances normally.
- `correct` in a recognition mode (`choice`/`match`) → advances at most to "learning", never to a long interval.
- `almost` → treated as "needs practice" (repeat soon), not as failure.
- Any outcome can be overridden by you ("I knew it" / "I didn't").
- **Amended 2026-10-12**: two more overrides on a miss. *That's a typo* counts it `correct` (Good, overridden) without
  touching `accept` — a slip of the fingers is not another way of saying the word. *Not this session* counts it `wrong`
  (Again; overridden when the checker had said `almost`) and takes the card out of the session instead of bringing it
  back: it stays due, so it comes back next sitting. Offered on every miss, and under the grades in `flip`.

The review log keeps the evidence, so a smarter scheduler can be added later without losing history:
`mode, direction, raw_answer?, outcome, overridden, final_grade, duration_ms` (duration is recorded, not used).

### 3.6 Two schemas, not one ✅

The storage format above is lenient (optional fields, unknown keys kept). Strict LLM structured output is the opposite
(`additionalProperties: false`, every property required), and some OpenAI-compatible providers support no structured output at all.
So there are **two Pydantic models and an adapter**, not one shared schema:

| | storage model (`memo.datafile`) | extraction model (LLM-facing) |
|---|---|---|
| shape | nested, optional everything, `extra="allow"`, IDs, provenance, review state | flat, small, no IDs, no provenance, no review state |
| types | unions, maps, markdown | strings / string lists / null only, fixed keys |
| purpose | on-disk truth, migrations | one LLM response |
| schema | JSON Schema for validation + TS types | strict JSON Schema, all keys required, nullable where empty allowed |

`extraction → storage` is one adapter function (assigns IDs, attaches provenance, sets `status: "unverified"`), unit-tested against
the golden fixture. Consequence: the storage format can grow without touching prompts, and prompts/extraction shapes can differ per importer.

**Provider capability tiers** (detected once by a probe at configuration time, stored as `structured_output: json_schema | json_object | text`):

1. `json_schema` — send the strict schema, parse directly.
2. `json_object` — JSON mode without schema: schema goes in the prompt, response validated, up to 2 repair retries with the validation errors.
3. `text` — schema + example in the prompt, extract the JSON block, same repair loop.

All three end at the same validated extraction object, so the rest of the pipeline doesn't care. Vision support is probed the same way.

### 3.7 Language neutrality ✅

The app is not a Korean app; Korean only shapes the *content* and the *extractor*. Practice logic therefore has **no
language branches** — two generic Unicode rules cover what looked Korean-specific:

| need | generic rule | Korean | English |
|---|---|---|---|
| how different two answers are | compare in **Unicode NFD**, edit distance over code points (transposition = 1) | syllable decomposes to jamo → `학생`/`학샘` = 1 | `café`/`cafe` = 1 |
| split an answer into pieces (`build`) | several words → whitespace; otherwise **grapheme clusters** | one tile per syllable block | one tile per letter |
| which script this is (fonts, TTS, sorting) | `front_lang`/`back_lang` inherited from the category | `ko` | `en` |

Per-category overrides exist where content needs them (maths: split on terms, never on characters), but the defaults need no
configuration. Nothing else in practice, scheduling or the data model mentions a language.

## 4. Import pipeline

**One import job = one or more raw files = one data file** ✅ (a lesson usually spans several photos).

```
upload N files (images / pdf pages / text / json / csv / anki)   → import job
  → store raw files (kept next to the data file), keep page order (user can reorder/rotate/crop, drop pages)
  → pick importer  ✅ cheap LLM "router" call on page 1 proposes one; preselected in the UI, user can override
                   ✅ (2026-10-14) only when there is something to choose: with the general reader alone, no call
      • general reader         ✅ (2026-10-14) the prompt from docs/llm-prompt.md, answering in data files
      • local importers        ✅ (2026-10-14) e.g. korean-textbook-vocab, a spec in importers.local/, out of git
      • no-LLM paths           json (validate), csv (column mapping), anki .apkg (read sqlite)
  → per page: LLM extraction call (parallel, capability tier from 3.6) → validated extraction object
  → merge pages: concatenate in page order, carry group/context headings across page breaks,
    drop within-job duplicates (same front+back), keep per-note `source.page`
  → REVIEW: pages side-by-side with editable rows; flags: empty side, low confidence, duplicates
    against the existing tree ✅ (shown as "already in 2-1" → keep both / skip / merge into existing),
    and ✅ (2026-10-11) the same *meaning* on a different word — "same meaning as 그것 in 2-2" — which is
    the flag that would have caught the 그것/그게/그건 glosses before they were practised for four days;
    accepted-answer chips editable; accept / edit / reject per row
  → target: new data file at an LLM-proposed (editable) path,
            OR append to an existing data file — existing notes keep their IDs and progress,
               new pages are appended, matching notes (same front) are offered as "update text" or "skip"
```

Re-import and "add more pages later" are therefore the same operation: run the job, choose *append to* the existing file.
Importers are files (prompt template + extraction shape + example output), so new known formats need no code.
PDF: rendered to page images (vision) or text-extracted, per importer.

### 4.1 The general reader, and importers that stay on one machine ✅ (2026-10-14)

Going public, the built-in importer had to be one that works for anyone's material, and the textbook one
is niche. Decided with the owner:

- ✅ **The app reads photos with the prompt from [docs/llm-prompt.md](docs/llm-prompt.md), word for word.**
  It is a package file (`importers/prompts/general.md`), and `tests/test_docs.py` fails if it and the
  doc's block differ: one prompt to get right, whether a person pastes it into a chat or the app sends it.
  It answers with whole `memo.datafile` objects in fenced JSON blocks, so the call is plain text whatever the
  provider's tier, and the extraction tiers' repair loop stands in for a schema. Several objects from one
  page, or from several, merge into the job's one draft. The model's ids, statuses and provenance are
  thrown away, as an uploaded file's are.
- ✅ **"My instructions" is filled by the app**: which photo of how many and, if given, its printed page;
  the category's path, languages and default type as defaults; then whatever was typed in *Anything the
  reader should know*, last, since the prompt lets it override.
- ✅ **Two kinds of importer**: an extraction importer (strict shape → adapter, PLAN 3.6), kept as the
  framework for narrow readers on weak providers, and a data-file importer like the general one. The old
  `generic` extraction fallback is gone; its name is an alias of `general`, so old jobs can be retried.
- ✅ **Local importers live in `backend/importers.local/`** (gitignored; `MEMO_IMPORTERS_DIR` moves it).
  A `.toml` spec is the documented form; a `.py` module defining `IMPORTER` is the escape hatch, and runs
  as code. A file that does not load is skipped and reported (`memo importers`), never fatal; a local
  name cannot take a built-in one. Read on every upload, so an edited spec needs no restart.
- ✅ **The Korean importer ships as an example**, `backend/examples/importers/korean-textbook-vocab.toml`,
  not loaded by default. It holds layout rules, no book content, and the tests run against that folder,
  so every machine sees the same importers.
- ✅ **PDFs go to the model too**, through the same importers, a few pages per call
  (`pdf_pages_per_call`, 5): the person picks *its text* (cheap, any model) or *its pages as pictures*
  (tables, layout) at upload, and a chunk with no text is sent as pictures regardless. The old reader
  that split a PDF's text into pairs is gone; it rarely worked on real material. Pages are numbered
  across the whole upload, so a printed first page carries through a PDF to the photo after it.
- ✅ **An importer that is not installed is an error**, not a silent fallback: a 400 on upload, a failed
  job on retry. Old drafts and files naming it still load; the name is only ever displayed.

## 5. Architecture ✅

```
backend/   FastAPI · Pydantic v2 · SQLite (SQLAlchemy + alembic) · uv
           services: collection (categories/notes/cards CRUD), import (jobs, LLM adapters, importers),
                     io (data-file import/export, round-trip), scheduler (interface + impls),
                     auth (shared password → session cookie)
frontend/  SvelteKit (static adapter, PWA) · types generated from OpenAPI · markdown-it + KaTeX
           practice widgets (flip/typed/choice/match/build) · answer checker (single implementation, see below)
var/       memo.db (truth) · raw/<category>/… uploaded photos & PDFs (filesystem, served statically)
```

**Storage = option D** ✅ (`docs/storage-options.md`): SQLite holds categories (tree table with materialised path),
notes, cards, import jobs + drafts, review log and card state. Rationale: the learn views need queries across the whole
collection, import staging and concurrent writers are natural in a DB, and with a CRUD UI nothing has to be hand-edited.

- **Tables mirror the format**: `note(front, back, front_lang, back_lang, fields JSON, accept JSON, note, tags JSON, group_id, status, extra JSON)`
  — `fields`/`extra` keep unknown keys, so null tolerance and lossless round-trip survive the move into a DB.
- **Raw uploads stay on the filesystem** (big, write-once, cheap to lose), referenced by relative path; DB stores the reference.
- **Export is manual** ✅ — an "export collection" action writes the data-file tree (phase 2); no auto-export, no git automation for now.
  A round-trip test (export → import → compare) guards the format regardless.
- **Backup** = `memo.db` (via `VACUUM INTO`) + the raw directory.

- **Android later**: same API; either wrap the PWA (Capacitor — cheapest) or a native Kotlin client using the generated schema. Nothing in the backend blocks either.
- **Scheduler** ✅: SM-2 and FSRS (py-fsrs) both implement one interface, chosen per profile/category, compared on the same log.
- **Scheduler state**: `review_log(profile, card_key, ts, mode, raw_answer, outcome, overridden, final_grade, duration_ms, scheduler, state_before, state_after)` is append-only; current state is a cache recomputable from logs.
- **Answer checker: one implementation, in the client** ✅ (TS, dependency-free package). Checking must be instant and must keep
  working offline later; with a handful of trusted users there is nothing to cheat at, so the server does not re-check. It stores
  `raw_answer` + `outcome`, which is enough to re-evaluate later (or to port the checker) if that ever becomes necessary.
  A JSON test-vector file (`answer, accepted, expected outcome`) is the checker's spec — a Python port, if ever needed, must pass the same file.
- **Deployment** ✅ (revised 2026-10-10, `docs/serving.md`): `uvicorn` on the laptop, reached from the phone
  over **Tailscale**, which terminates TLS and so makes the page a secure context. That is not a preference:
  a service worker — and therefore offline practice at all — is refused outside one, and a LAN address is
  not one. One Docker image + `var/` volume when an always-on box is bought. No PaaS.
- **Auth**: shared password (argon2 hash in config), login rate-limited, then profile picker (no per-profile password).

## 6. Phases ✅ (slicing is my proposal, contents decided)

Each phase ends with something usable; "done" is stated so a phase can't silently sprawl.

**Phase 0 — foundations** *(no UI)* — **built**, see `backend/` and `backend/README.md`
- ✔ SQLite schema + alembic baseline; storage model + extraction model + adapter; JSON Schema export (`backend/schema/`)
- ✔ Data-file import/export functions (round-trip test) — the format is exercised from day one
- ✔ Golden fixture: hand-verified data file for `vocab1.jpg` (`backend/tests/fixtures/vocab1.datafile.json`)
- ✔ LLM adapter + capability probe; CLI: `memo import <images…> → draft JSON`
- **Done when**: `import data/korean/raw/vocab1.jpg` produces a file that differs from the fixture only in ways you accept, and the fixture round-trips through load/save unchanged.
- **Status**: the round-trip holds (file → file and file → SQLite → file, byte-identical), and the pipeline reproduces the
  fixture from a recorded extraction. The half that needs a real provider — a live vision call on the photo — is still
  unrun: it needs `MEMO_LLM_API_KEY`. `backend/README.md` has the one command and the `diff` that judges it.

**Phase 1 — the thin path** *(first usable version)* — **built**, see `backend/`, `frontend/`, `spec/`
- ✔ Password gate, single profile (picker comes with phase 4)
- ✔ Category tree browsing; per-category upload of one or more images → extraction → review screen → data file
- ✔ Practice: due queue for a subtree, `flip` + `typed`, session re-queue until learned, "add to accepted" button
- ✔ Scheduler interface with SM-2 and FSRS implementations, switchable
- ✔ Answer checker in TS (`frontend/packages/answer-check`), specified by `spec/answer-check.{md,vectors.json}`;
  §1.2 folds every printed dash to `-` (and drops the soft hyphen), so an en dash the model read off the page
  never costs you the answer — the card keeps the dash it was imported with, only the comparison ignores it.
  `collection/editing.py:normalise` folds the same set, so `–씨` and `-씨` are flagged as duplicates of each other.
- **Done when**: you photograph a textbook page, correct it on screen, and practise it the same day — on your phone's browser.
- **Status**: the whole path was driven in headless Chromium against the real server (sign in → category → upload
  `vocab1.jpg` → review, reject a row → commit → practise typed, with an `almost`, "that's the same thing" and a miss),
  at desktop and phone width, with a stand-in provider replaying the fixture. The real provider has since been run
  too (2026-09-29, `kimi-k3`: multimodal, strict `json_schema`): `vocab1.jpg` came back as 32 notes in 3 groups,
  matching `tests/fixtures/vocab1.extraction.json` note for note — so the stand-in is faithful. The only difference
  was the en dash in `–씨`, which is what prompted the dash folding above. Not yet done: a session on an actual
  phone (`memo serve --host 0.0.0.0`).
- Choices made while building, all easy to change: FSRS is the default scheduler; FSRS interval fuzzing is off (so card
  state can be rebuilt from the log); `almost` → grade Hard; a card right first time leaves the session, a missed one
  must be right twice; in-session repeats are logged and scheduled like any other answer.

**Phase 2 — editing and import breadth** — **built**
- ✔ Manual note CRUD — a grid editor per data file (`/files/<id>`): rows save as you leave them, Enter adds a row,
  a detail panel holds type, accepted answers, note and suspended; the file's title, languages and default type are
  editable in its header
- ✔ Category tree management: create, rename (the branch's paths follow), move, delete when empty, bilingual labels
- ✔ Duplicate detection across the whole tree — reported on the row, never blocking, "keep both" dismisses it
- ✔ Multi-page jobs with append-to-existing-file (the upload picks the file the pages join), page reorder, and
  rotate/crop done in the browser before the upload, so the model only ever sees the picture you approved
- ✔ Ready-made JSON, CSV/TSV, plain text, Anki `.apkg` and PDFs with a text layer — read without a model, into the
  same draft → review → commit path; a scanned PDF says to photograph it instead
- ✔ Manual export of a category/collection to data files, into the repo's `data/<category path>/` tree
- ✔ Where something lands is a choice, not whichever row you pressed ✅ (decided 2026-10-01): the same category
  picker — every category, plus "+ new category…" which makes a whole path — sits on the upload screen, on the
  review screen (where the commit button names the destination: *Add 31 to 02 Introduction*) and in a data file's
  header, so a file in the wrong place is moved, never re-imported. A staged import can also be discarded, photos
  and all; a committed one cannot, because the notes point at it.
- ✔ A data file's title is one plain line ✅ (decided 2026-10-01): it used to be a label map, shown joined as
  *native · English*, and the header's box wrote whatever it showed back into the English slot — so every rename
  prepended the native title again. A file now has a single name, whatever scripts it mixes, and the import names
  it *number · native · English* (`2-1 · 어휘와 표현 · Vocabulary & Expressions`). Groups and categories keep their
  label maps; only the title changed. Migration `b1c7a9d4e2f3` joins the old ones.
- ✔ Nothing counts down ✅ (decided 2026-10-01): no "N due" or "N new" anywhere — not in the tree, not on the
  *Practise everything* button, not on the practice start screen — and the end of a session says only *Done*,
  with no score for how many were right first time. The app holds the collection and answers what is in it; it
  does not tell you what to do with it today. What is left is inventory (how many notes a category holds), the
  position in the session you are actually in, and a staged import saying it is ready to read.
- ✔ **A gloss has to be answerable backwards** ✅ (asked for 2026-10-11: *"'that' appears multiple times, with or
  without topic as subject marker. It's impossible to then decide which one the app wants"*). A note's back is the
  answer going one way and the **prompt** going the other, which the import had not reckoned with: asked what 그게
  means the model said "that", exactly as it did for 그것 and 그건, so the reverse direction asked one question with
  three right answers. Three separate defects came out of one audit of the 210 live notes, and each wanted a
  different fix:

  | | | |
  |---|---|---|
  | 8 contracted forms | 이게 이건 · 그게 그건 · 저게 저건 · 저것 · 누가 | the gloss **names the particle** — `this + 이 (subject)`, `this + 은 (topic)` — with the bare meaning kept in `accept.back` so the forward direction got no harder, and the uncontracted form in `note`, where 누가 already had `누구+가 → 누가` |
  | 7 exact duplicates | 교실 학교 사다 닫다 배우다 만나다 (3-1 ∩ 3-3), 누구 (2-2 ∩ 2-3) | the lesser copy is **suspended**, not archived: 3-3 *Expanding Vocabulary* re-lists lesson 3's words faithfully, so the word stays in its sheet and only leaves practice. The copy holding the history is the one kept |
  | 3 synonym pairs | 뭐·무엇 · 밑·아래 · 공·영 | **cross-accepted both ways**, finishing what the import half-did (영 accepted 공; 공 did not accept 영). These keep one shared gloss on purpose, and `memo audit` reports them as deliberate rather than going quiet |
  | 1 mis-gloss | 회사 "office" | → `company`, with "office" kept in `accept.back`. The one place the fix overrules the book |

  Two tools, because there was no way to do any of it. `memo audit` is the read-only check that would have caught
  this at import; `memo patch` applies a reviewed file of `{id, expect, set}` through `update_note`, dry-run by
  default, refusing the whole file if a note is missing or holds something other than what the patch expected, and
  **comparing the card and review-log counts across the write**. The alternative — editing the exported
  `data/korean/*.json` and re-importing — is not an edit: `store_datafile` only inserts and the importer blanks
  every id, so it would have made 20 new notes with no history. The patch file is kept at
  `backend/patches/2026-10-11-glosses.json`.

  **What it cost, measured on a copy before it ran**: 420 cards and 1053 answers unchanged, as `card_key` has no
  text in it. Suspending the seven copies took 14 cards out of what `/progress` counts — ten of them `new`, four
  `learning` — so the collection reads 406 cards with `known` 16 and `mastered` 15, both untouched.
- **Done when**: a whole textbook chapter (several photos, added over several days) is one data file with no duplicates, and export → import reproduces it exactly.
- **Status**: driven in headless Chromium against the real server — a file typed by hand, a category renamed and
  moved, a CSV imported, a photo turned and cropped before upload, a second photo added to the file the first one
  made (with every repeated row flagged), and the whole collection exported to `data/`. Export → import → the same
  notes is a test; the exported file keeps the name it has on disk, so retitling never scatters copies.
  The destination controls were driven the same way (2026-10-01, against a copy of the real database): a file moved
  out of the category it was imported into, an import retargeted and then discarded, a category created from the
  upload screen at phone width. They came out of a real miss — a lesson imported into `statistics` — which also
  turned up a bug: a category that renders expanded (the roots do) only fetched its data files when clicked, so a
  committed import under a root looked like it had vanished. `TreeNode.svelte` now loads them when it renders.
  The plain title and the removed counts were verified the same way (2026-10-01, same copy): the title typed into
  the header survived three reloads unchanged where it used to grow a copy of the native name on every one, and
  the collection, the start screen and the end of a session carry no due/new counts.
- Choices made while building, all easy to change: deleting is archiving (`archived_at` on notes and files) — an
  archived note keeps its cards and its place in the review log, leaves practice, counts and exports, and can be
  restored; duplicates are matched on the normalised front across the whole tree, and say whether the back matches
  too; a category is deleted only when it is empty, so notes can never go with it by accident; export leaves files
  it did not write alone and reports them; a re-imported data file gets new note IDs, because progress belongs to
  the collection it is in; raw photo references keep their job folder, so two photos called `vocab1.jpg` stay two.

**Phase 3 — practice depth** — **built**
- ✔ `choice` — four options ✅ (decided 2026-10-08): the answer plus three distractors, picked server-side from the
  same alphabet and a similar length so nothing is answerable by elimination. A wrong pick marks what you chose,
  shows what was right, and the card comes back later in the session — the same loop a wrong typed answer gets.
- ✔ `match` — five pairs, tap one side then the other ✅ (decided 2026-10-08): a right pair locks, a wrong one
  turns both red and says so. **Each pair is logged for its own card**, correct only if it was paired first try,
  so a word you knew is not dragged down by one you fumbled. A round is offered when the queue holds four or more
  unanswered cards from one heading (then one lesson, then the session), and only once every `MATCH_GAP` single
  cards, so a session is mixed rather than a wall of grids. ✔ **Which** cards is drawn, not decided (2026-10-08):
  the scope still narrows the same way, but a heading of twelve words would otherwise always give up the same five,
  and two headings that could both fill a grid would always be settled by whichever is longer. Both are now random;
  the longest-first rule is kept only where no pocket holds a whole round, since there it is the only way to reach
  four pairs at all.
- ✔ `build` — tiles from the answer: words when there are several, grapheme clusters otherwise (§3.7), with a
  length window so one tile is not a puzzle and twelve is not a chore.
- ✔ Mode selection ✅ (decided 2026-10-08): **adaptive with a session override**. The server sends a `suggest`
  per card from that card's own state — new or under a day → `choice`, under a week → `typed`, beyond → `build`
  when the answer can be cut up — and the start screen can force one mode instead ("Let the card decide" is the
  default). A mode that cannot be shown falls back towards typing, never towards nothing; a category's
  `practice.modes` and a note's own `modes` narrow what may be suggested at all.
- ✔ Distractor scope — `auto | group | file | category` on the queue request, defaulting to the category's
  setting; the start screen offers it per session.
- ✔ Where the settings live ✅ (decided 2026-10-08): **in the category's ⋯ panel**, beside its name and labels —
  which modes this branch allows, and where its options come from. Both inherit down the tree (the panel shows
  what it would inherit until you tick "set here"), and the start screen overrides either for one session.
  *Practise everything* has no one category to ask, so it offers what every root agrees on: a mode only one
  subject allows is not offered across the whole collection, and the scope falls back to `auto` where they differ.
- **Done when**: a session mixes modes sensibly, and switching SM-2 ↔ FSRS changes nothing but the intervals.
- **Status**: driven in headless Chromium at phone width against a copy of the real collection (2026-10-08): a
  matching round of five, including a deliberate mis-pair, then choice and typed cards, with the progress counter
  and the in-session requeue following. The review log shows the recognition cap doing its job — `choice` and
  `match` answers never earned more than a day, while a `typed` answer on an older card earned 23.
  Two bugs surfaced on the way, both fixed: imported data files all carried `position = 0`, so a session
  interleaved six lessons instead of working through the book (the import now numbers them, and the queue breaks
  a tie by the file's age); and the practice page tracked the session through a counter read for its side effect,
  which the production build dropped — the progress bar sat at 0 all session. The page now mirrors what it shows
  in plain state and refreshes it after every answer.
- Choices made while building: a card that has already been answered this session is never hidden in a matching
  grid, so a word you missed comes back on its own terms; a `match` round answers cards in whatever order they
  are paired, which is why `Session.recordItem` exists beside `record`; anything held in Svelte `$state` is a
  deep proxy, so answers are always recorded against the item the `Session` itself holds, found by card key.

**Phase 4 — overview / learn** — **study sheets and progress stats built**; profiles and LLM
categorisation deferred ✅ (decided 2026-10-08: build the reading half first)
- ✔ Study sheets ✅ (decided 2026-10-08): a data file opens as a **sheet**, and a read/edit toggle
  flips the same page into the grid editor — reading is what a file is usually opened for, editing is
  asked for. The sheet carries all four of: **cover the answers** (a toggle, tap a row to reveal it,
  nothing logged — reading is not practising), a **progress marker per row**, a **print layout**, and
  **practise from here**, per file and per heading.
- ✔ Three buckets ✅: a card is `new` (never answered), `learning`, or `known` once its reviews are
  **21 days apart or more** — Anki's mature line, and about where an interval stops being counted in
  days. A note is marked as its *weaker* direction, so the sheet shows the hole rather than the best case.
  **Superseded 2026-10-09** by "Mastery by success rate" below: four buckets, read from the review log
  instead of the interval. The weaker-direction rule survives unchanged.
- ✔ Progress stats ✅ (decided 2026-10-08): **all three** — mastery bars, a weak list and a heatmap, on
  their own `/progress` page. Nothing counts down and nothing is a percentage; the collection view stays
  as bare as phase 3 left it. Bars are drawn per category *and* per data file, because a collection of
  one subject and six lessons has one useful bar and six.
- ✔ Weak ✅: ranked by misses in the last 30 days together with lapses, never a score — a recent *again*
  counts double an old lapse, because the list is for what to look at now. "Wrong" is the scheduler being
  told *again*, which catches judging yourself wrong on a flip, where the checker never saw an answer.
- ✔ The heatmap is drawn in the **client's own days**: it sends its offset from UTC, so a session at five
  in the morning in Seoul is that morning and not the night before in London.
- ✔ **Finding a word** ✅ (asked for 2026-10-11: *"the management and retrieval of cards is difficult at
  the moment"*). There was no search of any kind: no endpoint took a text query, and `GET /files/{id}/notes`
  was the whole note-reading API, so every path to a word ran Collection → category → file → read a
  fifty-six-row grid. `GET /notes/search?q=` (`collection/search.py`) is a **scan**, for the reason
  `find_duplicates` already gives — the collection is one person's and `normalise()` has no SQL equivalent —
  over both printed sides, every `accept` spelling, the free-text note, the heading and the lesson title.
  Ranked by **tier, then exactness, then side**, so a file title (thirty-two notes at once) comes last
  however exactly it matches. It finds **suspended** words on purpose: hiding them is the whole job of
  `_practisable()`, which is exactly why a word set aside could not be found.
- ✔ **Links land on the word** ✅: `?note=` scrolls the row into view and fades a wash off it. The audit
  card, the Progress word lists and the weak list all used to arrive at the top of a lesson, so acting on a
  finding meant reading the sheet by eye to find the word again.
- ✔ **A list for a test** ✅ (asked for 2026-10-11: *"it is clumsy to change priorities of all items for a
  test. Is there an elegant way to implement sth like default-priorities overload via a test sub-collection
  or something, or would that break the main scheduler?"*). The diagnosis first: `priority` is **permanent
  and global**, so using it for a temporary scoped job leaves sediment — 119 of this collection's 210 words
  had ended up `high` or `crucial`, evenly across all six lessons, and a boost covering 57% of a collection
  boosts nothing. The answer is a **named list with a date** (`word_list`, `word_list_note`, migration
  `f1a4d8e62c37`): a *selection, not a place*, so notes stay in their lesson with their own marks and their
  history. **Marks carry importance, lists carry urgency**, and the 119 existing marks were left alone by
  the user's choice.
  - **It cannot break the scheduler**, which was the question: priority and scope are read-time only.
    `replay()` reads `final_grade`, `mode`, `ts`, `overridden` and nothing else, and neither `card_state`
    nor `review_log` has a priority, scope or list column. A test set built as a **category** genuinely
    could, via `resolve_scheduler_name()` and `card_state`'s `(profile, card_key, scheduler)` key — and is
    not even reachable, since `NOTE_FIELDS` has no `data_file_id`.
  - **The focus is the half that expires**, by the user's own description: *"I can delete it manually (or I
    can activate it for a drill)"*. So the list is permanent until deleted and always drillable; only the
    dated push lapses, and nothing has to be remembered and undone.
  - **Both a drill and an overlay with a reserved share**, chosen over either alone. `FOCUS_SHARE = 0.5` is
    load-bearing rather than a nicety: an unmarked focused word pushes 1 and a `high` one pushes 2, so with
    no share held back the words marked before some earlier test would still go first. The other half keeps
    the rest of the collection alive during the week before an exam.
  - **`FOCUS_PUSH` is 1, not 2.** `TWICE_AT = 2` asks a card twice, so twenty focused words would be forty
    slots — a whole `normal` sitting. `push()` takes the better of mark and focus, so a `crucial` word on a
    list keeps its second ask; at `mastered` the focus is worth 0, because a test needs what you have not
    got. A pushed card shows the **list's name**, never a mark it has not got.
  - **Cramming cannot inflate intervals**, which was the one cost I expected to have to document: a drill
    brings words forward, and `schedule_answer` already counts an answer given more than `EARLY_FLOOR`
    ahead *without rescheduling the card*. The protection was there for "a scope you chose is never a dead
    end" and is keyed off the card's own `due`, so it applies to a drill for free.
  - Filling a list without a multi-select, which this app has never had: a list is turned on from its page
    and every search result and sheet heading grows a `+` until it is turned off. A heading or a whole
    lesson goes on in **one** tap, which is the only structural bulk gesture — a heading is already a set
    you think in.
- ✔ **Words beside a word** ✅ (asked for 2026-10-11: *"stuff like finding out synonyms and antonyms"*).
  `GET /notes/{id}/related` reuses `audit.py`'s matching down to `bare()`: `same-meaning`, `near-meaning`,
  `same-heading`, plus whether the pair already accepts itself both ways — which puts the audit's
  *one-sided* finding where you would act on it. **No antonyms, and there cannot be**: nothing in a note
  records that one word is the opposite of another, and generating it would mean presenting a model's
  guess about Korean as the collection's own, which the import prompts refuse to do. `same-heading` stands
  in for it, since a textbook prints 위 beside 밑 for that reason. `AuditOut` also stopped discarding
  `near` and `resolved`, which the API had been computing and throwing away.
- ✔ **A heading taken up again is one section** ✅ (2026-10-12, after moving 이집트 to *Countries* in 2-1
  blanked the sheet). Changing a heading never moves the word, so it sat mid-*Additional*; `sections()` then
  split the file into Countries · Jobs · Additional · Countries · Additional, and `Sheet.svelte` keys its
  sections by heading — Svelte 5 throws `each_key_duplicate` in production too. Fixed as the user chose:
  `sections()` **merges every run of a heading into its first section** before rendering, so each heading
  appears once and stays the key. The stored order is untouched and the grid editor still lists rows in file
  order; a reorder-on-closing-the-editor was built first and withdrawn.
- Deferred, with nothing built against them: **profiles** (the picker; the schema is already keyed by
  profile, so this is API and UI) and **LLM content-based categorisation / tag suggestions**, which needs
  live calls to verify.
- **Done when**: you can read a lesson like a sheet, and see what you're weak at without starting a session.
- **Status**: driven in headless Chromium at phone width against a copy of the real collection
  (2026-10-08): the 2-1 sheet with its three headings and 32 rows, every row marked from the real review
  history; covering hid all 32 answers and a tap revealed one; Edit and Read swapped the grid and the
  sheet; a heading's *Practise* started a session of just that heading; answering one card *Again* put it
  on the weak list with its file, heading and direction, and moved the heatmap and the counts. A covered
  sheet printed to A4 as a blank-answer worksheet, chrome gone, headings staying with their rows.
- Choices made while building: distractors for a lesson or heading session still come from the whole
  category, because five words cannot fill four plausible options; a sheet does not print a note's
  accepted alternatives, which are a practice detail (`what, which` is already the whole meaning); the
  markers are drawn in CSS rather than typed as ○ ◐ ●, which not every font has; an empty data file gets
  no bar, since it is not a lesson yet; mastery leaves out suspended and archived notes, while a sheet
  still marks them — the bars are what you are learning, the sheet is the lesson as it is written.

**Looks — one pass over every screen** ✅ (decided 2026-10-09: *cramped, and the contrast and colours are off*)
- ✔ **Roomy everywhere**, and **the language being learned is set larger than the gloss beside it** — a
  sheet row is 19px against 16px, a matching tile is 64px tall, nothing tappable is under `--tap` (48px).
  Fewer rows fit on a screen; that was the choice.
- ✔ Contrast and colour: every value is a token in `frontend/src/app.css`. The page sits further from the
  cards than it did, borders are visible, and the three buckets are **one family** (`--known` / `--learning`
  / `--unseen`) instead of green against mustard — a mastery bar now reads as one thing.
- ✔ **Light or dark is set in the app, per device** ✅ (decided 2026-10-09): Settings offers *follow the
  phone · light · dark*, kept in that browser's storage rather than on the server, because the laptop and
  the phone are read in different light. `app.html` applies it before the first paint, so nothing flashes;
  printing ignores it and is black on white whatever the screen is doing.
- ✔ Screen by screen: a session holds where you are at the top and the card in the middle of the screen
  (it used to pin everything to the top with two thirds of the phone empty); the category row no longer
  packs a name, a count and three buttons onto one line; the progress page names a lesson in full on its
  own line, keeps the weekday labels in view while the heatmap scrolls, and draws squares you can see; the
  grid editor keeps columns wide enough to read a long answer, and scrolls sideways rather than cutting
  every one of them in half.
- ✔ **Palette: `paper`** ✅ (decided 2026-10-09): the warm original, fixed. `crisp` and the `data-palette`
  plumbing are deleted.

**Looks, second pass — the whole UI/UX to best practice** ✅ (asked for 2026-10-09)

Four decisions were taken first, because "best practice" is not one thing: *the structure stays* (the
collection is still the home screen — no "Today" screen, no new information architecture), *navigation moves
to the bottom on a phone and stays in the header on a laptop* (withdrawn a day later — see below),
*rebuild the foundation and then refit every
screen* rather than only fixing behaviour, and *`paper`*.

- ✔ **A token layer, and nothing invents a value.** `frontend/src/app.css` now carries space on a 4px grid,
  a type scale, radii, durations and easings, layers, and the targets — and every one of the sixteen
  components was refitted onto it. What used to be `0.4rem` here and `0.45rem` there is `--space-2`
  everywhere. `.choice`, `.segmented`, `.back`, `.skeleton` and `dialog` moved into it, so the screens that
  shared a look now share the code.
- ✗ **Navigation under a thumb — tried, and withdrawn 2026-10-10.** Three places in a fixed bar at the
  bottom below 641px, with the home-bar inset kept clear. The first real phone session killed it: *"It gets
  hidden behind the browser UI. It is too cramped to the bottom of the content. I do not want it there."*
  That is the standing trouble with `position: fixed` on a phone — Chrome's own chrome occupies the same
  strip, and `env(safe-area-inset-bottom)` cannot help with being underneath the *browser* rather than the
  page. Replaced by **a sticky header at every width**: full-width and opaque, with the centred row inside
  it, and at ≤640px the brand gives way so the three links can spread across the screen at `--tap` tall.
  Installing the app (§5) removes the browser chrome altogether, which is the other half of the answer.
  What was first reported as content hidden behind the bar turned out to be something else — *"I think it
  might have just been really cramped, and not actually hidden. I mistook lack of padding for overlap"* —
  so no density change was made.
- ✔ **A size setting, because one size cannot fit both screens** (asked for 2026-10-10: the text was too big
  on the phone and too small on the 2K display). Four named steps — compact 90% · default 100% · large 115%
  · larger 130% — in the *Look* card beside Paper/Ink and Auto/Light/Dark, written to `localStorage` and so
  **per device**, which is the whole point. It moves the **root font size**, not `--type-scale`: spacing is
  all in rem, but rem is anchored to the root, which `--type-scale` does not touch, so scaling the text
  alone would have grown the words inside padding that stayed put. `--tap`, `--tap-sm` and `--nav-h` moved
  from px to rem so the buttons come along, with `max()` floors so nothing is ever harder to hit than 44px.
  Set before the first paint in `app.html`, as a percentage so the phone's own accessibility size still
  multiplies in rather than being overridden.
- ✔ **Cards come along by themselves.** "Take cards with me" was a button, and a button nobody could find —
  at y=810 in an 844px viewport, behind the bottom bar. It only ever fetched a *bigger* batch than one
  session needs, which is a decision the app can make for itself, so it is gone: after every successful
  load the practice page quietly tops up the batch on the device if it is missing, too small to last or a
  day old. Offline with no batch for the exact scope, it falls back to the widest one there is and says on
  screen that the cards came from wider than this one.
- ✔ **A session is the only thing that takes the screen.** Hiding the chrome used to follow the URL, so the
  screen where a session is *set up* had no navigation at all. It now follows the session itself
  (`src/lib/chrome.svelte.ts`), and a round of matching starts at the top of the screen instead of floating
  in the middle of it.
- ✔ **A session ends with what happened**: asked, right first time, and how many stayed due.
- ✔ **Asking before taking something away** is the app's own dialog, not `window.confirm` — it says what is
  kept as well as what goes, Escape leaves it, focus starts on the safe answer and returns where it came
  from. Three calls replaced: deleting a category, archiving a note, archiving a file, discarding an import.
  The full-size page in an import review is a real modal too, so Escape closes it.
- ✔ **Waiting looks like what is coming** — skeletons in the shape of the content, not the word "Loading…".
- ✔ **Keyboard and screen reader**: a skip link, focus moved to the page after a navigation (but not on the
  first load), a title per route so history and the announcer have something to say, `aria-keyshortcuts` on
  the graded answers, and the shortcuts written on screen where there is a keyboard to use them. A whole
  session can be answered with <kbd>Space</kbd> and <kbd>1</kbd>–<kbd>4</kbd>.
- ✔ **`prefers-reduced-motion` and `prefers-contrast`** are answered; the browser's own chrome follows the
  scheme through `theme-color`.
- ✔ **Verified, not assumed**: six routes × two widths × two schemes in headless chromium — every contrast
  pair at 4.5:1 or better in both schemes (lowest: 4.86), nothing tappable under 36px, no sideways scroll,
  no console errors, and a keyboard-only session driven end to end. Two bugs the screenshots caught: in the
  dark scheme `--sunken` was exactly `--bg`, so the progress track and the piece pool were invisible; and a
  long lesson title pushed its note count onto a second line.

**Looks, third pass — the redesign** ✅ (asked for 2026-10-09)

The second pass was answered with *"It looks the same."* That was fair: asked how far to go, the owner
had chosen "leave the structure alone", so the token work mapped old values onto near-identical new
ones and nothing was redrawn. This pass is the redesign that was actually wanted.

Two directions (**Editorial** and **Bold drill**) were built for real in a throwaway copy of the
frontend, screenshotted side by side from the live data, and shown. The answer was *"I like both …
what I want most is for the main UI to be simple, with lots of padding … some screens are dense or
unnecessarily verbose."* So the brief was never the direction.

- ✔ **Two skins, one layout.** `paper` (cream, Noto Serif, hairlines, indigo) and `ink` (flat, heavy
  sans, 2px rules, cobalt), switchable in Settings beside light/dark and stored per device. Carrying
  two *layouts* was rejected as a permanent cost; carrying two token sets is nearly free.
- ✔ **No cards, in either skin.** A section is a rule, a small uppercase label and air. `.card` keeps
  its name so no screen had to be rewired, but it draws only the rule.
- ✔ **521 words of standing explanation → ~175 on screen.** The load-bearing rules moved behind a `?`
  (`Help.svelte`, a native `<details>`); the rest was deleted because the owner wrote this app and
  does not need to be told how a category path works every time.
- ✔ **Progress split into three** — the gist (`/progress`: how much is known, the streak, the
  heatmap), `/progress/lessons` and `/progress/weak`. It was the densest screen in the app by
  measurement; it is now the emptiest.
- ✔ **Progress rebuilt around words ✅ (2026-10-11)** — and *emptiest* turned out to be the problem:
  below the fold it was blank, and what it did show was the algorithm's view (a heatmap twenty-six
  columns wide for a fortnight of data, and the scheduler's name). It now shows **words**: three
  strips of real ones — *Know well* (recently mastered first), *Troublesome*, *Not met yet*, plus
  *Set aside* when there are any — each tapping through to the whole list at
  `/progress/words/[bucket]`. A row is `prompt answer` and nothing else; **which way round a card is
  asked is which side leads**, so no row says "reverse" and none carries a count. *Going wrong* went
  from six lines a row to two and gained **Set aside**, the first thing that list could ever do
  about a word. `standing()` became the first half of `standing_since()` so "recently" can be
  said; `set-aside` is a pseudo-bucket with its own query, because hiding suspended notes is the
  whole job of `_practisable()` — which is why seven words were unreachable from anywhere in the app.
- ✔ **Progress as a drill-down ✅ (2026-10-12)** — *"no granularity … I specifically wish to have
  per-file or per-category level."* Per-file bars existed, but only at `/progress/lessons`, behind
  the last row, as `mastered/cards`. The user chose: **a drill-down tree** (`/progress` leads with
  the root categories → `/progress/c/[id]` its subcategories and lessons → `/progress/f/[id]` its
  headings, each opening to its figures and *Practise this heading*, and its words by bucket);
  **two numbers, never a merged "learned"** (mastered and known side by side); **count notes, not
  cards** — a word asked both ways is one, at its **weaker** direction (`weakest()`, the sheet dot's
  rule), so the API's `cards` field became `notes`; **no "mastered" badge**; and **rows are bars
  only**, the figures on the screen you tap into. Word lists became note-level too (one row per note,
  front first, `card_key` naming the side holding it back) so a list is as long as its count, and take
  `?file=` / `?category=`. New: `group_mastery()`, `GET /api/progress/files/{id}`. The heatmap moved
  to `/progress/habit`; `/progress/lessons` redirects. Consequence worth knowing: a note asked only
  one way still counts as *not met yet*, and Korean's mastered figure reads 44 of 203 words where it
  used to read 148 of 406 cards. The weak list stays per card — it is about which way round goes wrong.
- ✔ **Seven defects from the 2026-10-11 review ✅** — the weak list ranked on all-time lapses inside a
  thirty-day window (now recent misses only); `canChoose` let a forced *choice* render two options
  where the server wants four; a flush already in flight turned away the answer that arrived during
  it, stranding the last one of a sitting; `pace` counted UTC days while `activity` counted the
  client's; `/practice/answer` resolved the scheduler without the card's category; the recognition
  cap left the FSRS bag's own date behind; and one ungradeable row 422'd a whole sync batch, which
  the outbox would then retry for ever. Each has a test.
- ✔ **The collection audit, surfaced ✅ (2026-10-11)** — `GET /api/collection/audit` and a quiet card
  on the Collection page, naming each finding's kind and what to do about it. `memo audit` was the
  only witness to what the extractor leaves behind, and it is a command nobody remembers to run.
- ✔ **The session** lost its box, its standing instructions and the `new · forward → en` line; the
  answer's language moved into the input's placeholder, where it is needed.
- ✔ Icon, manifest and `theme-color` redrawn and finally agreeing with each other.
- ✔ **Verified** across *four* looks (2 skins × 2 schemes) × 8 routes: every contrast pair ≥ 4.5:1
  (lowest 4.56), nothing tappable under 36px, no sideways scroll, print black-on-white from every
  look, no console errors.
- ⚠ **Two class-collision bugs found, both pre-existing from pass two**: the study sheet's gloss
  column (`<td class="back">`) was being styled by the global back-link rule, so it was an
  `inline-flex` box pulled 8px left and ignoring the table's column widths — *that*, not the column
  width, was why long glosses wrapped into three lines. And `TreeNode`'s `.label` collided with the
  new eyebrow utility. A check for this now lives in the verification notes.
- ⚠ **The print block must stay as specific as the palette blocks.** `:root[data-skin='paper']` lost
  to `:root[data-skin='paper']:not([data-theme='dark'])`, and sheets printed cream-on-ink from a
  light screen until the print selectors were given the same shape.

**Copy and listen — two QOL additions** ✅ (asked for 2026-10-09)

- ✔ **The study text can be selected and copied out of a tap target.** Plain text always could; text
  inside a `<button>` could not, which is exactly where `choice`, `match` and `build` put it. The
  three now ask for `user-select: text` (the numeral and the ✓/✕ ask for `none`, so what you paste is
  the answer alone). A drag that selects **still fires `click`**, so every one of those taps is
  guarded by `selecting()` in `src/lib/selection.ts` — otherwise copying an option would answer the
  card. A `disabled` button keeps its text selectable, so a finished question is safe to copy from.
- ✔ **"Hear it" — one tap, the device's own voice** (`src/lib/speech.svelte.ts`,
  `components/Speak.svelte`). Web Speech API: no backend, no network, no cost, and not gated on a
  secure context, which matters because the phone reaches the laptop over plain http. One speaker per
  card, on the side memo is not written in — the phone has an English voice too, and a speaker beside
  every English answer is noise. It draws nothing at all when the device has no voice for the
  language, which is this laptop's state today: nothing provides `libspeechd.so.2`, so
  `getVoices()` is empty. Installing `speech-dispatcher` + `espeak-ng` would fix that and change no
  code, but espeak's Korean is too flat to learn pronunciation from.
- ⚠ **Never autoplays**, by choice. The owner asked for tap-only.
  ✅ (2026-10-14) **except when a sitting asks for it**: *Read questions aloud* on the practice setup
  screen, off by default and remembered per device, says each question as it comes up, for learning
  how a sentence sounds. Offered only where some question can be said on that device.
- ⚠ **No keyboard shortcut**: the practice page's `keydown` has no target guard and is safe today
  only because its branches require Enter or flip mode, so any letter would fire while typing an
  answer.
- ⚠ **Speaking into the microphone is blocked, not declined.** `getUserMedia` and
  `webkitSpeechRecognition` are secure-context-only and the phone is on `http://<LAN-IP>:8000`, so
  the microphone is unavailable on the only device that matters until the LAN is served over TLS.
  `navigator.clipboard` is blocked for the same reason, which is why copying is selection and not a
  button. Judging pronunciation by transcription would also be dishonest — it tests whether a word
  was recognisable, not whether it was said well, and letting it grade would corrupt the scheduler.

**Bigger type above full HD** ✅ (asked for 2026-10-09)

- ✔ The type scale now hangs off one multiplier, `--type-scale`, and `@media (min-width: 1921px)`
  sets it to `1.125`. Every size grows by the same eighth, so the hierarchy keeps its proportions;
  the space scale and the 820px column deliberately do not move, so a line holds fewer words rather
  than running longer. (This laptop is a 4608×2880 panel at 200%, i.e. 2304 CSS px — comfortably over.)
- ⚠ `font-size` was on `html, body`. Because the tokens are `rem`, sizing the root redefined `rem`
  and the scale applied **twice** (body came out 20.25px instead of 18px). It now sits on `body`
  alone, which also stops the app overriding the reader's own browser font size.

**Keyboard control** ✅ (asked for 2026-10-09)

- ✔ **Every mode, match included** ✅ (decided 2026-10-09, over choice-only): arrows move between
  `choice` options, along `build`'s pool and across `match`'s two columns; `Enter` commits. Match had
  no keyboard path at all before this.
- ✔ **`Enter` is Good on a revealed flip** ✅, so `Enter` means "on you go" in every mode without
  exception. `1`–`4` keep working. The alternative — a flip always costing a deliberate key — was
  rejected as the one hole in that promise.
- ✔ **The focus goes where `Enter` goes** ✅: answering disables the options, which drops the focus,
  so each verdict hands it to Continue and each revealed flip hands it to Good. The ring is on the key
  you are about to press, and a screen reader announces it.
- ✔ The arrows move the **real focus** rather than painting a highlight (`src/lib/roving.ts`), so the
  existing `:focus-visible` ring, the hover styles and assistive tech need no new code at all.
- ✔ Every handler goes through `forPage()` (`src/lib/keys.ts`) first. There are three `svelte:window`
  keydown listeners live at once and not one of them looked at `event.target`, so a bare key typed into
  the answer box was only safe by accident. A **readonly** box is deliberately not excluded: the answer
  field keeps the focus while the verdict is up, and `Enter` must still continue from there.
- Already there and easy to miss: `Enter` on a verdict, `1`–`4` in `choice`, `Space` on a flip,
  `Backspace`/`Enter` in `build`. Not in scope, neither asked for: `Enter` on the start and finish
  screens, and `Escape` to end a session.
- **Status**: driven in headless Chromium against a copy of the real collection — 35 checks, every
  mode answered with nothing but the keyboard, including a whole five-pair match round.

**Mastery by success rate** ✅ (asked for 2026-10-09)

- ✔ **Four buckets** ✅ (decided 2026-10-09): `new` · `learning` · `known` · `mastered`. The top one
  requires writing, which is what was asked for; `known` is "answered right often enough" and keeps the
  distinction between recognising a word and being able to write it.
- ✔ **Credit depends on the mode** ✅, which is what prompted the change — selecting the right pair out
  of five is not the evidence that writing the word is. The weights follow the difficulty order
  **Laufer & Goldstein (2004)** measured for four degrees of knowing a word: *passive recognition* <
  *active recognition* < *passive recall* < *active recall*. Both coordinates are already on every log
  row (`mode`, `direction`), so this needed **no migration**.

  | evidence | mode × direction | points |
  |---|---|---|
  | passive recognition — pick what it means | `choice`/`match` `fwd` | 1 |
  | active recognition — pick the word | `choice`/`match` `rev` | 2 |
  | self-graded recall | `flip`, either way | 2 |
  | passive recall · assisted production | `typed` `fwd`, `build` either way | 3 |
  | active recall — write the word | `typed` `rev` | 4 |

  Supporting: Nation's receptive/productive distinction and Webb (2005, 2008) — receptive practice does
  not reliably yield productive knowledge; Pyc & Rawson (2009) on retrieval effort; Morris, Bransford &
  Franks (1977) on transfer-appropriate processing. The *ordering* is well established; the exchange rate
  between a recognition and a production is a judgement call, which is why the numbers were the owner's.
- ✔ **The gates** ✅ (the "balanced" option of three): `known` at 6 points, 4 counted reviews and 80% of
  the last 8; `mastered` at 10 points of which **3 must come from `typed`**. `build` earns its 3 points
  towards the total and never towards the writing requirement — tiles are production with the answer cut
  up in front of you. Writing is judged per card in its own direction, and a note still shows its weaker
  direction, so a note is mastered only when both sides have been written.
- ✔ **`almost` is ignored entirely** ✅: no points, and not one of the reviews the accuracy window looks
  at. Since `almost` maps to `HARD`, the whole rule reads off `final_grade` — ≥3 earns, 1 counts against,
  2 is neither. This settles a contradiction already in `progress.py`, which called grade `== 1` wrong in
  one place and grade `>= 3` correct in another, leaving `HARD` in limbo. It is now limbo on purpose.
- ✔ Points are kept for good; the **accuracy window is what regresses a card**, so a word you have
  started getting wrong leaves `known` however much credit it earned. That split is the rule in two
  sentences, which is what makes it explainable in the `?` panel.
- ✔ **And it cannot be done in one sitting** ✅ (asked for 2026-10-11, alongside the mark: *"a word cannot
  be mastered in a day … until it's consistent and separated by 8 hours"*). The points that earn
  `mastered` must span at least `MASTERY_SPREAD` = 8 hours. Everything else above is reachable in an
  evening on one lesson, and a word you can still produce an hour later is not a word you have kept.
  Eight hours rather than a calendar day, because morning-and-evening is two real retrievals across a
  working memory emptied in between, whereas waiting for midnight would make the same two answers count
  differently depending on what time the first one was given. Only `mastered` is gated — a crammed word
  still reaches `known`. `standing()` therefore reads `(mode, direction, grade, ts)`, which its own
  docstring had already anticipated ("the log is kept raw … the rule can change"), and the spread is
  measured over the successes that *earned* something, so an `almost` eight hours ago proves nothing.
  **Measured against the real log before shipping: not one card moved** — all 15 mastered cards had
  already earned their points over more than eight hours, so the rule only constrains what comes next.
  (At 30 days, for comparison, all 15 would have moved, so the knob does bite.)
- ⚠ **Mastery stopped depending on the scheduler**, necessarily — the rule touches no interval. Switching
  SM-2 ↔ FSRS used to reset the bars to `new`; it no longer does, and the test that asserted the old
  behaviour now asserts the new one.
- The bucket colours were re-spaced rather than extended: four steps need four values, so `--mastered`
  takes the strong end of the family and `--known` moves in one notch, in all seven token blocks.
- **Status**: the rule recomputed against a copy of the real 404 reviews says 194 `new`, 226 `learning`,
  0 `known`, 0 `mastered` — nothing is mastered because **not one of those 404 reviews was typed**. The
  suggester only offers typing after a card has been held a day (`modes.py: TYPED_AFTER_DAYS = 1.0`) and
  120 cards crossed that line in the session of 2026-10-09, so writing starts appearing now.

**Serving it, and practising with no signal** ✅ (asked for 2026-10-10)

> "Lets plan how will we serve this. Or can it run static?" … "I just want the static export to work on
> the phone now. I will use phone and then sync progress again."

- **It cannot run static**, and the reason is the data, not the rendering: the bundle already is static,
  but every screen fetches, and practice needs the server to pick what is due, build distractors and
  advance the scheduler. A static host serves an empty shell.
- **The gate nobody expected**: offline practice needs a service worker, and a service worker is refused
  outside a secure context. `http://evoend.local:8000` is not one, and a `file://` copy is worse — Chrome
  gives it an opaque origin with no IndexedDB, so there would be nowhere to keep the answers. Hence
  Tailscale first, which the user chose over ZeroTier once it was clear that ZeroTier (like Netbird,
  Nebula and plain WireGuard) routes but issues no certificate.
- **What made it cheap**: the checker already runs in the client, `AnswerIn.at` already existed, and
  `replay()` already rebuilt a card's state from the log alone — so **SM-2 and FSRS did not have to be
  ported to the browser**. The phone collects evidence; the laptop still schedules.
- **The shape**: a service worker caching the app and never `/api/`; a batch of cards in IndexedDB, topped
  up by itself after every load (it began as an explicit *Take cards with me* button — withdrawn the next
  day, §6); and an outbox every answer goes through, online or not, so the offline path is not a special
  case that only runs when it is too late to find it broken.
- **Syncing is both**, the user's choice: the outbox flushes to `POST /api/practice/answers` whenever the
  laptop is reachable, and *Settings → Save to a file* feeds `memo import-answers`. Neither can
  double-count, because `review_log.client_id` is unique per profile — the one migration this needed
  (`c4e8f1a7b093`).
- Ingested rows are **appended, then replayed**: an answer from last Tuesday lands where it belongs
  rather than nudging today's state. They keep `state_before`/`state_after` null, because they were
  never scheduled live and inventing those would be writing a history that did not happen. Nothing in
  the codebase reads them.
- **It installs on the home screen** ✅ (asked for 2026-10-10: *"Can we make it work as a PWA or
  something?"*). More of it was already there than expected — manifest, a service worker registered by
  SvelteKit's own snippet, IndexedDB — so what was missing was the install itself: the only icon was a
  268-byte SVG, declared `any` *and* `maskable` with no safe zone, so iOS would have synthesised a
  screenshot. Added: 192/512 PNGs and a 180px `apple-touch-icon` (opaque — iOS composites nothing behind
  it), a maskable 512 redrawn at 60% inside its own safe zone, `id`/`scope`/`lang`/`dir` on the manifest,
  and the `apple-mobile-web-app-*` metas. Generated with `rsvg-convert` from the SVG, so the icons stay
  one source. **Online first stays online first** — the fetch handler is untouched; the only change inside
  the worker is that the app shell must cache while the icons and fonts are best effort, because `addAll`
  is all-or-nothing and one failed request on a weak connection used to mean no service worker at all.
  Two server-side consequences: `.webmanifest` is pinned to `application/manifest+json` rather than trusting
  the interpreter's mime table, and a missing *file* now 404s instead of being answered with the page and a
  200, which is what made a broken icon look like it had loaded.
- **Installed, and then actually opened with the laptop off** (2026-10-10, reported from the phone:
  *"I think the PWA installs, but does not work offline"*). The worker was innocent — it installed,
  activated and cached 122 entries, and the app opened. What was missing was **a way in**: every route
  to a session is a link in the category tree, the tree is `/api/` only, and `/api/` is deliberately
  never cached, so a cold start showed an empty collection, the line "Can't reach the laptop", and not
  one practice link — with 66 cards sitting in IndexedDB. The reason the harness missed it is worth
  keeping: it navigated to `/practice/all` **by URL**, which is the one thing a phone cannot do.
  Fixed by keeping **the last collection this device was shown** in a third IndexedDB store
  (`offline/collection.ts`, schema version 2), so the home screen looks and works as it always does;
  what genuinely needs the laptop — adding pages, the ⋯ panel, a new category, export, and opening a
  file as a sheet — is disabled with a reason rather than dead. And since a phone that had only ever
  seen the home screen had nothing on it at all, cards are now taken along **when the app opens**, not
  only when a practice screen loads, with *Settings → Cards on this device* to check and to ask for
  more before leaving.
- **"It just takes a lot of time to load"** (2026-10-10, the next report from the phone, and the
  sharpest lesson of the three). A laptop that is **asleep does not refuse a connection** — the
  packets go nowhere, nothing comes back, and `fetch` waits for the operating system to give up,
  which is over two minutes. Network-first with no deadline therefore fails in exactly the situation
  the cache exists for, and `Page.navigate` in the harness never returned at all. Switching the
  machine off, or a phone in airplane mode, fails in milliseconds — **which is why neither this nor
  any earlier offline test caught it.** A deadline in three places fixed it:
  - the service worker gives the network `PATIENCE` (1.5s) on a navigation or an asset and serves the
    cache if it does not answer; a failure resolves rather than throws, so a genuinely offline phone
    is still instant;
  - `client.ts` puts a 2.5s `AbortSignal.timeout` on reads — long jobs (imports, export) keep none —
    plus a 10-second breaker, because a screen with four requests on it otherwise pays four timeouts
    one after another;
  - and the two things the app was *waiting* for it already had: the sign-in gate
    (`+layout.svelte:70` renders nothing until `auth.status` exists) now starts from the remembered
    status, and the collection renders from `collection.ts` before the network is asked at all.

  Measured against a blackholed host, which is what a sleeping laptop looks like: **never returned
  (>120s) → 4.2s with the worker's deadline alone → 1.8s** once the gate stopped waiting. With the
  laptop awake: 166ms for the collection, 276ms for a practice screen — the online path is untouched,
  which is the point of a deadline rather than cache-first.
- A trap that cost an hour and will recur: **Svelte 5 state is a `Proxy`, and IndexedDB's structured
  clone refuses one** with `DataCloneError`. `db.ts` answers a failed write with `null` by design, so
  the store simply stayed empty with nothing to say why. Anything handed to `put()` from reactive state
  must be plain first — `collection.ts` does the round-trip at the boundary so no caller has to
  remember. (The batch never hit this: it stores the API's own response object.)
- Smaller things it forced: `client_id()` must read `X-Forwarded-For` (only from loopback) or every
  device behind `tailscale serve` shares one rate-limit bucket; a failed `fetch` must not reach the user
  as "Failed to fetch"; and `auth` must remember the last good status, or being out of range looks
  exactly like being signed out and locks the whole app.
- **Backups**, finally: `memo backup` uses `VACUUM INTO` (WAL-safe, where `cp` is not) into
  `~/backups/memo/`, nightly by a user timer.
- ⚠ **A batch is a photograph, not a feed**: after a long stretch offline the `suggest` on a card is
  behind what it now deserves. Grading and replay are unaffected; only the choice of exercise is stale.

**Phase 5 — beyond Korean vocab**
- Equations/results (`directional` + KaTeX, maybe SymPy equivalence), grammar content
- Audio: listening is done (above); speaking needs TLS, which Tailscale now provides — untried
- ~~Offline practice (PWA cache + queued review log)~~ ✅ done 2026-10-10, above; Android (Capacitor wrap or native client) still open
- **Done when**: a maths deck and an offline session on the phone both work.

## 7. Open questions ❓

None outstanding — everything from earlier revisions is decided (see §1 and the ✅ marks throughout).

Settled in this revision: SvelteKit · SM-2 + FSRS switchable · localhost now, Docker later · flat `notes[] + group ref` ·
LLM proposes the importer with user override · duplicates flagged with keep/skip/merge · distractor scope is a setting ·
adaptive modes follow scheduler state · practice logic is language-neutral (§3.7).

Deliberately deferred to their phase: auto-export and git automation, offline practice, Android packaging,
maths equivalence checking, multi-device sync.

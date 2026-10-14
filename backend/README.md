# memo — backend

The API, database, import pipeline, schedulers and a command line — phases 0 to 4
of [`../PLAN.md`](../PLAN.md). The same process serves the built frontend.

Start at the [root README](../README.md): using the app is in [`../docs/user-guide.md`](../docs/user-guide.md),
the data format in [`../docs/format.md`](../docs/format.md), and the rules for changing the code in
[`../docs/development.md`](../docs/development.md). Below the command reference, each section is one
decision and the reasoning behind it.

**Contents:** [Run the app](#run-the-app) · [Setup](#setup) · [What can be run](#what-can-be-run) · [Checking the phase-0 acceptance criterion](#checking-the-phase-0-acceptance-criterion) · [Layout](#layout) · [Tests](#tests) · [What counts as mastered](#what-counts-as-mastered) · [The words behind the buckets](#the-words-behind-the-buckets) · [Answers earned offline](#answers-earned-offline) · [Practising a lesson you chose](#practising-a-lesson-you-chose) · [How often a word comes up](#how-often-a-word-comes-up) · [Finding a word](#finding-a-word) · [A list for a test](#a-list-for-a-test) · [Words beside a word](#words-beside-a-word) · [A gloss read backwards](#a-gloss-read-backwards) · [What keeps a card on the weak list](#what-keeps-a-card-on-the-weak-list) · [How long a sitting will take](#how-long-a-sitting-will-take)

## Run the app

```sh
uv sync                                    # then MEMO_LLM_API_KEY=… in .env
uv run memo hash-password                  # put the output in MEMO_AUTH_PASSWORD_HASH
(cd ../frontend && npm install && npm run build)
uv run memo serve                          # http://127.0.0.1:8000
uv run memo serve --host 0.0.0.0           # reachable on the LAN, but plain http: no offline, no install
```

Or `../serve.sh` from the project root, which does the migration, builds the frontend when
there is none, and takes `--phone` for the `0.0.0.0` bind (`--help` lists the rest).

With no `MEMO_AUTH_PASSWORD_HASH` the password gate is open — fine on localhost only.
For frontend work, `npm run dev` in `../frontend` proxies `/api` to `memo serve`.

## Setup

```sh
uv sync
uv run alembic upgrade head
```

Settings go in `.env` here, each with the `MEMO_` prefix; every one of them is in
`src/memo/config.py`. Reading photos needs at least `MEMO_LLM_API_KEY` (and
`MEMO_LLM_BASE_URL` and `MEMO_LLM_MODEL` for a provider other than OpenAI).

## What can be run

```sh
uv run memo probe-provider --image ../data/korean/raw/vocab1.jpg
```
Asks the configured provider what it supports and prints the tier to put in
`.env` (`json_schema` / `json_object` / `text`, PLAN 3.6).

```sh
uv run memo import ../data/korean/raw/vocab1.jpg \
    --importer korean-textbook-vocab --first-page 6 \
    -o /tmp/draft.json --category korean/book1/02-introduction
```
Reads the page and writes one draft data file. Leave `--importer` out and the
general reader does it, with the prompt from `docs/llm-prompt.md` (PLAN 4.1), unless
local importers exist, when a cheap router call proposes one. `--instructions` is
what you would tell the model in a chat. A PDF can be given too, read as its text or,
with `--pdf-mode images`, as pictures of its pages. `--category` also loads it into the collection.
`korean-textbook-vocab` is a local importer: copy
`examples/importers/korean-textbook-vocab.toml` into `importers.local/` to have it.

```sh
uv run memo store <file.json> --category korean/book1   # a ready-made data file
uv run memo export df_01J…  -o out.json                 # back out again
uv run memo schema -o schema                            # both JSON Schemas
uv run memo importers                                   # what can read a page, and what failed to load
uv run memo openapi                                     # API description → frontend types
```

```sh
uv run memo audit                                        # read-only: what is wrong with the data
uv run memo patch patches/2026-10-11-glosses.json        # dry run; --apply writes it
```
`audit` looks for the kinds of wonkiness an import leaves — see *A gloss read
backwards* below. `patch` is the **only** way to change a batch of notes in
place, and the only way at all once a collection has been practised.

```sh
uv run memo import-answers ~/Downloads/memo-answers-2026-10-10.json
uv run memo backup --to ~/backups/memo --keep 14
```
Answers earned on the phone with no network, and a copy of the only database
there is. See [`../docs/serving.md`](../docs/serving.md) for both, and for how
the phone reaches the laptop at all.

## Checking the phase-0 acceptance criterion

`tests/fixtures/vocab1.datafile.json` is the hand-verified data file for
`data/korean/raw/vocab1.jpg` (textbook page 6, PLAN 2). `data/` is not in git, being one person's
collection and a publisher's pages, so the tests upload `tests/fixtures/sample-page.jpg` instead.
Compare a real import against it:

```sh
uv run memo import ../data/korean/raw/vocab1.jpg \
    --importer korean-textbook-vocab --first-page 6 -o /tmp/vocab1.json
diff <(jq 'del(.id, .source.import) | .notes |= map(del(.id))' tests/fixtures/vocab1.datafile.json) \
     <(jq 'del(.id, .source.import) | .notes |= map(del(.id))' /tmp/vocab1.json)
```

IDs and provenance differ by design; anything else is a real difference.
The same comparison runs offline in `tests/test_import_pipeline.py` against a
recorded extraction, so a regression fails the suite without spending a call.

## Layout

```
src/memo/models/      data file (lenient) · extraction (strict) · adapter  — PLAN 3
src/memo/dataio/      read/write the interchange format                     — PLAN 5
src/memo/db/          SQLAlchemy tables; SQLite is the truth                 — PLAN 5
src/memo/collection/  category tree, storing and exporting data files
                      `audit.py` asks what is wrong with the whole tree; `patch.py` fixes it in place
src/memo/llm/         OpenAI-compatible client, capability probe, repair loop — PLAN 3.6
src/memo/importers/   the general reader (`prompts/general.md`), local importers, the router — PLAN 4, 4.1
src/memo/importpipe/  run a job: pages in, one draft data file out; import jobs — PLAN 4
src/memo/scheduling/  SM-2 and FSRS behind one interface                     — PLAN 5
src/memo/practice/    outcome → grade, recognition cap, due queue, review log,
                      mode per card and multiple-choice distractors — PLAN 3.5
                      `ingest_answers()` takes in answers earned offline, then replays
                      `answered_early()` is why practising ahead costs a card nothing
                      `priority.py` is what a word's mark is worth once you take account of knowing it
src/memo/overview/    what the log already says: buckets, weak cards, activity — PLAN 6, phase 4
                      `progress.standing()` is the mastery rule, read off the review log alone
src/memo/api/         FastAPI routes, password gate                           — PLAN 5
var/                  memo.db · raw/ uploads · export/                       — PLAN 5
examples/importers/   a local importer spec to copy (the Korean textbook)    — PLAN 4.1
importers.local/      your own importers; gitignored                         — PLAN 4.1
```

## Tests

```sh
uv run pytest
uv run ruff check src tests
```

No test touches the network: `tests/fakes.py` stands in for the provider.

## What counts as mastered

Four buckets — `new`, `learning`, `known`, `mastered` — and the whole rule is
`overview/progress.py:standing()`, which reads a card's own review rows and nothing else. No
interval, no scheduler state: what you know about a word does not depend on the algorithm that
scheduled it, so switching SM-2 ↔ FSRS no longer changes the bars.

Each clean answer earns points by how hard it was to produce, following the difficulty order
Laufer & Goldstein (2004) measured — picking what a word means (1), picking the word itself or
judging a flip (2), writing what it means or building it from pieces (3), writing the word from
memory (4). Both coordinates are already on the log row (`mode`, `direction`), which is why this
needed no migration. `known` wants 6 points, `mastered` wants 10 of which 3 must come from
`typed`; `build` is production with the answer cut up in front of you, so it counts towards the
total and never towards the writing requirement.

A grade of `HARD` — which is what an `almost` becomes — is neither a success nor a miss: it earns
nothing and is left out of the accuracy window entirely. That window (80% of the last 8 counted
answers, over at least 4) is what takes a card back down, since points never decay. A word you
have started getting wrong leaves `known` however much credit it once earned.

**Mastered also needs time.** Everything above can be satisfied in one evening on one lesson, and a
word you can still produce an hour later is not a word you have kept — so the successes that earned
the points must span `MASTERY_SPREAD` (8 hours). Only `mastered` is gated; a crammed word still
reaches `known`. Eight hours rather than a calendar day, because morning-and-evening is two real
retrievals across a working memory emptied in between, whereas waiting for midnight would make the
same two answers count differently depending on what time the first was given. The spread is measured
over the answers that *earned* something, so an `almost` eight hours ago proves nothing. `standing()`
therefore takes `(mode, direction, final_grade, ts)`, and `ts` is when the answer was **given** — a
session on a train is measured where it happened, not when it synced.

## The words behind the buckets

`overview.progress.words(session, profile, bucket)` returns the cards in one bucket as a list of
words — `prompt` and `answer` already the right way round for the card's direction, so a row says
which way it is asked by which side leads rather than by a label. `GET /api/progress/words` serves
it, and `/progress` carries the first six of `mastered` and `new` inline so the page shows words the
moment it loads instead of four numbers.

`known` and `mastered` come back most recently reached first. That needs to know *when* a card got
where it is, so `standing()` is now the first half of `standing_since()`, which applies the same
rule after every review rather than only at the end and remembers where the current run began. The
totals it reads are running ones, so this costs nothing; `standing()` is unchanged, and so are its
tests.

`set-aside` is the odd one: not a standing at all, but a word deliberately left out of practice. It
needs its own query, because hiding suspended notes is the entire job of `_practisable()` — which is
why, before this, a word you set aside could not be found again except by remembering which lesson
it came from. *Going wrong* can now set one aside (`PATCH /notes/{id}` with `suspended`), and
`/progress/words/set-aside` is the way back.

## Answers earned offline

`review_log` is append-only and `CardState` is only a cache of it, which is what makes a phone
with no signal workable: it grades with the same checker the browser always uses, keeps the rows,
and hands them over later. `POST /api/practice/answers` and `memo import-answers` are the same
code (`practice/service.py:ingest_answers`), so the two ways in cannot drift apart.

A row brings its own `client_id` and its own `at`. The id is unique per profile
(`c4e8f1a7b093`), so the same batch offered twice — uploaded *and* carried over as a file —
lands once. The timestamp is kept over the arrival time, and because that means rows can arrive
older than rows already here, each touched card is **replayed** from its whole log rather than
nudged forward.

Ingested rows leave `state_before` and `state_after` null. They were never scheduled live, and
filling them in would mean writing a history that did not happen; nothing reads them.

## Practising a lesson you chose

`due_queue()` answers with a `Queue`, not a list: `cards` plus `due_count`, `new_count`,
`ahead_count`, `later_count` and `next_due`. The counts exist because an empty list cannot say
*why* it is empty, and the screen was left to guess — it used to claim "every card here is
scheduled for later" for an empty file and an all-suspended one alike.

- `limit=None` (the default) means the whole pile, due cards included. With a size — which is what the
  start screen's four steps send — `NEW_SHARE` (a quarter) of it is held for cards not met yet, so a
  backlog cannot own every sitting and leave the lesson it came from standing still; whichever side is
  short, the other fills the room (`_shares`). Without that share, 185 due cards means never opening a
  new lesson again.
- `new_limit=None` (the default) means **every** unseen card in scope. With a size it is a *ceiling* on
  the share above rather than a target. How much to take on in one sitting is the user's, not the
  scheduler's.
- `ahead=True` (the default) fills a session of `ahead_to` (20) from the **soonest-scheduled** cards
  once the due and new ones run out, flagged `early`. A scope somebody chose by hand is never
  answered with "come back tomorrow". Bounded by `limit` when there is one: bringing cards forward
  rescues an empty scope, it does not overrule how much was asked for.
- `schedule_answer()` then makes that free: with more than `EARLY_FLOOR` (a day) still to run, a
  non-failing answer is logged and counts for mastery but **does not reschedule the card** — it
  keeps its due date, interval and the scheduler's own `data`, gaining only `reps` and
  `last_review`. Without it, FSRS would damp the stability gain for the high retrievability and
  SM-2 would restart the same interval from today, both of which cost the user interval they had
  earned. A failure is exempt: a card you got wrong has to come back.
- The rule is a pure function of `(state, now)`, which is what lets `replay()` reach it from the log
  alone — including for a row that arrives days later from a phone.

## How often a word comes up

`note.priority` is `low`, `high`, `crucial`, or null for the ordinary middle — one mark per **word**,
so it covers both directions. What it is worth is damped by how well each card is already known,
which is the whole feature: twenty words marked before a test stop dominating once they are actually
learned, and nobody has to go back and unmark them.

| `push` | new | learning | known | mastered |
|---|---|---|---|---|
| `crucial` | 3 | 3 | 2 | 1 |
| `high` | 2 | 2 | 1 | 0 |
| `low` | -1 | -1 | -1 | -1 |

`3` is ahead of everything and asked twice; `2` is asked first **and** asked a second time in the
sitting; `1` is asked first; `-1` is asked last. `crucial` damps one step later than `high` and never
all the way, because those are the words that must not be lost. `low` is not damped — damping
withdraws a boost a word no longer needs, and has no business overruling "I care about this one
less".

**A mark is for ever and everywhere, which is why it is the wrong tool for a test.** Using it for one
leaves sediment: 119 of this collection's 210 words ended up marked `high` or `crucial`, and a boost
covering 57% of a collection boosts nothing. [Lists](#a-list-for-a-test) are the dated half of the
same idea.

Nothing is stored and nothing expires. The bucket comes from `standing()`, re-read from the
append-only log every time, so a word that starts going wrong is demoted by the accuracy window and
gets its push back by itself. That is also why `practice` imports `overview.progress` and not the
other way round. `standings()` is **not called at all** unless something in scope is marked.

The card carries `priority` (the mark *as it stands*, after damping — a mastered word reads `normal`,
because a badge claiming a push it has lost would be describing the setting rather than the session)
and `twice`. Ordering lands in three places in `due_queue()`: the due sort key ahead of the overdue
day, the new sort key ahead of page order (where the mark *selects* rather than orders, under a cap
or in the 60-card offline batch), and `_space_siblings`, which would otherwise quietly undo both.
Bringing cards forward is still soonest-due-first, and distractors never see a mark.

## Finding a word

`GET /api/notes/search?q=` over `collection/search.py`. Until it existed the only way to a note was
Collection → category → file → read a fifty-six-row grid, because `GET /files/{id}/notes` was the
whole note-reading API — which is why marking twenty words for a test meant hand-writing a patch
file full of ids no screen ever shows.

A **scan**, for the reason `find_duplicates` already gives for scanning: the collection is one
person's, and `normalise()` has no SQL equivalent. Two hundred notes cost nothing and an index would
be a second thing to keep true.

It searches both printed sides, every spelling in `accept`, the free-text `note`, the heading's key
and labels, and the lesson's title — so 미국 is found by typing "america", and 누가 by typing its own
footnote. Ranking is **tier, then exactness, then side**: the word itself and its gloss first, then a
spelling it merely accepts, then something written *about* it, and a file title last however exactly
it matches (it would otherwise drag in all thirty-two of its notes).

**It finds suspended words on purpose.** Hiding them is the entire job of `_practisable()`, and that
is exactly why a word you set aside could not be found; a search that repeated the omission would be
no use at the one moment you need it. `aside=`, `mark=` and `standing=` filter instead, and a
`standing` filter takes a note at its *weaker* direction.

A hit is **note-shaped**, not card-shaped — a card is one way round and what you searched for was
the word — and carries both directions' standings, which is the only part of it that comes from the
review log.

## A list for a test

Two tables (`word_list`, `word_list_note`) and `collection/lists.py`. A list is a **selection, not a
place**: notes stay in the lesson they were extracted from, keep their own marks and keep their
history. Nothing is moved, and nothing could be — `NOTE_FIELDS` has no `data_file_id`, so no API can
move a note between files.

`focus_until` is the half that expires. While it is ahead the list's words lead a sitting; once it
passes they stop, with nothing to remember to undo. **The list outlives its focus**, because what was
on a test is worth keeping and worth drilling again.

| | what it does |
|---|---|
| `GET /practice/queue?list_id=` | a **drill**: every word on the list, due or not |
| a focus, with no `list_id` | the list leads up to `FOCUS_SHARE` of an ordinary sitting |

**Why a list cannot break the scheduler.** Priority and scope are read-time only: `replay()` reads
`final_grade`, `mode`, `ts` and `overridden` and nothing else, and neither `card_state` nor
`review_log` has a priority, scope, file, category or list column. The mark is not in the history, so
a thing that reorders a queue cannot corrupt a card's state. A list is also not a *category*, which
is the shape that genuinely could: `resolve_scheduler_name()` lets a category override the scheduler,
and `card_state` is keyed `(profile_id, card_key, scheduler)`, so a test category resolving a
different scheduler would read an empty row and every word would look new.

**`FOCUS_PUSH` is `1`, not `2`.** `TWICE_AT = 2` means a push of two or more asks the card twice, so
twenty focused words would be forty slots — a whole `normal` sitting. A list does not need to buy its
place that way: it is already guaranteed a share. `push()` takes **the better** of a word's mark and
its focus, so the two compose — a `crucial` word on a test list keeps its second ask — and nothing is
ever written to `note.priority`. At `mastered` the focus is worth `0`, because a test needs the words
you have not got.

**`FOCUS_SHARE = 0.5` is load-bearing, not a nicety.** An unmarked focused word pushes 1 and a word
marked `high` pushes 2, so with no share held back the words marked before some earlier test would
still go first and the list would never get a look in. The other half keeps the rest of the
collection alive during the week before an exam, because a backlog you have stopped touching is what
makes a collection feel lost.

**A focus brings its words forward**, not only the ones already due — a test on Friday is not
something the schedule knows about. They are marked `early`, which is not merely a label:
`schedule_answer` counts an answer given more than `EARLY_FLOOR` ahead **without rescheduling the
card**, so drilling a word you already know keeps the interval it earned. Cramming therefore cannot
inflate intervals, and the protection is keyed off the card's own `due` rather than off any flag.

A card pushed by a focus carries the list's **name** (`QueueCardOut.focus`), not a mark. A chip
reading `high` on an unmarked word would be describing the session and lying about the setting, which
is the rule `effective()` already keeps; and the name is the more useful thing to read anyway. The
name is dropped once the focus has damped to nothing, for the same reason.

## Words beside a word

`GET /api/notes/{id}/related` over `collection/related.py`, built on `audit.py`'s matching down to
`bare()`, so "nearly the same gloss" means here exactly what it means in a report. The difference is
purpose: an audit says what is broken, this says what is nearby.

| `how` | what it means |
|---|---|
| `same-meaning` | the same gloss, folded |
| `near-meaning` | the same gloss once a trailing `(…)` is dropped |
| `same-heading` | printed under one heading in the book |

Each pair also reports `accepts` and `accepted_by`, so the panel can offer to fix the audit's
*one-sided* finding at the point where you would act on it rather than from a card on the home page.

**There are no antonyms and cannot be.** Nothing in a note records that one word is the opposite of
another, and inventing the relation would mean asking a model about Korean and presenting the answer
as the collection's own — which the import prompts refuse to do on purpose. `same-heading` stands in
for it, because a textbook prints 위 beside 밑 for exactly that reason.

The HTTP audit also stopped throwing away what it was already computing: `AuditOut` now carries
`near` and `resolved`. They do not bear on `clean` — a screen should not interrupt for a hint — but
`near` is the same signal as "what else do I know that means this".

## A gloss read backwards

A note's back is the answer in the `fwd` direction and the **prompt** in `rev`. The import had not reckoned with
that: asked what 그게 means, the model answers "that" — exactly as it does for 그것 and 그건 — so the reverse direction
ended up asking one question with three right answers. It is not a hard card, it is an unanswerable one, and
`choice` made it worse, since `distractors_for` banned a candidate equal to the *answer* but never compared
**prompts**. `Candidate` now carries its prompt for that one purpose.

`memo audit` is the check, read-only, and its findings are four:

| | |
|---|---|
| same gloss, different word | the unanswerable prompt. Skipped when the notes accept each other's fronts, which is reported as *shared on purpose* so a deliberate pair does not make the report go quiet |
| the same note twice | same word *and* gloss, with the answer count per copy — which is the "which copy do I keep" decision |
| cross-acceptance only one way | 영 took 공 as an answer; 공 did not take 영, so one of the two directions still failed |
| nearly the same gloss | identical once a trailing `(…)` is dropped. A hint, not a finding: "that" and "that (over there)" *are* two answerable questions |

Nothing suspended or archived is considered — practice never asks it, so it cannot be ambiguous.

`GET /api/collection/audit` is the same check over HTTP, carrying the three findings `clean` is
defined from (the hints are the CLI's). The Collection page asks for it after the tree and shows a
quiet card only when something is wrong, because a command nobody remembers to run is not a check:
the extractor goes on producing these as lessons are added, and this is what notices.

`memo patch` applies a reviewed file of `{id, expect, set}` through `update_note`, the same call the grid editor
makes. Editing a gloss is safe because `card_key` is `note:direction` with no text in it, so no card, schedule or
log row can move; **the command proves that rather than promising it**, by comparing the card and review-log
counts across the write and aborting if either moved. It is a dry run until `--apply`, it refuses the whole file
if any note is missing or holds something other than what `expect` says, and a field already holding its target is
settled rather than a conflict, so the same file can be run twice.

The thing it replaces does not work: editing the exported `data/korean/*.json` and re-importing is not an edit.
`store_datafile` only inserts, and `importers/files.py` blanks every id on the way in — deliberately, since
progress belongs to the collection a note is in (PLAN 3.4) — so a round trip returns new notes with no history.
The export is a snapshot written *from* the database, so after a patch, run `memo export-tree` to bring the files
back in step.

## What keeps a card on the weak list

Recent misses, and nothing else. `weak_cards` used to add the card's all-time `lapses` to the score,
which meant a word forgotten once last season sat on the list for good however well it went
afterwards — the `window_days` control was only half honoured. Windowing the lapse instead was not
on offer: spotting one in the log needs `state_before`, and that is null on every row handed back
from a phone (549 of 1189 on the real collection). So the lapse count is still reported as a fact
and no longer decides anything.

## How long a sitting will take

`QueueOut.seconds_per_card` comes from `overview.progress.pace`, which reads this profile's own log and
nothing else: the median of the last 200 timed answers, times how many answers one card takes within a
day. The second factor is the one that is easy to forget — the in-session loop asks a missed card again
until it is right twice, so a card costs about twice an answer (8.7 s × 1.96 ≈ 17 s on the real log).

It is `None` below 20 timed answers, because a median of four is a mood, and the screen then falls back
to a stated assumption rather than showing a figure it cannot stand behind. The repeat ratio is clamped
to 1–3 for the same reason: a sitting of six answers must not get to claim one.

This is also why a `match` pair records a duration now. It used to send none at all, which left 379 of
1053 rows untimed — a third of the log invisible to the one statistic read off it.

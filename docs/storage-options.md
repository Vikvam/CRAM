# Storage options (open question 1)

Three things need a home, and they have **different** requirements:

| | content (data files) | progress (review log + card state) | raw uploads (photos, PDFs) |
|---|---|---|---|
| size | tiny (KB) | small, grows steadily | large (≈1 MB per photo) |
| written by | import + manual edits, rarely | every single answer, constantly | once, on upload |
| value if lost | high — re-parsing costs LLM calls | medium — schedule resets | low — can re-photograph |
| nice to diff/read? | yes | no | no |
| concurrent writers | rare | likely (two profiles practising) | no |

Conclusion baked into every option below: **don't treat them the same**.

---

## A. Data files in the git repo + SQLite progress

```
repo/  data/korean/…/2-1-vocabulary.json     ← committed
       data/korean/raw/vocab1.jpg            ← committed (or LFS/ignored)
       var/progress.db                       ← ignored
```

- **+** Simplest to grasp; content versioned with real diffs; PLAN/code/data in one place; backup = push.
- **+** Editing a data file by hand or by LLM is trivial.
- **−** Photos bloat the repo (100 pages ≈ 100 MB, forever, unless ignored or in LFS).
- **−** Content and code releases are coupled: adding vocabulary makes a code commit. Deploying = the server writes into its own working copy (surprising, and merge conflicts become an app concern).
- **−** Server can't be redeployed from a clean checkout without losing data written since.

## B. Separate `DATA_DIR` outside the repo (optionally its own git repo) + SQLite progress

```
DATA_DIR/korean/…/2-1-vocabulary.json        ← optionally git, auto-commit on write
DATA_DIR/korean/raw/vocab1.jpg
DATA_DIR/var/progress.db
```

- **+** Same file benefits as A (readable, diffable, LLM-friendly) without polluting the code repo.
- **+** One directory to back up or sync; can be a git repo the app auto-commits to, giving history and undo for free.
- **+** Code deploys and content are independent; a volume in Docker.
- **−** Two places to manage (code repo + data dir); slightly more config.
- **−** Still needs care: atomic writes (write temp + rename), an in-memory ID index rebuilt at startup, a lock for concurrent edits.

## C. Everything in files (progress as per-profile JSON too)

- **+** No database; whole state copyable; in principle practice could work without a server later.
- **−** The review log is append-heavy and concurrent — the worst fit for JSON files; every answer rewrites a file, and two profiles can clobber each other.
- **−** Queries the learn phase needs ("weakest 20 cards in this subtree", heatmaps) mean loading everything into memory.
- **−** "Server optional" isn't actually achieved: import, password and multi-device already need the server.

## D. SQLite as the truth, files only as import/export

- **+** Best for concurrency, queries, and the stats views; one file to back up.
- **+** No atomic-write/index machinery to write.
- **−** Loses the property you asked for: the tree of data files *is* the organisation, hand-editable and LLM-friendly.
- **−** Export/import round-trips become a feature to maintain instead of a side effect.

---

## Decision ✅ — D (SQLite is the truth), export stays manual

Chosen 2026-09-18 after the CRUD UI made hand-editing unnecessary.

**Why D over B**, given a CRUD exists:

1. **B needs a database anyway.** The learn phase queries the whole collection ("weakest 20 in this subtree", mastery per
   category, heatmaps), so B = files as truth **+** an index table that must be rebuilt at startup, updated on every write
   and repaired after hand edits. Two stores, one of them a cache — the main source of bugs in B, and its only purpose was
   hand-editability.
2. **Import staging** (multi-page job, per-page extraction, partial review, drafts) is a table; in B it is a pile of temp files.
3. **Concurrency** (two profiles practising, or importing while editing) is free in SQLite, needs locking in B.
4. **Moving a category** is one update in D, versus file moves + index updates + stale-path handling in B.

**What D gives up, and the mitigation**: readable history, diffs, and an escape hatch if the app breaks.
Mitigated by keeping the data-file format canonical for import/export with a round-trip test, plus a manual export action.
Auto-export and git automation were considered and **deferred** — not needed while the collection is small and the DB is backed up.

**Layout**

```
var/memo.db                    ← truth: categories, notes, cards, import jobs, review log, card state
var/raw/korean/…/vocab1.jpg    ← uploaded photos/PDFs (filesystem, served statically, referenced by path)
<export dir>/korean/…json      ← written only by the manual "export" action
```

**Accepted risks**: the app is the only way in (CRUD and import/export must be good), schema changes are migrations rather
than scripts over files, and early debugging means `sqlite3` rather than an editor.

---

## Original comparison (kept for context)

### Recommendation 💡 — B, with raw files kept out of git

- **Content**: one data file per import job, in `DATA_DIR`, path = category. Optionally a git repo the server commits to after each save (free history, easy undo, `git pull` to read the collection anywhere).
- **Progress**: SQLite (`review_log` append-only + a `card_state` cache), keyed by note ID + direction, never by path — so moving or renaming files keeps history.
- **Raw uploads**: `DATA_DIR/<category>/raw/`, git-ignored (or in git-annex/LFS if you want them versioned); referenced from the data file by relative path. Losing them costs nothing but a re-photo.
- **Backups**: the whole `DATA_DIR` (one rsync/borg job); SQLite backed up with `VACUUM INTO` so it's consistent.

This keeps the readable, tree-shaped, LLM-friendly content you wanted, and puts the constantly-written, query-heavy part where that's easy.

## Things to decide 💬

1. **A vs B**: data files inside this repo, or a separate `DATA_DIR`?
2. **Auto-commit content to git?** Free history and undo, but a commit per save — noisy but useful.
3. **Raw photos**: keep forever (backed up), keep but exclude from version control, or delete after a data file is confirmed?
4. **Does the collection need to be usable without the app** (readable/editable in an editor or another tool)? This is the main argument for files over D.
5. **Multi-device**: is `DATA_DIR` on the server only, or do you want to sync/clone it to a laptop?

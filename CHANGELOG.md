# Changelog

## 0.1.0 — 2026-10-14

The first release. What it does is in the [user guide](docs/user-guide.md), and why each part is the way it is in
[PLAN.md](PLAN.md).

- **Getting material in:** photos and PDFs read by any OpenAI-compatible LLM with one general
  [prompt](docs/llm-prompt.md), the same one you can give any chat LLM along with your notes; a PDF as its
  text or as pictures of its pages, a few pages per call; `.json`, `.csv`/`.tsv`, `.txt`/`.md` and Anki decks. Every import is a draft you review before it is committed.
- **Importers of your own:** a TOML spec (or a Python module) in `backend/importers.local/`, kept out of git and
  loaded at runtime; [an example](backend/examples/importers/korean-textbook-vocab.toml) for one textbook's layout.
- **Practising:** pick, match, type, build from pieces and flip, moving from the easier to the harder as you learn
  a card; FSRS or SM-2; Practice and Drill sittings of a chosen size; keyboard-only.
- **Listening:** a speaker on every question and answer in a language the device has a voice for, and
  *Read questions aloud* to hear each question as it comes up.
- **The collection:** a category tree, a grid editor, priority marks, search, lists for a dated test, and an audit
  for duplicates and ambiguous answers, fixed in place with `memo patch`.
- **Progress:** words placed as not met, learning, known or mastered, read off the review log.
- **The phone:** installable and offline over HTTPS (Tailscale), with answers synced back.

# CRAM

*Computer-Regulated Acquisition of Memories.* Despite the name, the opposite of cramming.

A flashcard app for your own material. Photograph a textbook page, or bring a file or an LLM's
output, check what was read, then practise it in several ways, from picking the answer to writing it
from memory, on a schedule set by how you answered (FSRS or SM-2). It runs on your own machine,
installs on your phone and works there offline.

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and Node.js.

```sh
cd backend && uv sync && cd ..
./serve.sh                  # migrates the database, builds the frontend once, serves
```

Open <http://127.0.0.1:8000>. With no password set the app is open, which is fine on localhost. To
set one, run `uv run memo hash-password` in `backend/` and put the result in `backend/.env` as
`MEMO_AUTH_PASSWORD_HASH`. Reading photos also needs an LLM provider: `MEMO_LLM_API_KEY` and its
settings in the same file. `./serve.sh --help` lists the options.

To use it from a phone, see [docs/serving.md](docs/serving.md).

## Documentation

| | |
|---|---|
| [docs/user-guide.md](docs/user-guide.md) | how to use the app: importing, practising, lists, progress, the phone |
| [docs/llm-prompt.md](docs/llm-prompt.md) | a prompt to give any LLM with your material, so it writes cards memo imports as they are |
| [docs/format.md](docs/format.md) | the data-file format, and how each kind of file is imported and exported |
| [docs/serving.md](docs/serving.md) | reaching it from a phone over Tailscale, installing, offline, backups |
| [docs/development.md](docs/development.md) | for anyone changing the code, including the rules for LLM agents |
| [PLAN.md](PLAN.md) | the decision record: what was decided, and why |
| [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md) | module maps, and the reasoning behind each feature |
| [docs/storage-options.md](docs/storage-options.md), [spec/answer-check.md](spec/answer-check.md) | the storage decision; the answer checker's spec |

**Your progress lives in one file, `backend/var/memo.db`.** Back it up
(`uv run memo backup --to <dir>` in `backend/`).

The code, the command line and the data format still say `memo`: `uv run memo …`, `MEMO_*` settings,
`"format": "memo.datafile"`.

## Licence

[GPL-3.0-or-later](LICENSE): you may use, change and share it, and what you share stays under
the same licence.

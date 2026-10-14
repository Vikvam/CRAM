# Serving it

*Part of the [memo docs](../README.md#documentation). For using the phone once it is set up, see
[user-guide.md](user-guide.md#on-the-phone).*

The app is one process — the API and the built frontend together — and the SQLite file
beside it is the only copy of every review you have ever done. Everything here is about
getting at it from the phone without putting that file at risk.

## Can it run static?

No, and the reason is the data, not the rendering.

The frontend already *is* a static bundle (`adapter-static`, `fallback: index.html`), but it
ships with nothing in it. Every screen fetches from the API, and practice in particular needs
two things the client cannot work out for itself: `GET /api/practice/queue`, where the server
picks what is due, builds the distractors and suggests a mode, and `POST /api/practice/answer`,
where it grades, advances SM-2 or FSRS and appends to `review_log`. A static host would serve
an empty shell.

What *is* possible, and is what the offline support below does, is to take a batch of cards
along and hand the answers back afterwards. The checker already runs in the client (PLAN 5),
so the phone can grade; it just cannot schedule, and does not try to.

## Reaching the phone

Over **Tailscale**, which is unusual among overlay networks in issuing a real certificate for
your machines as well as routing to them. The certificate is the point: a service worker — the
thing that makes the app open at all with no signal — is refused outside a secure context, and
a LAN address like `http://evoend.local:8000` is not one. ZeroTier, Netbird, Nebula and plain
WireGuard all give reachability and no certificate.

```sh
sudo pacman -S tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up                       # and the phone app, same account
# enable HTTPS once in the admin console, then:
tailscale serve --bg https / http://127.0.0.1:8000
```

Tailscale terminates TLS and forwards to the server as it stands: no certificate files, no
renewal, no reverse proxy, no firewall change — and nothing is exposed to the internet. That
would be `tailscale funnel`, which this does not use. The phone then opens
`https://evoend.<tailnet>.ts.net`.

Firewalld is active here in the `public` zone, so plain `./serve.sh --phone` over the wifi would
be refused anyway. Tailscale sidesteps it: the tailnet is its own interface.

### Three lines for `backend/.env`

```
MEMO_AUTH_PASSWORD_HASH=...    # uv run memo hash-password
MEMO_SECRET_KEY=...            # else every restart signs the phone out
MEMO_COOKIE_SECURE=true        # the cookie never leaves an https page
```

Behind the proxy every request arrives from `127.0.0.1`, so `client_id()` reads the last hop of
`X-Forwarded-For` — but only when the peer is loopback, or anyone locked out could simply claim
to be somebody else.

## Putting it on the home screen

Open `https://<machine>.<tailnet>.ts.net` on the phone, then **Add to home screen** (Chrome offers
it from the ⋮ menu; on iOS it is the share sheet). What opens then has no address bar and no
browser toolbar at the bottom — which is worth doing for its own sake, since that toolbar is what
made navigation-at-the-bottom unusable.

It works because `frontend/static/manifest.webmanifest` declares `display: standalone`, a scope
and real icons: 192 and 512 PNGs, a maskable 512 drawn inside its own safe zone for launchers that
crop to a circle, and `apple-touch-icon.png` at 180 because iOS reads none of the manifest's icons
and will otherwise invent one from a screenshot. They are all generated from `static/icon.svg`:

```sh
cd frontend/static
rsvg-convert -w 192 -h 192 icon.svg -o icon-192.png
rsvg-convert -w 512 -h 512 icon.svg -o icon-512.png
rsvg-convert -w 180 -h 180 icon.svg -o apple-touch-icon.png
rsvg-convert -w 512 -h 512 icon-maskable.svg -o icon-maskable-512.png
```

Installing changes nothing about how it loads: the network is still asked first and the cache is
the fallback. It is the same app, in its own window.

## Practising with no signal

Three pieces, in `frontend/src/lib/offline/` and `frontend/src/service-worker.ts`:

- **The app itself is cached** by the service worker, so it opens with nothing to reach.
  `/api/` is never cached: a stale queue pretending to be current is worse than an honest
  failure.
- **A batch of cards** is kept in IndexedDB, and kept *big enough by itself*: every queue that is
  fetched is kept, and after each load the page quietly fetches a larger one if what is stored is
  missing, too small to last or a day old. There is nothing to press and nothing to remember —
  the *Take cards with me* button this replaced was both easy to miss and a decision the app can
  make on its own. An incidental save never replaces a batch put aside on purpose. Cards already
  answered are filtered out, so a second offline session moves on; and with no batch for the exact
  scope, the widest one there is covers more than that scope rather than less, which the screen
  says out loud.
- **The collection is kept too**, because a batch you cannot reach is no use: every route into a
  session is a link in the category tree, and the tree comes from `/api/`, which is never cached. So
  the last tree this device was shown is kept beside the cards, and the home screen works as it
  always does. Adding pages, the ⋯ panel, a new category, export and opening a file as a sheet all
  need the laptop, so offline they are disabled and say so.
- **Answers go to the outbox first**, always, even when the laptop is right there — one path,
  so the offline one is not a special case that only runs when it is too late to notice it is
  broken. Each gets a ULID and the moment it happened.

Cards are taken along whenever the app is opened with the laptop reachable — nothing to press.
**Settings → Cards on this device** says how many there are and when they arrived, with *Take more
now* for before you leave.

A batch is a photograph, not a feed: after a long stretch the `suggest` on a card is behind what
it now deserves. The answers are still graded and replayed correctly; only the choice of
exercise is stale.

## Getting the answers back

Both ways, and they cannot double-count because `review_log.client_id` is unique per profile:

- **By itself** — the outbox flushes to `POST /api/practice/answers` whenever the laptop is
  reachable, and on every page load.
- **By hand** — *Settings → Answers on this device → Save to a file*, then on the laptop:

  ```sh
  cd backend && uv run memo import-answers ~/Downloads/memo-answers-2026-10-10.json
  ```

Either way the rows are appended with the time they were actually answered, and each card's
cached state is then **replayed** from its whole log rather than nudged forward — so an answer
from last Tuesday arriving today lands where it belongs. Rows taken in this way leave
`state_before` and `state_after` null: they were never scheduled live, and inventing the state
they passed through would be writing a history that did not happen.

## Backups

`memo.db` has no other copy. `VACUUM INTO`, never `cp` — with the write-ahead log the file on
disk is not the whole story.

```sh
cd backend && uv run memo backup              # ~/backups/memo/memo-YYYY-MM-DD.db, last 14
```

Nightly, as a user timer:

```ini
# ~/.config/systemd/user/memo-backup.service
[Unit]
Description=Back up the memo database

[Service]
Type=oneshot
WorkingDirectory=%h/Documents/projekty/memorization/backend
ExecStart=%h/Documents/projekty/memorization/backend/.venv/bin/memo backup
```

```ini
# ~/.config/systemd/user/memo-backup.timer
[Unit]
Description=Nightly memo backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```sh
systemctl --user daemon-reload && systemctl --user enable --now memo-backup.timer
loginctl enable-linger viki    # only if it should run while you are logged out
```

## When the box arrives

The laptop is the server until there is an always-on one. Nothing above is wasted: the user
timer becomes a system timer and `tailscale serve` moves to the box.

Any arm64 or x86_64 Linux box will do — every dependency in `backend/pyproject.toml` is pure
Python or has wheels for both. It wants a `Dockerfile` (uv, `memo serve`) and a `compose.yml`
with `var/` as the only volume and `.env` for the model key; neither is written yet, because an
untested one is worse than none. Moving over is `sqlite3 .backup` of `memo.db` plus a copy of
`var/raw/`, and then the laptop is just another client.

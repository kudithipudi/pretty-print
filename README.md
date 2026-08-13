# pretty-print

Paste a URL, get a clean, reader-formatted version of the page designed to
print well on paper (A4 or Letter): margins, page numbers, no nav/ads/chrome.

Live at [https://lab.kudithipudi.org/pretty-print/](https://lab.kudithipudi.org/pretty-print/).

## What it is

- Takes any `http(s)` URL.
- Content handling: **HTML pages** (main article extracted) and **plain text**
  (printed as a monospace block). PDFs and binary content are rejected with a
  clear message.
- Fetches are **offloaded to Browser Use's cloud** whenever `BROWSER_USE_API_KEY`
  is set — the actual page request happens on their infrastructure, not on this
  server. Falls back to a direct `httpx` fetch, and (optionally) to a headless
  Chromium for JS-heavy pages.
- Every successful fetch is saved to a SQLite **history** so you can re-print
  later without refetching.
- A password-protected **admin** section at `/admin` (gated by `ADMIN_PASSWORD`,
  session-cookie login) lets you delete documents from history.

## Stack

Python 3.12 · FastAPI · gunicorn (uvicorn worker) · Jinja2 · Tailwind CSS ·
Alpine.js · SQLite (aiosqlite). Per the lab standards in
`/var/www/plans/00-STANDARDS.md`.

## Run locally

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env           # fill in BROWSER_USE_API_KEY if you have one
venv/bin/uvicorn app.main:app  # http://127.0.0.1:8000
```

Tests:

```bash
venv/bin/python -m pytest
```

## Deploy

Run behind nginx at `https://lab.kudithipudi.org/pretty-print/`, served from a
unix socket by gunicorn, managed by systemd (`pretty-print.service`,
checked into the repo root under `User=www-data`):

```bash
sudo cp pretty-print.service /etc/systemd/system/pretty-print.service
sudo chown -R www-data:www-data /var/www/pretty-print/data
sudo systemctl daemon-reload
sudo systemctl enable --now pretty-print
sudo systemctl restart pretty-print
```

nginx location block (see the lab vhost): strip the `/pretty-print` prefix
before proxying to `unix:/var/www/pretty-print/pretty-print.sock`:

```nginx
location /pretty-print/ {
    include proxy_params;
    proxy_set_header X-Script-Name /pretty-print;
    proxy_set_header X-Forwarded-Prefix /pretty-print;
    proxy_read_timeout 120s;
    rewrite ^/pretty-print(/.*)$ $1 break;
    proxy_pass http://unix:/var/www/pretty-print/pretty-print.sock;
}
```

## Env vars

| Var | Default | Purpose |
| --- | --- | --- |
| `ROOT_PATH` | `/pretty-print` | Public subpath, used for links in templates. |
| `DB_PATH` | `data/pretty-print.db` | SQLite location. |
| `BROWSER_USE_API_KEY` | *(empty)* | Browser Use cloud key enabling offloaded fetches. |
| `BROWSER_USE_OUTPUT_FORMAT` | `simplified` | `simplified`/`raw`/`markdown`/`structured`. `markdown` is fine for text-heavy pages. |
| `FETCH_TIMEOUT_MS` | `30000` | Per-fetch timeout sent to Browser Use. |
| `FETCH_ALLOW_HEADLESS` | `false` | Enable the headless-Chromium fallback (needs `playwright` + `playwright install chromium`). |
| `FETCH_SEQUENCE_TIMEOUT` | `90` | Outer bound for the whole fetch sequence, seconds. |
| `RATE_LIMIT_PER_MINUTE` | `20` | Per-IP cap on `POST /print` over the trailing window. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Trailing window (seconds) the cap above applies over. |
| `ADMIN_PASSWORD` | *(empty)* | Password for the `/admin` section (delete history, etc.). Empty disables admin login. |
| `SESSION_SECRET` | *(empty)* | Signs the admin session cookie; falls back to `ADMIN_PASSWORD`. Set a stable value — without it every restart logs the admin out. |

## Rebuilding Tailwind CSS

Built with the standalone CLI (vendored at `./tailwindcss`) into the committed
`app/static/css/app.css`:

```bash
./tailwindcss \
  -i app/static/css/input.css \
  -o app/static/css/app.css --minify
```

Alpine.js is vendored (pinned 3.14.9) at `app/static/js/alpine.min.js`.

## Fetch backends in order

1. **browser_use** — `fetch-use` SDK → Browser Use's cloud (offloaded; the
   target site never sees this server's IP).
2. **httpx** — plain GET from this server.
3. **headless** — headless Chromium via Playwright, only when
   `FETCH_ALLOW_HEADLESS=true` **and** the optional dependency is installed.

Extraction: `readability-lxml` pulls the main article out of HTML; if no
article is found (or it's too short) the page is converted to plain text so
there is still something printable.

## Security notes

This tool is public with no auth, fetches arbitrary user-supplied URLs, and
renders the extracted result with `| safe` for anyone who later opens
`/d/{id}` or `/history` — so two classes of risk get explicit guards:

- **SSRF**: before the `httpx` or `headless` backends (which run on this
  server) connect, the target hostname is resolved and rejected if any
  resolved address is loopback/private/link-local/reserved (e.g. cloud
  metadata at `169.254.169.254`). `browser_use` is exempt since that request
  runs on Browser Use's infrastructure, not this network. Note: redirects
  followed after the check are not re-validated per hop.
- **Stored XSS**: every HTML fragment that ends up in the DB — from article
  extraction, readability's whole-document fallback, or markdown-to-HTML
  conversion — is passed through an `lxml.html.clean.Cleaner` allowlist
  (`app/services/extractor.py:sanitize_html`) that strips scripts, event
  handler attributes, `javascript:` links, and inline styles before storage.
- **Abuse / cost control**: `POST /print` — the only route that can call the
  paid Browser Use API or fetch an arbitrary URL — is capped per IP
  (`RATE_LIMIT_PER_MINUTE` hits per `RATE_LIMIT_WINDOW_SECONDS`, default 20/60s).
  Hits are recorded in SQLite rather than in-process memory so the limit holds
  across gunicorn's worker processes; old hits are pruned automatically.
- **Admin**: `/admin` and its state-changing actions (delete from history) are
  gated by a session cookie set only after a correct `ADMIN_PASSWORD`
  (`secrets.compare_digest`), signed with `SESSION_SECRET`. The admin session
  is confined to the app's own routes; the cookie uses the default path since
  nginx strips the `/pretty-print` prefix before proxying.

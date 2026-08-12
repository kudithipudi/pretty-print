-- Canonical schema for pretty-print.
-- Applied idempotently on startup via app/db.py (CREATE TABLE IF NOT EXISTS).

-- One row per fetched URL. content is the cleaned, print-ready HTML fragment
-- (for HTML sources) or escaped plain text (for text/* sources). Storing it
-- means "re-print from history" never refetches the page.
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    final_url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    -- browser_use | httpx | headless | text  -- how the content was obtained.
    source TEXT NOT NULL DEFAULT '',
    -- html | text -- how content should be rendered on the print page.
    content_type TEXT NOT NULL DEFAULT 'html',
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok'
        CHECK (status IN ('ok', 'error')),
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents (created_at);

-- One row per rate-limited request, used to throttle abuse of expensive
-- routes (POST /print, which can call the paid Browser Use API and fetch
-- arbitrary URLs). Hits older than the limiting window are pruned as new
-- ones are recorded, so this stays small. A plain table (rather than an
-- in-process counter) so the limit is enforced consistently across all
-- gunicorn workers, which don't share memory.
CREATE TABLE IF NOT EXISTS rate_limit_hits (
    ip TEXT NOT NULL,
    route TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_route_ip_time ON rate_limit_hits (route, ip, created_at);

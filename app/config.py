from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    root_path: str = "/pretty-print"
    db_path: str = "data/pretty-print.db"

    # App log verbosity (see §7 of the lab standards): flip via LOG_LEVEL in
    # .env without touching code.
    log_level: str = "info"

    # Browser Use (browser-use.com) fetch-use SDK. The actual page fetch happens
    # on Browser Use's infrastructure, not this server. Empty -> skipped, the
    # app falls back to a direct httpx fetch.
    browser_use_api_key: str = ""
    browser_use_output_format: str = "simplified"
    fetch_timeout_ms: int = 30000

    # Optional last-resort backend for JS-heavy pages. When set and the
    # playwright package + browser binaries are installed, the fetcher will
    # render the page in a headless Chromium instead of a plain httpx GET when
    # both cloud fetch and the direct fetch fail.
    fetch_allow_headless: bool = False

    # Outer bound on the whole fetch sequence (seconds).
    fetch_sequence_timeout: int = 90

    # Per-IP cap on POST /print (the route that can call the paid Browser Use
    # API and fetch arbitrary URLs), enforced over a trailing window.
    rate_limit_per_minute: int = 20
    rate_limit_window_seconds: int = 60

    # Admin section. ADMIN_PASSWORD gates /admin; SESSION_SECRET signs the
    # login cookie (falls back to ADMIN_PASSWORD if unset so a fresh checkout
    # runs, but set a stable SESSION_SECRET in .env — without it every restart
    # logs the admin out).
    admin_password: str = ""
    session_secret: str = ""


def get_settings() -> Settings:
    # Not cached: this app runs a single gunicorn worker and Settings() is cheap
    # to build, so we always read the current environment/.env rather than risk
    # a stale cached instance (e.g. across tests that monkeypatch env vars).
    return Settings()
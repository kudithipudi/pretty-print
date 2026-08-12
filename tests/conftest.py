import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.fetcher import FetchResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient wired to a throwaway SQLite db and no Browser-Use key, so
    tests never touch the network."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app-test.db"))
    monkeypatch.setenv("BROWSER_USE_API_KEY", "")
    monkeypatch.setenv("FETCH_ALLOW_HEADLESS", "false")
    monkeypatch.setenv("ROOT_PATH", "/pretty-print")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_fetcher(monkeypatch):
    """Stub fetch_and_normalize so POST /print never performs a real fetch.
    Records the URL it received so tests can assert form parsing."""

    def _install(result: FetchResult | None = None, exc: Exception | None = None):
        calls: list[str] = []

        _result = result or FetchResult(
            final_url="https://example.com/article",
            title="Example Article",
            source="httpx",
            content_type="html",
            content="<h1>Hello</h1><p>Printable body text.</p>",
        )

        async def _fake(url: str, settings):
            calls.append(url)
            if exc is not None:
                raise exc
            return _result

        monkeypatch.setattr("app.routers.pages.fetch_and_normalize", _fake)
        return calls

    return _install
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import init_db
from app.main import app
from app.services.fetcher import FetchResult


TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """An AsyncClient wired to a throwaway SQLite db and no Browser-Use key, so
    tests never touch the network."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app-test.db"))
    monkeypatch.setenv("BROWSER_USE_API_KEY", "")
    monkeypatch.setenv("FETCH_ALLOW_HEADLESS", "false")
    monkeypatch.setenv("ROOT_PATH", "/pretty-print")
    monkeypatch.setenv("ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    # ASGITransport doesn't run lifespan hooks, so apply the schema here.
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def anon_client(client):
    """A client with no admin session — for exercising what a visitor who
    hasn't logged in can and can't reach."""
    return client


@pytest_asyncio.fixture
async def admin_client(client):
    """A client already logged in to /admin (session cookie carries over to
    every subsequent request, same as a real browser)."""
    resp = await client.post(
        "/admin/login", data={"password": TEST_ADMIN_PASSWORD}, follow_redirects=False
    )
    assert resp.status_code == 303
    return client


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

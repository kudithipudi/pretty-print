import pytest

from app.services.fetcher import (FetchError, FetchResult, _fetch_httpx,
                                   _is_public_ip, validate_url)


# --- public pages (smoke tests) ------------------------------------------


async def test_index_ok(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "pretty-print" in resp.text
    assert 'name="url"' in resp.text


async def test_history_ok_empty(client):
    resp = await client.get("/history")
    assert resp.status_code == 200
    assert "History" in resp.text


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_unknown_doc_404(client):
    resp = await client.get("/d/99999")
    assert resp.status_code == 404


async def test_missing_url_rejected(client):
    resp = await client.post("/print", data={"url": ""}, follow_redirects=False)
    assert resp.status_code == 400


async def test_url_validation(client):
    resp = await client.post("/print", data={"url": "not-a-url"}, follow_redirects=False)
    assert resp.status_code == 400


async def _print_one(client, url="https://example.com/article"):
    return await client.post(
        "/print", data={"url": url}, follow_redirects=False
    )


# --- print flow ----------------------------------------------------------


async def test_post_print_saves_and_redirects(client, fake_fetcher):
    calls = fake_fetcher()
    resp = await _print_one(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/d/1"
    # The submitted URL must actually reach the fetcher (form parsing).
    assert calls == ["https://example.com/article"]


async def test_print_view_renders_content(client, fake_fetcher):
    fake_fetcher()
    await _print_one(client)

    resp = await client.get("/d/1")
    assert resp.status_code == 200
    assert "Example Article" in resp.text
    assert "Printable body text" in resp.text
    # App chrome is hidden when printing.
    assert "print:hidden" in resp.text


async def test_print_paper_param(client, fake_fetcher):
    fake_fetcher()
    await _print_one(client)

    assert "size: A4" in (await client.get("/d/1")).text
    assert "size: Letter" in (await client.get("/d/1?paper=letter")).text
    # Bogus value falls back to A4.
    assert "size: A4" in (await client.get("/d/1?paper=weird")).text


async def test_print_rate_limited_per_ip(client, fake_fetcher, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    fake_fetcher()

    assert (await _print_one(client, "https://example.com/1")).status_code == 303
    assert (await _print_one(client, "https://example.com/2")).status_code == 303
    resp = await _print_one(client, "https://example.com/3")
    assert resp.status_code == 429
    assert "Too many requests" in resp.text


async def test_rate_limit_honors_x_forwarded_for(client, fake_fetcher, monkeypatch):
    """Two distinct X-Forwarded-For values must get independent rate-limit
    buckets, proving the client IP is read from the proxy header rather than
    falling back to a single shared value (e.g. the test transport's socket
    peer, which is the same for every request)."""
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    fake_fetcher()

    async def _print_as(ip, url):
        return await client.post(
            "/print",
            data={"url": url},
            headers={"X-Forwarded-For": ip},
            follow_redirects=False,
        )

    # Exhaust the limit for 1.1.1.1.
    assert (await _print_as("1.1.1.1", "https://example.com/1")).status_code == 303
    assert (await _print_as("1.1.1.1", "https://example.com/2")).status_code == 303
    assert (await _print_as("1.1.1.1", "https://example.com/3")).status_code == 429

    # A different forwarded IP still has a fresh bucket.
    assert (await _print_as("2.2.2.2", "https://example.com/4")).status_code == 303


async def test_history_lists_saved_docs(client, fake_fetcher):
    fake_fetcher()
    await _print_one(client)
    await _print_one(client)

    resp = await client.get("/history")
    assert resp.status_code == 200
    assert resp.text.count("Example Article") >= 2


async def test_fetch_error_rerenders_home(client, fake_fetcher):
    fake_fetcher(exc=FetchError("upstream blocked us"))
    resp = await _print_one(client)
    assert resp.status_code == 400
    assert "upstream blocked us" in resp.text


async def test_text_content_rendered(client, fake_fetcher):
    result = FetchResult(
        final_url="https://example.com/notes.txt",
        title="",
        source="browser_use",
        content_type="text",
        content="<pre class=\"print-text\">raw text line1\nline2</pre>",
    )
    fake_fetcher(result=result)
    await _print_one(client, "https://example.com/notes.txt")

    resp = await client.get("/d/1")
    assert resp.status_code == 200
    assert "raw text line1" in resp.text


async def test_title_falls_back_to_url(client, fake_fetcher):
    result = FetchResult(
        final_url="https://example.com/notes.txt",
        title="",
        source="httpx",
        content_type="text",
        content="<pre class=\"print-text\">hello</pre>",
    )
    fake_fetcher(result=result)
    await _print_one(client, "https://example.com/notes.txt")

    resp = await client.get("/d/1")
    assert "https://example.com/notes.txt" in resp.text


# --- fetcher URL validation unit tests -----------------------------------


async def test_validate_url_accepts_http_https():
    assert validate_url("https://example.com/x") == "https://example.com/x"
    assert validate_url("  http://example.com  ") == "http://example.com"


def test_validate_url_rejects_bad_schemes():
    for bad in ("ftp://example.com", "javascript:alert(1)", "example.com", "file:///etc/passwd"):
        try:
            validate_url(bad)
        except FetchError:
            continue
        raise AssertionError(f"expected FetchError for {bad!r}")


# --- SSRF guard -----------------------------------------------------------


def test_is_public_ip():
    assert _is_public_ip("93.184.216.34") is True  # example.com
    assert _is_public_ip("127.0.0.1") is False
    assert _is_public_ip("10.0.0.5") is False
    assert _is_public_ip("192.168.1.1") is False
    assert _is_public_ip("169.254.169.254") is False  # cloud metadata
    assert _is_public_ip("::1") is False
    assert _is_public_ip("not-an-ip") is False


async def test_fetch_httpx_blocks_loopback_target():
    with pytest.raises(FetchError, match="private or internal"):
        await _fetch_httpx("http://127.0.0.1:22/")


async def test_fetch_httpx_blocks_localhost_hostname():
    with pytest.raises(FetchError, match="private or internal"):
        await _fetch_httpx("http://localhost/")

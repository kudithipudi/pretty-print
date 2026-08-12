"""Fetch a URL and normalize it into print-ready content.

Fetch strategy (first success wins):

1. **browser_use** — if `BROWSER_USE_API_KEY` is set, the fetch is delegated to
   Browser Use's cloud via the `fetch-use` SDK. The actual page request happens
   on their infrastructure, so the burden (and the TLS/bot fingerprint) stays
   off this server.
2. **httpx** — a plain GET from this server (works for most static pages).
3. **headless** — if enabled AND the optional `playwright` package with a
   Chromium build is installed, render the page with a real browser (handles
   JS-heavy SPAs as a last resort).

Each backend returns a raw payload; `extractor` turns it into a print-safe
HTML fragment or escaped text block.
"""

import asyncio
import logging
import urllib.parse
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.services.extractor import (extract_html, plain_text_block,
                                     sniff_content_type)

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/131.0.0.0 Safari/537.36"
)


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    final_url: str
    title: str
    source: str  # browser_use | httpx | headless | text
    content_type: str  # html | text
    content: str
    status: str = "ok"
    error: str = ""


def validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FetchError("Please enter a valid http(s) URL.")
    return url.strip()


async def fetch_and_normalize(url: str, settings: Settings) -> FetchResult:
    try:
        return await asyncio.wait_for(
            _fetch_sequence(url, settings),
            timeout=settings.fetch_sequence_timeout,
        )
    except asyncio.TimeoutError as exc:
        raise FetchError("Fetch timed out after %ds." % settings.fetch_sequence_timeout) from exc


async def _fetch_sequence(url: str, settings: Settings) -> FetchResult:
    url = validate_url(url)
    errors: list[str] = []

    if settings.browser_use_api_key:
        try:
            return await _fetch_browser_use(url, settings)
        except Exception as exc:
            err = f"browser_use: {exc}"
            logger.warning("Browser-Use fetch failed for %s: %s", url, exc)
            errors.append(err)

    try:
        return await _fetch_httpx(url)
    except Exception as exc:
        err = f"httpx: {exc}"
        logger.warning("Direct fetch failed for %s: %s", url, exc)
        errors.append(err)

    if settings.fetch_allow_headless:
        try:
            return await _fetch_headless(url)
        except Exception as exc:
            err = f"headless: {exc}"
            logger.warning("Headless fetch failed for %s: %s", url, exc)
            errors.append(err)

    detail = "; ".join(errors) if errors else "URL could not be fetched (empty response)."
    raise FetchError(f"Could not fetch content: {detail}")


async def _fetch_browser_use(url: str, settings: Settings) -> FetchResult:
    """Delegate the fetch to Browser Use's cloud via the fetch-use SDK.

    fetch_sync is blocking; run it off the event loop."""
    from fetch_use import FetchError as BUError
    from fetch_use import fetch_sync

    def _run():
        return fetch_sync(
            url,
            output_format=settings.browser_use_output_format,
            timeout_ms=settings.fetch_timeout_ms,
        )

    try:
        response = await asyncio.to_thread(_run)
        response.raise_for_status()
    except BUError as exc:
        raise FetchError(str(exc)) from exc
    except Exception as exc:
        # raise_for_status on non-2xx surfaces an HTTPError.
        raise FetchError(f"status {getattr(response, 'status_code', '?')}: {exc}") from exc

    body = response.text or ""
    if not body:
        raise FetchError("Empty response body from Browser-Use.")

    if settings.browser_use_output_format == "markdown":
        from markdown import markdown

        title = _guess_title_from_markdown(body, url)
        return FetchResult(
            final_url=response.url or url,
            title=title,
            source="browser_use",
            content_type="html",
            content=markdown(body, extensions=["fenced_code", "tables", "sane_lists"]),
        )

    ctype = sniff_content_type(response.headers.get("content-type", ""), body)
    if ctype is None:
        raise FetchError("Unsupported content type returned by the site.")
    return _normalize_payload(
        final_url=response.url or url,
        title="",
        source="browser_use",
        content_type_header=response.headers.get("content-type", ""),
        body=body,
    )


async def _fetch_httpx(url: str) -> FetchResult:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml,text/plain,*/*"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.text
        if not body:
            raise FetchError("Empty response body.")

    return _normalize_payload(
        final_url=str(resp.url),
        title="",
        source="httpx",
        content_type_header=resp.headers.get("content-type", ""),
        body=body,
    )


async def _fetch_headless(url: str) -> FetchResult:
    """Render the page in a headless Chromium (requires playwright + browser).

    Plays two roles: JS-heavy single-page apps that never render without a
    browser, and pages that block plain HTTP clients."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=_UA)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            body = await page.content()
            page_title = await page.title()
        finally:
            await browser.close()

    if not body:
        raise FetchError("Headless browser returned an empty page.")
    return _normalize_payload(
        final_url=url,
        title=page_title or "",
        source="headless",
        content_type_header="text/html",
        body=body,
    )


def _normalize_payload(
    *,
    final_url: str,
    title: str,
    source: str,
    content_type_header: str,
    body: str,
) -> FetchResult:
    ctype = sniff_content_type(content_type_header, body)
    if ctype is None:
        raise FetchError("Unsupported content type returned by the site.")
    if ctype == "text":
        return FetchResult(
            final_url=final_url,
            title=title,
            source=source,
            content_type="text",
            content=plain_text_block(body),
        )
    content_type, content, extracted_title = extract_html(body)
    return FetchResult(
        final_url=final_url,
        title=extracted_title or title,
        source=source,
        content_type=content_type,
        content=content,
    )


def _guess_title_from_markdown(md: str, url: str) -> str:
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return url
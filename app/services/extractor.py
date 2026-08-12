"""Normalize fetched content into clean, print-safe HTML.

Every backend (browser-use cloud, plain httpx, optional headless) returns a
raw payload; these helpers turn that payload into:
  * content_type == "html"  -> a cleaned article HTML fragment
  * content_type == "text"  -> an escaped <pre> block
Either way the result is safe to render with |safe in a Jinja2 template.
"""

import logging
import re
from html import escape

from markdown import markdown
from markdownify import markdownify
from readability import Document

logger = logging.getLogger(__name__)

# Content we cannot sensibly print.
UNSUPPORTED_TYPES = {
    "application/pdf": "PDF files are not supported — open them directly and use the browser print dialog.",
    "application/octet-stream": "Binary content is not supported.",
    "application/zip": "Binary content is not supported.",
}

# content-type sniffing: strip parameters and lowercase.
def _ctype(header_value: str | None) -> str:
    if not header_value:
        return ""
    return header_value.split(";")[0].strip().lower()


def sniff_content_type(header_value: str | None, body: str) -> str | None:
    """Decide how to treat a fetched payload: 'html', 'text', or None if the
    payload is an unsupported binary type."""
    ct = _ctype(header_value)
    if ct in UNSUPPORTED_TYPES:
        return None
    if ct and ct not in ("text/html", "application/xhtml+xml", "text/plain", "text/markdown"):
        # e.g. application/json, application/xml -> treat as printable text.
        return "text"
    if ct in ("text/plain", "text/markdown"):
        return "text"
    # No/inconclusive header: sniff the body.
    head = body[:512].lstrip()
    if head.lower().startswith("<!doctype") or head.lower().startswith("<html") or "<body" in head.lower():
        return "html"
    return "text"


def clean_html_to_text(html: str) -> str:
    """Fallback for when readability finds no article: convert an HTML blob to
    plain markdown-text so we still print something useful."""
    try:
        return markdownify(html, heading_style="ATX", strip=["img", "figure", "script", "noscript", "style", "svg", "iframe"]).strip()
    except Exception:
        logger.warning("markdownify conversion failed; returning raw text", exc_info=True)
        return re.sub(r"<[^>]+>\s*", " ", html)


def extract_html(html: str, fallback_source: str = "") -> tuple[str, str, str]:
    """Return (content_type, content, title or '') for an HTML payload.

    Uses readability-lxml to pull out the main article. If that yields nothing
    useful, falls back to a markdownified, boilerplate-free version of the body.
    """
    try:
        doc = Document(html)
        title = (doc.short_title() or "").strip()
    except Exception:
        logger.warning("readability failed to parse page", exc_info=True)
        title = ""
        summary = ""
    else:
        summary = (doc.summary() or "").strip()

    if len(summary) >= 120:
        return "html", summary, title

    # No extractable article -> turn the whole page into plain text.
    body_text = clean_html_to_text(html)
    if not body_text:
        body_text = fallback_source or "No readable content found on this page."
    return "text", escape_text(body_text), title


def markdown_to_html(md: str) -> str:
    """Convert markdown (e.g. from browser-use fetch-use) to a clean HTML fragment."""
    html = markdown(
        md,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )
    return html


def escape_text(text: str) -> str:
    """Escape raw plain text and wrap it in a <pre> for the print template."""
    return f"<pre class=\"print-text\">{escape(text)}</pre>"


def plain_text_block(text: str) -> str:
    return escape_text(text)
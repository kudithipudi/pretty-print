"""Normalize fetched content into clean, print-safe HTML.

Every backend (browser-use cloud, plain httpx, optional headless) returns a
raw payload; these helpers turn that payload into:
  * content_type == "html"  -> a cleaned article HTML fragment
  * content_type == "text"  -> an escaped <pre> block
Either way the result is safe to render with |safe in a Jinja2 template.

Extraction strategy, in order:
  1. If the page has one or more <article> elements, rebuild the largest one
     from its meaningful blocks (headings, paragraphs, lists, quotes, code,
     tables). This is what makes news sites like the BBC come out whole —
     whole-document readability often loses to a "related articles" rail.
  2. Otherwise run readability-lxml over the whole document.
  3. If neither yields a usable article, convert the page body to plain text.
"""

import logging
import re
from html import escape

from lxml import etree, html as lxml_html
from lxml.html.clean import Cleaner
from markdown import markdown
from markdownify import markdownify
from readability import Document

logger = logging.getLogger(__name__)

# Any HTML fragment stored and later rendered with `| safe` must be sanitized
# first: extracted articles carry the source site's markup verbatim (event
# handler attributes, javascript: links, etc.), and this app has no auth —
# every visitor to /d/{id} and /history executes whatever survives here.
_cleaner = Cleaner(
    scripts=True,
    javascript=True,
    comments=True,
    style=True,
    inline_style=True,
    links=False,
    meta=True,
    page_structure=True,
    processing_instructions=True,
    embedded=True,
    frames=True,
    forms=True,
    annoying_tags=True,
    remove_unknown_tags=False,
    safe_attrs_only=True,
)


def sanitize_html(fragment: str) -> str:
    """Strip anything in an HTML fragment that could execute on render."""
    if not fragment or not fragment.strip():
        return fragment
    try:
        return _cleaner.clean_html(fragment)
    except Exception:
        logger.warning("HTML sanitization failed; dropping fragment", exc_info=True)
        return ""


# Content we cannot sensibly print.
UNSUPPORTED_TYPES = {
    "application/pdf": "PDF files are not supported — open them directly and use the browser print dialog.",
    "application/octet-stream": "Binary content is not supported.",
    "application/zip": "Binary content is not supported.",
}

# Blocks inside an <article> that are meaningful for print.
_ARTICLE_BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "ul", "ol", "blockquote", "pre", "table", "hr", "img",
}

# Sub-trees that should never end up on paper.
_NOISE_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "canvas", "video",
    "audio", "form", "button", "input", "select", "textarea", "nav",
    "aside", "footer", "figcaption",
}

# Minimum plain-text length before we trust a targeted <article> extraction.
_ARTICLE_MIN_LEN = 200


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
    """Fallback for when nothing extractable is found: convert an HTML blob to
    plain markdown-text so we still print something useful."""
    try:
        return markdownify(html, heading_style="ATX", strip=["img", "figure", "script", "noscript", "style", "svg", "iframe"]).strip()
    except Exception:
        logger.warning("markdownify conversion failed; returning raw text", exc_info=True)
        return re.sub(r"<[^>]+>\s*", " ", html)


def _article_elements(html: str) -> list:
    """Parse the page and return each <article> element (in document order)."""
    try:
        root = lxml_html.fromstring(html)
    except Exception:
        return []
    return root.xpath("//article")


def _plain_len(fragment: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", fragment).strip())


def extract_from_article_element(article_root) -> str:
    """Rebuild a print-friendly HTML fragment from one <article> element,
    keeping only meaningful blocks with their inline formatting."""
    # Drop noise sub-trees first.
    for tag in _NOISE_TAGS:
        for el in article_root.xpath(f".//{tag}"):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    keep: list = []
    for el in article_root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag == "img":
            src = el.get("src") or ""
            alt = el.get("alt") or ""
            if src.startswith("http"):
                for k in list(el.attrib):
                    del el.attrib[k]
                if src:
                    el.set("src", src)
                if alt:
                    el.set("alt", alt)
                keep.append(el)
            continue
        if el.tag not in _ARTICLE_BLOCK_TAGS:
            continue
        if not el.text_content().strip():
            continue
        keep.append(el)

    # Dedup: if an element is nested inside another kept element, drop the
    # inner one (e.g. <li> inside a retained <ul>; <p> inside <blockquote>).
    roots = [el for el in keep if not any(
        el is not other and el in list(other.iter()) for other in keep
    )]

    container = etree.Element("div")
    for el in roots:
        container.append(el)
    return lxml_html.tostring(container, encoding="unicode")


def extract_html(html: str, fallback_source: str = "") -> tuple[str, str, str]:
    """Return (content_type, content, title or '') for an HTML payload."""
    title = ""
    tried_fragments: list[str] = []

    articles = _article_elements(html)
    for article_root in articles:
        frag = extract_from_article_element(article_root)
        if _plain_len(frag) >= _ARTICLE_MIN_LEN:
            title = _page_title(html)
            return "html", sanitize_html(frag), title
        tried_fragments.append(frag)

    # No trustworthy <article>: fall back to whole-document readability.
    try:
        doc = Document(html)
        t = (doc.short_title() or "").strip()
        summary = (doc.summary() or "").strip()
    except Exception:
        logger.warning("readability failed to parse page", exc_info=True)
        t, summary = "", ""

    for frag in tried_fragments:
        if frag and _plain_len(frag) >= _ARTICLE_MIN_LEN // 2:
            return "html", sanitize_html(frag), t

    if len(summary) >= 120:
        return "html", sanitize_html(summary), t or title

    body_text = clean_html_to_text(html)
    if not body_text:
        body_text = fallback_source or "No readable content found on this page."
    return "text", escape_text(body_text), t or title


def _page_title(html: str) -> str:
    try:
        return (Document(html).short_title() or "").strip()
    except Exception:
        return ""


def markdown_to_html(md: str) -> str:
    """Convert markdown (e.g. from browser-use fetch-use) to a clean HTML fragment.

    python-markdown passes raw HTML embedded in the source through unescaped,
    so the result still needs sanitizing before it's safe to render.
    """
    html_out = markdown(
        md,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )
    return sanitize_html(html_out)


def escape_text(text: str) -> str:
    """Escape raw plain text and wrap it in a <pre> for the print template."""
    return f"<pre class=\"print-text\">{escape(text)}</pre>"


def plain_text_block(text: str) -> str:
    return escape_text(text)
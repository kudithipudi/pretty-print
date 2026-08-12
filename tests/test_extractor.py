import re

from app.services.extractor import (extract_html, plain_text_block,
                                     sniff_content_type)

HTML_WITH_ARTICLE = """<!DOCTYPE html>
<html><head><title>BBC-style headline</title></head><body>
<nav><a href="/">Home</a><a href="/news">News</a></nav>
<div class="rail">
  <div class="card"><div class="card-text-wrapper"><p>Related article one more words here</p></div></div>
  <div class="card"><div class="card-text-wrapper"><p>Related article two even more words</p></div></div>
</div>
<article>
  <h1>Wisconsin result dents winning streak for Democratic Party's left wing</h1>
  <div><p data-component="paragraph">David Crowley is projected to have won a primary election to become the Democratic candidate for Wisconsin governor, edging out progressive challenger Francesca Hong by less than half a percentage point.</p></div>
  <div><p data-component="paragraph">Anti-establishment Democrats across the US had previously notched up victories that have rattled the party leadership this cycle.</p></div>
  <div><h2>What happens next</h2><p>The governor's race in November will be contested by Crowley and Tom Tiffany, who easily won the Republican primary.</p></div>
  <figure><img src="https://ichef.bbci.co.uk/foo.jpg" alt="candidate" /><figcaption>caption</figcaption></figure>
  <blockquote><p>A longer quote from the article that stretches across a couple of lines of text to be substantial.</p></blockquote>
</article>
<footer>About BBC</footer>
</body></html>
"""


def test_sniff_content_type_text_plain():
    assert sniff_content_type("text/plain", "hello") == "text"
    assert sniff_content_type("text/plain; charset=utf-8", "hello") == "text"


def test_sniff_content_type_html():
    assert sniff_content_type("text/html", "<html><body>x</body></html>") == "html"
    assert sniff_content_type("", "<!DOCTYPE html><html>") == "html"


def test_sniff_content_type_unsupported():
    assert sniff_content_type("application/pdf", "") is None


def test_extract_article_preferred_over_rail():
    ctype, content, title = extract_html(HTML_WITH_ARTICLE)
    assert ctype == "html"
    text = re.sub(r"<[^>]+>", " ", content)
    # The real article body is present and long enough to be trusted.
    assert "David Crowley is projected to have won a primary election" in text
    assert "What happens next" in text
    # The rail should not end up as the parent block, and its two bogus cards
    # must not dominate: article text is far longer.
    assert len(text.strip()) >= 300


def test_extract_article_keeps_headings_and_blocks():
    ctype, content, _ = extract_html(HTML_WITH_ARTICLE)
    assert "<h1>" in content
    assert "<h2>" in content
    assert "<blockquote" in content
    assert "<img src=" in content
    assert "alt=" in content
    # Noise is gone.
    assert "<script" not in content
    assert "Related article" not in content


def test_plain_text_block():
    block = plain_text_block("line1\nline2")
    assert '<pre class="print-text">' in block
    assert "line1\nline2" in block


def test_simple_html_via_readability():
    html = ("<html><head><title>Blog post</title></head><body>"
            "<div id='masthead'>Logo nav links everywhere</div>"
            "<div class='content'><h1>My Trip</h1>"
            "<p>" + ("This is a genuinely long paragraph of travel writing " * 30) + "</p>"
            "</div></body></html>")
    ctype, content, title = extract_html(html)
    assert ctype == "html"
    assert title == "Blog post"
    assert "My Trip" in content or "My Trip" in __import__("re").sub(r"<[^>]+>", "", content)
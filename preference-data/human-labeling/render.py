"""Markdown -> sanitized HTML for model answers.

Model outputs are markdown-formatted and can be long, so rendering is cached by
content hash: each answer is rendered once per process.
"""

from functools import lru_cache

import bleach
import markdown as md
from markupsafe import Markup

ALLOWED_TAGS = [
    "p", "br", "hr", "span", "div",
    "strong", "b", "em", "i", "u", "s", "del", "ins", "mark", "sup", "sub",
    "code", "pre", "kbd", "samp", "blockquote",
    "ul", "ol", "li", "dl", "dt", "dd",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "img",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
]

ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title"],
    "code": ["class"],
    "pre": ["class"],
    "span": ["class"],
    "div": ["class"],
    "th": ["align", "colspan", "rowspan"],
    "td": ["align", "colspan", "rowspan"],
    "ol": ["start"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


@lru_cache(maxsize=4096)
def _render(text: str) -> str:
    html = md.markdown(
        text or "",
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
        output_format="html",
    )
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


def render_markdown(text: str) -> Markup:
    """Render trusted-source markdown to HTML safe to drop into a template."""
    return Markup(_render(text or ""))

"""Page-range specification parsing.

A page spec is a string of comma-separated items, each either a single 1-based
page number ("5") or an inclusive range ("3-7"). The literal "all" (any case)
selects every page.
"""

from __future__ import annotations

PageSpec = str


class PageSpecError(ValueError):
    """Raised when a page spec is malformed or out of range."""


def parse_pages(spec: PageSpec, page_count: int) -> list[int]:
    """Parse a page spec into a sorted, de-duplicated list of 1-based page numbers.

    Raises PageSpecError for malformed specs or pages outside 1..page_count.
    """
    spec = spec.strip()
    if not spec:
        raise PageSpecError("Empty page spec; expected 'all', a page number, or a range like 3-7")
    if spec.lower() == "all":
        return list(range(1, page_count + 1))

    pages: set[int] = set()
    for item in spec.split(","):
        item = item.strip()
        if not item:
            raise PageSpecError(f"Empty item in page spec {spec!r}")
        first, sep, last = item.partition("-")
        start = _parse_page_number(first, spec)
        end = _parse_page_number(last, spec) if sep else start
        if end < start:
            raise PageSpecError(f"Reversed range {item!r} in page spec {spec!r}")
        for page in (start, end):
            if not 1 <= page <= page_count:
                raise PageSpecError(f"Page {page} is out of range; valid pages are 1-{page_count}")
        pages.update(range(start, end + 1))
    return sorted(pages)


def _parse_page_number(text: str, spec: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise PageSpecError(f"Invalid page number {text!r} in page spec {spec!r}")
    return int(text)

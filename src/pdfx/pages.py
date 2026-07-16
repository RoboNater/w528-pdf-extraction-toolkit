"""Page-range specification parsing.

A page spec is a string of comma-separated items, each either a single page
("5") or an inclusive range ("3-7"). The literal "all" (any case) selects every
page. Items are interpreted either as 1-based physical positions (parse_pages)
or against the PDF's page labels such as "iv" or "FM2" (parse_page_labels).
"""

from __future__ import annotations

from collections.abc import Sequence

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


def parse_page_labels(spec: PageSpec, labels: Sequence[str]) -> list[int]:
    """Parse a page spec against a PDF's page labels (one label per physical page).

    Items are labels ("iv", "FM2", "5") or label ranges ("i-xx", "1-30"); ranges
    cover the physical span between their endpoints. Returns sorted, de-duplicated
    1-based physical page numbers. An item that exactly matches a label wins over
    range interpretation, so labels containing hyphens stay addressable.
    """
    spec = spec.strip()
    if not spec:
        raise PageSpecError("Empty page spec; expected 'all', a page label, or a range like i-xx")
    if spec.lower() == "all":
        return list(range(1, len(labels) + 1))
    pages: set[int] = set()
    for item in spec.split(","):
        item = item.strip()
        if not item:
            raise PageSpecError(f"Empty item in page spec {spec!r}")
        start, end = _resolve_label_item(item, labels, spec)
        pages.update(range(start, end + 1))
    return sorted(pages)


def _resolve_label_item(item: str, labels: Sequence[str], spec: str) -> tuple[int, int]:
    single = _find_label(item, labels)
    if single is not None:
        return single, single
    reversed_range = None
    for pos in (i for i, ch in enumerate(item) if ch == "-"):
        start = _find_label(item[:pos], labels)
        end = _find_label(item[pos + 1 :], labels)
        if start is not None and end is not None:
            if start <= end:
                return start, end
            reversed_range = (start, end)
    if reversed_range is not None:
        raise PageSpecError(f"Reversed range {item!r} in page spec {spec!r}")
    raise PageSpecError(
        f"No page labeled {item!r} in this PDF (labels run from {labels[0]!r} to {labels[-1]!r})"
    )


def _find_label(label: str, labels: Sequence[str]) -> int | None:
    """1-based physical page for a label; exact match first, then unique
    case-insensitive match."""
    label = label.strip()
    if label in labels:
        return labels.index(label) + 1
    matches = [i for i, candidate in enumerate(labels) if candidate.lower() == label.lower()]
    if len(matches) == 1:
        return matches[0] + 1
    return None


def _parse_page_number(text: str, spec: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise PageSpecError(f"Invalid page number {text!r} in page spec {spec!r}")
    return int(text)

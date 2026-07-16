"""pdfx — PDF extraction toolkit: JSON-first library and CLI."""

from pdfx.pages import PageSpecError, parse_page_labels, parse_pages

__version__ = "0.1.0"

__all__ = ["PageSpecError", "parse_page_labels", "parse_pages", "__version__"]

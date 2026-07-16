"""Pure extraction functions. No printing, no CLI concerns.

All functions accept a file path plus parameters and return pydantic models.
Page numbers are 1-based throughout the public API.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pdfplumber
from pypdf import PasswordType, PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import Destination

from pdfx.models import (
    DocumentIndex,
    DocumentMetadata,
    ImageInfo,
    OutlineItem,
    PageSummary,
    PageText,
    RenderedPage,
    Table,
)
from pdfx.pages import PageSpec, parse_page_labels, parse_pages

POPPLER_HINT = (
    "poppler is required for page rendering. Install it with "
    "'apt install poppler-utils' (Linux), 'brew install poppler' (macOS), or "
    "'winget install oschwartz10612.Poppler' (Windows); alternatively set "
    "PDFX_POPPLER_PATH to poppler's bin directory."
)


class PdfxError(Exception):
    """Base class for pdfx errors."""


class InvalidPdfError(PdfxError):
    """The file is not a readable PDF."""


class PasswordError(PdfxError):
    """The PDF is encrypted and the password is missing or wrong."""


class PopplerNotFoundError(PdfxError):
    """poppler binaries are required for rendering but were not found."""


def _open_reader(path: Path, password: str | None) -> PdfReader:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    try:
        reader = PdfReader(path)
    except PyPdfError as exc:
        raise InvalidPdfError(f"Not a valid PDF: {path} ({exc})") from exc
    if reader.is_encrypted:
        if password is None:
            raise PasswordError(f"{path} is encrypted; a password is required")
        if reader.decrypt(password) == PasswordType.NOT_DECRYPTED:
            raise PasswordError(f"Wrong password for {path}")
    return reader


def get_page_labels(path: Path, password: str | None = None) -> list[str] | None:
    """The document's page labels (one per physical page), or None if the PDF
    does not define a /PageLabels table."""
    return _page_labels(_open_reader(path, password))


def _page_labels(reader: PdfReader) -> list[str] | None:
    try:
        if "/PageLabels" not in reader.trailer["/Root"]:
            return None
        return list(reader.page_labels)
    except Exception:  # malformed catalog/labels tree: treat as unlabeled
        return None


def _resolve_pages(
    reader: PdfReader, pages: PageSpec, physical: bool
) -> tuple[list[int], list[str] | None]:
    """Page spec -> (physical page numbers, page labels). The spec is matched
    against the PDF's page labels when they exist unless physical=True; labels
    are returned either way so results can report both numbering schemes."""
    labels = _page_labels(reader)
    if not physical and labels is not None:
        return parse_page_labels(pages, labels), labels
    return parse_pages(pages, len(reader.pages)), labels


def _label_for(labels: list[str] | None, physical_page: int) -> str | None:
    return labels[physical_page - 1] if labels else None


def page_stem(physical_page: int, labeled_page: str | None = None) -> str:
    """Base file name for a page's outputs: 'page0007', or when the document has
    labels 'page0030_pp0007' — label first, since users think in labels."""
    if labeled_page is None:
        return f"page{physical_page:04d}"
    if labeled_page.isdigit():
        token = f"{int(labeled_page):04d}"
    else:
        token = re.sub(r"[^A-Za-z0-9._-]", "_", labeled_page)
    return f"page{token}_pp{physical_page:04d}"


def get_index(path: Path, password: str | None = None) -> DocumentIndex:
    """Document metadata, outline/bookmark tree, and per-page summary."""
    reader = _open_reader(path, password)
    meta = reader.metadata
    metadata = DocumentMetadata()
    if meta is not None:
        metadata = DocumentMetadata(
            title=meta.title,
            author=meta.author,
            subject=meta.subject,
            creator=meta.creator,
            producer=meta.producer,
            creation_date=_safe_date(meta, "creation_date"),
            modification_date=_safe_date(meta, "modification_date"),
        )
    labels = _page_labels(reader)
    pages = [
        PageSummary(
            physical_page=i,
            labeled_page=_label_for(labels, i),
            width=float(page.mediabox.width),
            height=float(page.mediabox.height),
            rotation=page.rotation or 0,
            has_text=bool((page.extract_text() or "").strip()),
        )
        for i, page in enumerate(reader.pages, start=1)
    ]
    return DocumentIndex(
        path=str(path),
        page_count=len(reader.pages),
        has_page_labels=labels is not None,
        metadata=metadata,
        outline=_convert_outline(reader, reader.outline, labels),
        pages=pages,
    )


def get_text(
    path: Path,
    pages: PageSpec = "all",
    layout: bool = False,
    password: str | None = None,
    physical: bool = False,
) -> list[PageText]:
    """Extract text per page. layout=True uses pdfplumber's layout-aware extraction."""
    reader = _open_reader(path, password)
    numbers, labels = _resolve_pages(reader, pages, physical)
    results: list[PageText] = []
    if layout:
        with pdfplumber.open(path, password=password) as pdf:
            for n in numbers:
                text = pdf.pages[n - 1].extract_text(layout=True) or ""
                results.append(
                    PageText(
                        physical_page=n,
                        labeled_page=_label_for(labels, n),
                        text=text,
                        has_text=bool(text.strip()),
                    )
                )
    else:
        for n in numbers:
            text = reader.pages[n - 1].extract_text() or ""
            results.append(
                PageText(
                    physical_page=n,
                    labeled_page=_label_for(labels, n),
                    text=text,
                    has_text=bool(text.strip()),
                )
            )
    return results


def get_tables(
    path: Path,
    pages: PageSpec = "all",
    password: str | None = None,
    physical: bool = False,
) -> list[Table]:
    """Extract tables via pdfplumber. rows is a list of rows of cell strings (or None)."""
    reader = _open_reader(path, password)
    numbers, labels = _resolve_pages(reader, pages, physical)
    results: list[Table] = []
    with pdfplumber.open(path, password=password) as pdf:
        for n in numbers:
            for i, rows in enumerate(pdf.pages[n - 1].extract_tables()):
                results.append(
                    Table(
                        physical_page=n,
                        labeled_page=_label_for(labels, n),
                        index=i,
                        rows=rows,
                    )
                )
    return results


def get_images(
    path: Path,
    pages: PageSpec = "all",
    out_dir: Path | None = None,
    password: str | None = None,
    physical: bool = False,
) -> list[ImageInfo]:
    """Embedded images. Saves files to out_dir if given, otherwise metadata only."""
    reader = _open_reader(path, password)
    numbers, labels = _resolve_pages(reader, pages, physical)
    results: list[ImageInfo] = []
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    for n in numbers:
        label = _label_for(labels, n)
        for i, image in enumerate(reader.pages[n - 1].images):
            pil = image.image
            width, height = pil.size if pil is not None else (0, 0)
            fmt = pil.format.lower() if pil is not None and pil.format else None
            saved_path = None
            if out_dir is not None:
                target = out_dir / f"{page_stem(n, label)}_img{i:02d}_{Path(image.name).name}"
                target.write_bytes(image.data)
                saved_path = str(target)
            results.append(
                ImageInfo(
                    physical_page=n,
                    labeled_page=label,
                    index=i,
                    name=image.name,
                    width=width,
                    height=height,
                    format=fmt,
                    saved_path=saved_path,
                )
            )
    return results


def render_pages(
    path: Path,
    pages: PageSpec,
    out_dir: Path,
    dpi: int = 200,
    fmt: str = "png",
    password: str | None = None,
    poppler_path: str | Path | None = None,
    physical: bool = False,
) -> list[RenderedPage]:
    """Rasterize pages to image files in out_dir, named page_stem(...).<ext>
    (e.g. page0007.png, or page0030_pp0007.png when the document has labels).

    Requires poppler. poppler_path (or the PDFX_POPPLER_PATH environment
    variable) points at poppler's bin directory when it is not on PATH.
    """
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFInfoNotInstalledError

    reader = _open_reader(path, password)
    numbers, labels = _resolve_pages(reader, pages, physical)
    fmt = fmt.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    ext = "jpg" if fmt == "jpeg" else fmt
    poppler_path = poppler_path or os.environ.get("PDFX_POPPLER_PATH") or None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[RenderedPage] = []
    try:
        for start, end in _contiguous_runs(numbers):
            images = convert_from_path(
                str(path),
                dpi=dpi,
                fmt=fmt,
                first_page=start,
                last_page=end,
                userpw=password,
                poppler_path=str(poppler_path) if poppler_path else None,
            )
            for offset, image in enumerate(images):
                n = start + offset
                label = _label_for(labels, n)
                target = out_dir / f"{page_stem(n, label)}.{ext}"
                image.save(target)
                results.append(
                    RenderedPage(
                        physical_page=n,
                        labeled_page=label,
                        path=str(target),
                        width=image.width,
                        height=image.height,
                        dpi=dpi,
                    )
                )
    except PDFInfoNotInstalledError as exc:
        raise PopplerNotFoundError(POPPLER_HINT) from exc
    return results


def _safe_date(meta, attr: str) -> str | None:
    try:
        value = getattr(meta, attr)
    except Exception:  # malformed date strings raise from pypdf's parser
        return None
    return value.isoformat() if value is not None else None


def _convert_outline(
    reader: PdfReader, items, labels: list[str] | None = None
) -> list[OutlineItem]:
    """Convert pypdf's outline (Destinations with nested lists) to OutlineItems."""
    result: list[OutlineItem] = []
    for item in items:
        if isinstance(item, list):
            children = _convert_outline(reader, item, labels)
            if result:
                result[-1].children.extend(children)
            else:
                result.extend(children)
        elif isinstance(item, Destination):
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                page = None
            result.append(
                OutlineItem(
                    title=str(item.title),
                    physical_page=page,
                    labeled_page=_label_for(labels, page) if page else None,
                )
            )
    return result


def _contiguous_runs(numbers: list[int]) -> list[tuple[int, int]]:
    """Group a sorted list of page numbers into inclusive contiguous (start, end) runs."""
    runs: list[tuple[int, int]] = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs

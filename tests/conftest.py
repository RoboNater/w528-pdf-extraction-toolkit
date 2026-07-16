"""Shared fixtures: small test PDFs generated programmatically with reportlab."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import SimpleDocTemplate, TableStyle
from reportlab.platypus import Table as RLTable

ENCRYPTED_PASSWORD = "secret"

TABLE_DATA = [
    ["Name", "Qty", "Price"],
    ["Apple", "3", "1.20"],
    ["Banana", "6", "0.50"],
]

IMAGE_SIZE = (64, 48)


def poppler_available() -> bool:
    if shutil.which("pdftoppm"):
        return True
    poppler_path = os.environ.get("PDFX_POPPLER_PATH")
    return bool(poppler_path and (Path(poppler_path) / "pdftoppm.exe").exists())


requires_poppler = pytest.mark.skipif(
    not poppler_available(), reason="poppler (pdftoppm) not installed"
)


@pytest.fixture(scope="session")
def pdf_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("pdfs")


@pytest.fixture(scope="session")
def text_pdf(pdf_dir: Path) -> Path:
    """Three text pages with metadata and a nested outline."""
    path = pdf_dir / "text.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.setTitle("Test Document")
    c.setAuthor("pdfx tests")
    for i, chapter in enumerate(["Chapter One", "Chapter Two", "Chapter Three"], start=1):
        key = f"ch{i}"
        c.bookmarkPage(key)
        c.addOutlineEntry(chapter, key, level=0)
        if i == 2:
            c.bookmarkPage("sec21")
            c.addOutlineEntry("Section 2.1", "sec21", level=1)
        c.drawString(72, 720, chapter)
        c.drawString(72, 700, f"This is page {i} of the test document.")
        c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def table_pdf(pdf_dir: Path) -> Path:
    """One page containing a ruled 3x3 table."""
    path = pdf_dir / "table.pdf"
    table = RLTable(TABLE_DATA)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(path), pagesize=letter).build([table])
    return path


@pytest.fixture(scope="session")
def image_pdf(pdf_dir: Path) -> Path:
    """One page with a single embedded raster image."""
    path = pdf_dir / "image.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "Image page")
    img = Image.new("RGB", IMAGE_SIZE, (200, 30, 30))
    c.drawImage(ImageReader(img), 72, 600, width=IMAGE_SIZE[0], height=IMAGE_SIZE[1])
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def blank_pdf(pdf_dir: Path) -> Path:
    """One page with no text content."""
    path = pdf_dir / "blank.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session")
def encrypted_pdf(pdf_dir: Path, text_pdf: Path) -> Path:
    path = pdf_dir / "encrypted.pdf"
    writer = PdfWriter(clone_from=str(text_pdf))
    writer.encrypt(ENCRYPTED_PASSWORD)
    with open(path, "wb") as f:
        writer.write(f)
    return path


LABELED_PDF_LABELS = ["cover", "FM1", "FM2", "FM3", "i", "ii", "iii", "1", "2", "3"]


def _with_decimal_labels(src: Path, dst: Path, start: int) -> Path:
    """Copy a PDF, labeling all pages with decimal numbers starting at `start`."""
    writer = PdfWriter(clone_from=str(src))
    writer.set_page_label(0, len(writer.pages) - 1, style="/D", start=start)
    with open(dst, "wb") as f:
        writer.write(f)
    return dst


@pytest.fixture(scope="session")
def labeled_image_pdf(pdf_dir: Path, image_pdf: Path) -> Path:
    """image_pdf with its single page labeled '30'."""
    return _with_decimal_labels(image_pdf, pdf_dir / "labeled_image.pdf", 30)


@pytest.fixture(scope="session")
def labeled_table_pdf(pdf_dir: Path, table_pdf: Path) -> Path:
    """table_pdf with its single page labeled '30'."""
    return _with_decimal_labels(table_pdf, pdf_dir / "labeled_table.pdf", 30)


@pytest.fixture(scope="session")
def labeled_pdf(pdf_dir: Path) -> Path:
    """Ten text pages with ebook-style page labels: cover, FM1-FM3, i-iii, 1-3.
    Each physical page N contains the text 'Physical page N'."""
    source = pdf_dir / "labeled_source.pdf"
    c = rl_canvas.Canvas(str(source), pagesize=letter)
    for n in range(1, 11):
        c.drawString(72, 720, f"Physical page {n}")
        c.showPage()
    c.save()
    writer = PdfWriter(clone_from=str(source))
    writer.set_page_label(0, 0, prefix="cover")
    writer.set_page_label(1, 3, prefix="FM", style="/D")
    writer.set_page_label(4, 6, style="/r")
    writer.set_page_label(7, 9, style="/D")
    path = pdf_dir / "labeled.pdf"
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture(scope="session")
def not_a_pdf(pdf_dir: Path) -> Path:
    path = pdf_dir / "fake.pdf"
    path.write_text("this is not a pdf", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def unicode_pdf(pdf_dir: Path) -> Path:
    """One page with non-ASCII text, to verify CLI output is UTF-8 regardless of
    the console code page. (Characters stay within cp1252, which is all the
    standard PDF fonts can encode.)"""
    path = pdf_dir / "unicode.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "Café — Über naïve résumé")
    c.showPage()
    c.save()
    return path

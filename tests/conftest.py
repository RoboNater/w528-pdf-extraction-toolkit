"""Shared fixtures: small test PDFs generated programmatically with reportlab,
and a fake OpenAI-compatible VLM endpoint for the AI-pass and OCR tests."""

from __future__ import annotations

import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def _has_poppler_tool(name: str) -> bool:
    if shutil.which(name):
        return True
    poppler_path = os.environ.get("PDFX_POPPLER_PATH")
    return bool(poppler_path and shutil.which(name, path=poppler_path))


def poppler_available() -> bool:
    return _has_poppler_tool("pdftoppm") and _has_poppler_tool("pdftotext")


requires_poppler = pytest.mark.skipif(
    not poppler_available(), reason="poppler (pdftoppm/pdftotext) not installed"
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


KERNED_SENTENCE = (
    "Whether you are looking for a quick reference or a deep dive this guide has you covered"
)


def _kerned_pdf_bytes(gap: int = 120, font_size: int = 10) -> bytes:
    """Hand-written PDF whose word gaps are TJ kerning offsets (thousandths of
    an em), with no space glyphs anywhere. This is the shape of PDF behind
    issue #1: pypdf and pdfplumber run the words together, while poppler's
    pdftotext segments them correctly. gap=120 sits below both pypdf's
    space-inference threshold and pdfplumber's default x_tolerance."""
    words = KERNED_SENTENCE.split()
    lines = [words[i : i + 6] for i in range(0, len(words), 6)]
    ops = ["BT", f"/F1 {font_size} Tf", "72 720 Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append(f"0 -{font_size + 4} Td")
        tj = f" -{gap} ".join(f"({w})" for w in line)
        ops.append(f"[{tj}] TJ")
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_pos,
    )
    return bytes(out)


@pytest.fixture(scope="session")
def kerned_pdf(pdf_dir: Path) -> Path:
    """One page where word gaps are kerning offsets, not space characters."""
    path = pdf_dir / "kerned.pdf"
    path.write_bytes(_kerned_pdf_bytes())
    return path


@pytest.fixture(scope="session")
def not_a_pdf(pdf_dir: Path) -> Path:
    path = pdf_dir / "fake.pdf"
    path.write_text("this is not a pdf", encoding="utf-8")
    return path


# --- fake OpenAI-compatible VLM endpoint (shared by markdown and OCR tests) ---


class FakeVlm:
    """Records chat.completions requests; serves queued (status, content)
    responses, then the default content."""

    def __init__(self):
        self.requests: list[dict] = []
        self.headers: list[dict] = []  # per-request headers, aligned with requests
        self.queue: list[tuple[int, str]] = []
        self.content = "Refined."
        self.base_url = ""
        self._lock = threading.Lock()

    def next_response(self) -> tuple[int, str]:
        with self._lock:
            return self.queue.pop(0) if self.queue else (200, self.content)


@pytest.fixture()
def fake_vlm():
    state = FakeVlm()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with state._lock:
                state.requests.append(payload)
                state.headers.append({k.lower(): v for k, v in self.headers.items()})
            status, content = state.next_response()
            if status != 200:
                body = json.dumps({"error": {"message": "boom", "type": "bad_request"}})
            else:
                body = json.dumps(
                    {
                        "id": "chatcmpl-test",
                        "object": "chat.completion",
                        "created": 0,
                        "model": payload.get("model", "fake"),
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": content},
                            }
                        ],
                    }
                )
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    thread.join()


@pytest.fixture()
def vlm_env(monkeypatch):
    for var in (
        "PDFX_VLM_MODEL",
        "PDFX_VLM_BASE_URL",
        "PDFX_VLM_ORG",
        "PDFX_VLM_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",  # SDK's own org fallback; clear so tests are deterministic
        "OPENAI_ORGANIZATION",
    ):
        monkeypatch.delenv(var, raising=False)


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

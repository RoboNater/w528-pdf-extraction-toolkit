"""VLM OCR tests (pdfx.ocr) and the --ocr stage of pdfx markdown.

Like the markdown AI-pass tests, everything runs against the fake
OpenAI-compatible endpoint from conftest — no network, no real key. Tests that
render pages require poppler.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_poppler
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from pdfx.markdown import to_markdown
from pdfx.ocr import (
    MIN_TRANSCRIPTION_CHARS,
    _accept_response,
    _write_validation_pdf,
    transcribe_pages,
    validate_ocr,
)
from pdfx.vlm_utils import VlmError

TRANSCRIPTION = "Scanned page transcription with enough characters to pass validation."


@pytest.fixture(scope="module")
def scanned_pdf(pdf_dir: Path) -> Path:
    """Two pages: page 1 has a text layer, page 2 carries text only inside an
    embedded image (no text layer) — the scanned-page shape OCR exists for."""
    path = pdf_dir / "scanned.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "Page one has a normal text layer.")
    c.showPage()
    image = Image.new("RGB", (1224, 1584), "white")
    ImageDraw.Draw(image).text((150, 150), "IMAGE ONLY TEXT", fill="black")
    c.drawImage(ImageReader(image), 0, 0, width=letter[0], height=letter[1])
    c.showPage()
    c.save()
    return path


# --- response validation ---


def test_accept_response_validation():
    good = "x" * MIN_TRANSCRIPTION_CHARS
    assert _accept_response(good) == (good, "")
    assert _accept_response(f"```\n{good}\n```") == (good, "")  # fence stripped
    assert _accept_response(None)[0] is None
    assert _accept_response("   ")[0] is None
    accepted, reason = _accept_response("too short")
    assert accepted is None and "short" in reason


# --- transcribe_pages ---


def test_missing_model(scanned_pdf, vlm_env):
    with pytest.raises(VlmError, match="model"):
        transcribe_pages(scanned_pdf)


def test_missing_key(scanned_pdf, vlm_env):
    with pytest.raises(VlmError, match="API key"):
        transcribe_pages(scanned_pdf, model="fake-vlm")


def test_only_scanned_pages_transcribed(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = TRANSCRIPTION
    result = transcribe_pages(
        scanned_pdf, model="fake-vlm", base_url=fake_vlm.base_url, cache_dir=tmp_path
    )
    assert [p.physical_page for p in result] == [2]  # page 1 has text: not OCR'd
    assert result[0].has_text and result[0].text == TRANSCRIPTION
    assert len(fake_vlm.requests) == 1
    content = fake_vlm.requests[0]["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_no_scanned_pages_no_requests(text_pdf, fake_vlm, vlm_env):
    result = transcribe_pages(text_pdf, model="fake-vlm", base_url=fake_vlm.base_url)
    assert result == []
    assert fake_vlm.requests == []  # no render, no API traffic


@requires_poppler
def test_failure_keeps_placeholder_and_warns(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.queue = [(400, "")]
    warnings: list[str] = []
    result = transcribe_pages(
        scanned_pdf,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
        warnings=warnings,
    )
    assert result[0].has_text is False and result[0].text == ""
    assert len(warnings) == 1 and "OCR failed" in warnings[0]


@requires_poppler
def test_short_response_rejected(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = "tiny"
    warnings: list[str] = []
    result = transcribe_pages(
        scanned_pdf,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
        warnings=warnings,
    )
    assert result[0].has_text is False
    assert len(warnings) == 1 and "rejected" in warnings[0]


@requires_poppler
def test_second_run_served_from_cache(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = TRANSCRIPTION
    args = dict(model="fake-vlm", base_url=fake_vlm.base_url, cache_dir=tmp_path)
    transcribe_pages(scanned_pdf, **args)
    assert len(fake_vlm.requests) == 1
    result = transcribe_pages(scanned_pdf, **args)
    assert len(fake_vlm.requests) == 1  # no new API calls
    assert result[0].text == TRANSCRIPTION


# --- markdown --ocr integration ---


def test_markdown_ocr_requires_ai(scanned_pdf, vlm_env):
    with pytest.raises(VlmError, match="--ai"):
        to_markdown(scanned_pdf, engine="pypdf", ocr=True)


@requires_poppler
def test_markdown_ocr_replaces_placeholder(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = TRANSCRIPTION
    result = to_markdown(
        scanned_pdf,
        ai=True,
        ocr=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    page1, page2 = result.pages
    assert page1.ai_refined and not page1.ocr_transcribed
    assert page2.ocr_transcribed and not page2.ai_refined
    assert page2.has_text and page2.markdown == TRANSCRIPTION
    assert "no text layer" not in result.markdown
    assert result.warnings == []


@requires_poppler
def test_markdown_ocr_failure_keeps_placeholder(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = TRANSCRIPTION
    fake_vlm.queue = [(200, TRANSCRIPTION), (400, "")]  # page 1 refine ok, page 2 OCR fails
    result = to_markdown(
        scanned_pdf,
        ai=True,
        ocr=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    page2 = result.pages[1]
    assert not page2.ocr_transcribed and not page2.has_text
    assert "no text layer" in result.markdown
    assert len(result.warnings) == 1 and "OCR failed" in result.warnings[0]


@requires_poppler
def test_markdown_without_ocr_keeps_placeholder(scanned_pdf, fake_vlm, vlm_env, tmp_path):
    result = to_markdown(
        scanned_pdf,
        ai=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    assert "no text layer" in result.markdown
    assert len(fake_vlm.requests) == 1  # only the page-1 refinement


# --- validate-vlm-ocr ---


def test_validation_pdf_shape(tmp_path):
    """The synthetic document must have a text layer on page 1 only — this is
    the property that makes the validation exercise OCR at all."""
    pdf = tmp_path / "validation.pdf"
    _write_validation_pdf(pdf)
    reader = PdfReader(pdf)
    assert len(reader.pages) == 3
    layered = [bool((p.extract_text() or "").strip()) for p in reader.pages]
    assert layered == [True, False, False]


@requires_poppler
def test_validate_ocr_pass(fake_vlm, vlm_env):
    from pdfx.ocr import VALIDATION_LAYOUT_LINES, VALIDATION_PROSE

    # jobs=1 processes pages in order: prose page 2 first, layout page 3 second.
    fake_vlm.queue = [(200, VALIDATION_PROSE), (200, "\n".join(VALIDATION_LAYOUT_LINES))]
    report = validate_ocr(model="fake-vlm", base_url=fake_vlm.base_url)
    assert report["overall_status"] == "pass"
    statuses = {p["physical_page"]: p["status"] for p in report["pages"]}
    assert statuses == {1: "skipped", 2: "ok", 3: "ok"}
    assert report["pages"][1]["similarity"] == 100.0
    assert len(fake_vlm.requests) == 2  # page 1 skipped: text layer present


@requires_poppler
def test_validate_ocr_warn_on_poor_transcription(fake_vlm, vlm_env):
    from pdfx.ocr import VALIDATION_PROSE

    fake_vlm.queue = [
        (200, VALIDATION_PROSE),
        (200, "Entirely unrelated text that is long enough to be accepted."),
    ]
    report = validate_ocr(model="fake-vlm", base_url=fake_vlm.base_url)
    assert report["overall_status"] == "warn"
    assert report["pages"][2]["status"] == "warn"
    assert report["pages"][2]["similarity"] < 70


@requires_poppler
def test_validate_ocr_fail_when_no_transcription(fake_vlm, vlm_env):
    fake_vlm.queue = [(400, ""), (400, "")]
    report = validate_ocr(model="fake-vlm", base_url=fake_vlm.base_url)
    assert report["overall_status"] == "fail"
    assert all(p["status"] == "fail" for p in report["pages"][1:])
    assert len(report["warnings"]) == 2

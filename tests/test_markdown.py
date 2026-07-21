"""Markdown conversion tests.

Stage 2 tests run against a fake OpenAI-compatible endpoint (the fake_vlm
fixture in conftest) served from a local thread — no network, no real API key.
They render pages, so they require poppler like the render tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TABLE_DATA, requires_poppler
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, TableStyle
from reportlab.platypus import Table as RLTable

from pdfx.markdown import VlmError, _accept_response, _pipe_table, to_markdown


@pytest.fixture(scope="module")
def mixed_pdf(pdf_dir: Path) -> Path:
    """One page with prose above and below a ruled table."""
    path = pdf_dir / "mixed.pdf"
    styles = getSampleStyleSheet()
    table = RLTable(TABLE_DATA)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(path), pagesize=letter).build(
        [
            Paragraph("Intro paragraph above the table.", styles["Normal"]),
            table,
            Paragraph("Closing text below the table.", styles["Normal"]),
        ]
    )
    return path


@pytest.fixture(scope="module")
def long_pdf(pdf_dir: Path) -> Path:
    """One page with well over 200 characters of text, for the length check."""
    path = pdf_dir / "long.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    for i in range(12):
        c.drawString(72, 720 - 16 * i, f"Line {i}: " + "lorem ipsum dolor sit amet " * 3)
    c.showPage()
    c.save()
    return path


@pytest.fixture(scope="module")
def outlined_pdf(pdf_dir: Path) -> Path:
    """Two pages with a two-level outline whose titles are drawn on their
    destination pages: 'Chapter Alpha' (level 0, page 1) and 'Background
    Methods.' (level 1, page 2 — trailing dot exercises the fuzzy match)."""
    path = pdf_dir / "outlined.pdf"
    c = rl_canvas.Canvas(str(path), pagesize=letter)
    c.bookmarkPage("ch1")
    c.addOutlineEntry("Chapter Alpha", "ch1", level=0)
    c.drawString(72, 720, "Chapter Alpha")
    c.drawString(72, 700, "Opening prose on the first page.")
    c.showPage()
    c.bookmarkPage("sec11")
    c.addOutlineEntry("Background Methods", "sec11", level=1)
    c.drawString(72, 720, "Background Methods.")
    c.drawString(72, 700, "Detail prose on the second page.")
    c.showPage()
    c.save()
    return path


# --- stage 1: programmatic pass ---


def test_table_page_dedup_and_flow(mixed_pdf):
    result = to_markdown(mixed_pdf)
    body = result.pages[0].markdown
    assert "| Name | Qty | Price |" in body
    assert "| Apple | 3 | 1.20 |" in body
    assert body.count("Apple") == 1  # table rows cropped out of the prose
    intro, table_pos, closing = (
        body.index("Intro paragraph"),
        body.index("| Name |"),
        body.index("Closing text"),
    )
    assert intro < table_pos < closing  # table sits in flow position


def test_delimiters_and_labels(labeled_table_pdf):
    result = to_markdown(labeled_table_pdf)
    assert result.pages[0].labeled_page == "30"
    assert "<!-- page 30 (pp 1) -->" in result.markdown


def test_text_page(text_pdf):
    result = to_markdown(text_pdf, engine="pypdf")
    assert len(result.pages) == 3
    assert "Chapter Two" in result.pages[1].markdown
    assert "<!-- page 2 -->" in result.markdown
    assert not result.pages[0].ai_refined


def test_blank_page_placeholder(blank_pdf):
    result = to_markdown(blank_pdf, engine="pypdf")
    assert result.pages[0].has_text is False
    assert result.pages[0].markdown == ""
    assert "<!-- page 1: no text layer -->" in result.markdown


def test_image_links(image_pdf, tmp_path):
    images_dir = tmp_path / "media"
    result = to_markdown(image_pdf, engine="pypdf", images_dir=images_dir)
    body = result.pages[0].markdown
    assert "![" in body and "](media/" in body
    linked = body.split("](media/", 1)[1].split(")", 1)[0]
    assert (images_dir / linked).is_file()


def test_images_skipped_without_dir(image_pdf):
    result = to_markdown(image_pdf, engine="pypdf")
    assert "![" not in result.pages[0].markdown


def test_pipe_table_escaping_and_padding():
    md = _pipe_table([["a|b", None], ["multi\nline", "x", "extra"]])
    lines = md.split("\n")
    assert lines[0] == "| a\\|b |  |  |"
    assert lines[1] == "| --- | --- | --- |"  # padded to the widest row
    assert lines[2] == "| multi<br>line | x | extra |"


def test_accept_response_validation():
    assert _accept_response("draft", "Fixed.") == ("Fixed.", "")
    assert _accept_response("draft", "```markdown\nFixed.\n```") == ("Fixed.", "")
    assert _accept_response("draft", None)[0] is None
    assert _accept_response("draft", "   ")[0] is None
    long_draft = "x" * 400
    accepted, reason = _accept_response(long_draft, "tiny")
    assert accepted is None and "short" in reason
    assert _accept_response("short draft", "ok")[0] == "ok"  # ratio check needs a long draft


# --- outline-aware heading options ---


def test_outline_headings_tagged_by_depth(outlined_pdf):
    result = to_markdown(outlined_pdf, engine="pypdf", outline_headings=True)
    assert "# Chapter Alpha" in result.pages[0].markdown
    assert "Opening prose" in result.pages[0].markdown
    assert "## Background Methods." in result.pages[1].markdown  # fuzzy: trailing dot on page


def test_outline_headings_default_off(outlined_pdf):
    result = to_markdown(outlined_pdf, engine="pypdf")
    assert "#" not in result.markdown.replace("<!--", "")  # delimiters aside, no headings


def test_outline_headings_unmatched_title_untouched(text_pdf):
    # text_pdf bookmarks 'Section 2.1' on page 2 but never draws that text
    result = to_markdown(text_pdf, engine="pypdf", outline_headings=True)
    assert "# Chapter Two" in result.pages[1].markdown
    assert "Section 2.1" not in result.pages[1].markdown


def test_outline_headings_noop_without_outline(table_pdf):
    with_opt = to_markdown(table_pdf, outline_headings=True)
    without = to_markdown(table_pdf)
    assert with_opt.markdown == without.markdown


def test_heading_match_is_conservative():
    from pdfx.markdown import _heading_match

    assert _heading_match("Background Methods.", "Background Methods")
    assert _heading_match("  background   methods ", "Background Methods")
    assert not _heading_match("Background", "Background Methods")  # partial line
    assert not _heading_match(
        "Background Methods are described at length in this paragraph", "Background Methods"
    )


# --- stage 2: AI review pass against a fake OpenAI-compatible endpoint ---


@requires_poppler
def test_ai_refines_pages(text_pdf, fake_vlm, vlm_env, tmp_path):
    result = to_markdown(
        text_pdf,
        ai=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        jobs=2,
        cache_dir=tmp_path,
    )
    assert result.warnings == []
    assert all(p.ai_refined for p in result.pages)
    assert all(p.markdown == "Refined." for p in result.pages)
    assert len(fake_vlm.requests) == 3
    user = fake_vlm.requests[0]["messages"][1]["content"]
    drafts = " ".join(r["messages"][1]["content"][0]["text"] for r in fake_vlm.requests)
    assert "This is page 1" in drafts  # request carries the draft
    assert user[1]["image_url"]["url"].startswith("data:image/png;base64,")


@requires_poppler
def test_ai_env_config_and_keyless_local_server(text_pdf, fake_vlm, vlm_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PDFX_VLM_MODEL", "fake-vlm")
    monkeypatch.setenv("PDFX_VLM_BASE_URL", fake_vlm.base_url)
    result = to_markdown(text_pdf, pages="1", ai=True, cache_dir=tmp_path)
    assert result.pages[0].ai_refined


def test_ai_missing_model(text_pdf, vlm_env):
    with pytest.raises(VlmError, match="model"):
        to_markdown(text_pdf, ai=True, engine="pypdf")


def test_ai_missing_key(text_pdf, vlm_env):
    with pytest.raises(VlmError, match="API key"):
        to_markdown(text_pdf, ai=True, model="fake-vlm", engine="pypdf")


@requires_poppler
def test_ai_fence_stripped(text_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = "```markdown\nClean page.\n```"
    result = to_markdown(
        text_pdf,
        pages="1",
        ai=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    assert result.pages[0].markdown == "Clean page."


@requires_poppler
def test_ai_short_response_rejected(long_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.content = "tiny"
    result = to_markdown(
        long_pdf, ai=True, model="fake-vlm", base_url=fake_vlm.base_url, cache_dir=tmp_path
    )
    assert not result.pages[0].ai_refined
    assert "Line 0" in result.pages[0].markdown  # programmatic draft kept
    assert len(result.warnings) == 1 and "short" in result.warnings[0]


@requires_poppler
def test_ai_api_error_falls_back(text_pdf, fake_vlm, vlm_env, tmp_path):
    fake_vlm.queue = [(400, "")]
    result = to_markdown(
        text_pdf,
        pages="1",
        ai=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    assert not result.pages[0].ai_refined
    assert "Chapter One" in result.pages[0].markdown
    assert len(result.warnings) == 1 and "AI pass failed" in result.warnings[0]


@requires_poppler
def test_ai_second_run_served_from_cache(text_pdf, fake_vlm, vlm_env, tmp_path):
    args = dict(ai=True, model="fake-vlm", base_url=fake_vlm.base_url, cache_dir=tmp_path)
    to_markdown(text_pdf, **args)
    assert len(fake_vlm.requests) == 3
    result = to_markdown(text_pdf, **args)
    assert len(fake_vlm.requests) == 3  # no new API calls
    assert all(p.ai_refined and p.markdown == "Refined." for p in result.pages)


@requires_poppler
def test_ai_no_cache_flag(text_pdf, fake_vlm, vlm_env, tmp_path):
    args = dict(
        pages="1",
        ai=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
        use_cache=False,
    )
    to_markdown(text_pdf, **args)
    to_markdown(text_pdf, **args)
    assert len(fake_vlm.requests) == 2


@requires_poppler
def test_outline_context_in_request(text_pdf, fake_vlm, vlm_env, tmp_path):
    result = to_markdown(
        text_pdf,
        ai=True,
        outline_context=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    assert all(p.ai_refined for p in result.pages)
    texts = [r["messages"][1]["content"][0]["text"] for r in fake_vlm.requests]
    page2 = next(t for t in texts if "This is page 2" in t)
    assert "Section path at this page: Chapter Two" in page2
    assert "Section 2.1 (level 2)" in page2  # on-page entries listed with levels


@requires_poppler
def test_outline_context_changes_cache_key(text_pdf, fake_vlm, vlm_env, tmp_path):
    args = dict(
        pages="1", ai=True, model="fake-vlm", base_url=fake_vlm.base_url, cache_dir=tmp_path
    )
    to_markdown(text_pdf, **args)
    to_markdown(text_pdf, outline_context=True, **args)  # different prompt, no stale hit
    assert len(fake_vlm.requests) == 2


def test_outline_context_requires_ai(text_pdf, vlm_env):
    with pytest.raises(VlmError, match="--ai"):
        to_markdown(text_pdf, engine="pypdf", outline_context=True)


def test_ai_skips_pages_without_text(blank_pdf, fake_vlm, vlm_env, tmp_path):
    result = to_markdown(
        blank_pdf,
        engine="pypdf",
        ai=True,
        model="fake-vlm",
        base_url=fake_vlm.base_url,
        cache_dir=tmp_path,
    )
    assert fake_vlm.requests == []  # nothing to review, no render/API work
    assert "no text layer" in result.markdown

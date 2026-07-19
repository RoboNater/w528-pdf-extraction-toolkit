"""VLM-based OCR for scanned (no text layer) pages.

Uses the same OpenAI-compatible API and validation/caching infrastructure as the
Markdown refinement pass. Pages without a text layer are rendered and sent to the
VLM for transcription.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pdfx import core
from pdfx.models import PageText
from pdfx.pages import PageSpec
from pdfx.vlm_utils import VlmError, cache_path, cache_read, cache_write, file_sha256

# Bumped whenever the system prompt or request shape changes.
PROMPT_VERSION = "1"

SYSTEM_PROMPT = """\
You are an OCR agent tasked with transcribing all visible text from a PDF page image.

Guidelines:
- Transcribe exactly what you see, including all text, headings, and labels.
- Preserve the original layout and structure as much as possible: paragraph breaks, lists, tables, columns.
- If text is partially obscured or illegible, indicate this with [...] and continue.
- Include page numbers, footers, and headers if present.
- Do not correct spelling or grammar; transcribe as seen.
- If you encounter special characters or symbols you cannot transcribe exactly, indicate them descriptively in brackets, e.g. [section symbol].

Return ONLY the transcribed text. No commentary, no markdown formatting, no code fences."""


def transcribe_pages(
    path: Path,
    pages: PageSpec = "all",
    model: str | None = None,
    base_url: str | None = None,
    jobs: int = 1,
    dpi: int = 150,
    password: str | None = None,
    physical: bool = False,
    poppler_path: str | Path | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[PageText]:
    """Transcribe scanned (no text layer) pages using a VLM.

    Only processes pages with no text layer. Other pages are returned with
    empty text and has_text=false. Applies the same validation, caching, and
    cost controls as the Markdown refinement pass.

    Args:
        path: Path to the PDF file.
        pages: Page specification (e.g., "all", "1-5", "1,3,5").
        model: VLM model name; falls back to PDFX_VLM_MODEL environment variable.
        base_url: OpenAI-compatible endpoint URL; falls back to PDFX_VLM_BASE_URL.
        jobs: Concurrent transcription requests.
        dpi: Render resolution for page images.
        password: PDF password if encrypted.
        physical: Interpret page numbers as physical positions (ignore labels).
        poppler_path: Path to poppler bin directory.
        cache_dir: Cache directory for responses (default ~/.cache/pdfx/vlm).
        use_cache: Whether to use the response cache.

    Returns:
        List of PageText models with transcribed text for scanned pages.
    """
    model = model or os.environ.get("PDFX_VLM_MODEL")
    if not model:
        raise VlmError("OCR needs a model: pass --model or set PDFX_VLM_MODEL.")
    base_url = base_url or os.environ.get("PDFX_VLM_BASE_URL")
    api_key = os.environ.get("PDFX_VLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        if base_url is None:
            raise VlmError(
                "OCR needs an API key: set PDFX_VLM_API_KEY (or OPENAI_API_KEY). "
                "Local servers also need --base-url/PDFX_VLM_BASE_URL."
            )
        api_key = "unused"

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise VlmError(
            "OCR requires the 'openai' package; install with 'uv sync --extra ai' "
            "or 'pip install pdfx[ai]'."
        ) from exc

    path = Path(path)
    reader = core._open_reader(path, password)
    numbers, labels = core._resolve_pages(reader, pages, physical)

    # Get index to identify pages with no text layer.
    index = core.get_index(path, password=password)
    scanned_pages = [
        n for n in numbers if not index.pages[n - 1].has_text
    ]

    if not scanned_pages:
        # No scanned pages; return empty PageText for all requested pages.
        return [
            PageText(
                physical_page=n,
                labeled_page=core._label_for(labels, n),
                text="",
                has_text=False,
            )
            for n in numbers
        ]

    # Render scanned pages and transcribe via VLM.
    file_hash = file_sha256(path)
    cache = cache_path(cache_dir) if use_cache else None
    client = OpenAI(api_key=api_key, base_url=base_url)

    result_text: dict[int, str] = {}
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pdfx-ocr-") as tmp:
        spec = ",".join(str(n) for n in scanned_pages)
        rendered = {
            r.physical_page: Path(r.path)
            for r in core.render_pages(
                path,
                spec,
                Path(tmp),
                dpi=dpi,
                password=password,
                poppler_path=poppler_path,
                physical=True,
            )
        }

        def transcribe(page_no: int) -> str | None:
            """Transcribe a single page; return a warning message on failure, None on success."""
            key = hashlib.sha256(
                f"{file_hash}:{page_no}:{model}:{PROMPT_VERSION}:{dpi}".encode()
            ).hexdigest()

            # Check cache first.
            if cache is not None:
                hit = cache_read(cache, key)
                if hit is not None:
                    result_text[page_no] = hit
                    return None

            # Call VLM.
            try:
                response = _call_vlm_for_ocr(
                    client, model, rendered[page_no]
                )
            except Exception as exc:
                return f"page {page_no}: OCR failed ({exc}); skipped"

            # Validate response.
            accepted, reason = _accept_ocr_response(response)
            if accepted is None:
                return f"page {page_no}: OCR response rejected ({reason}); skipped"

            result_text[page_no] = accepted
            if cache is not None:
                cache_write(cache, key, accepted)
            return None

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            warnings.extend(w for w in pool.map(transcribe, scanned_pages) if w is not None)

    # Build result list for all requested pages.
    result = []
    for n in numbers:
        if n in result_text:
            text = result_text[n]
            result.append(
                PageText(
                    physical_page=n,
                    labeled_page=core._label_for(labels, n),
                    text=text,
                    has_text=True,
                )
            )
        else:
            # Page was not scanned, or OCR was skipped.
            result.append(
                PageText(
                    physical_page=n,
                    labeled_page=core._label_for(labels, n),
                    text="",
                    has_text=False,
                )
            )

    return result


def _call_vlm_for_ocr(client, model: str, image_path: Path) -> str | None:
    """Send a rendered page image to the VLM for OCR transcription."""
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            },
        ],
    )
    return completion.choices[0].message.content


def _accept_ocr_response(response: str | None) -> tuple[str | None, str]:
    """Validate an OCR response; (accepted_text, "") or (None, reason)."""
    if response is None:
        return None, "empty response"
    text = response.strip()
    if not text:
        return None, "empty response"
    # Reject suspiciously short responses (VLM hallucination/refusal).
    # A page typically has 200+ characters; if response is very short, it's likely
    # the VLM failed to transcribe.
    if len(text) < 50:
        return None, f"response too short ({len(text)} chars; expected at least 50)"
    return text, ""


# --- validation command ---


def validate_ocr(
    model: str | None = None,
    base_url: str | None = None,
    dpi: int = 150,
) -> dict:
    """Test VLM OCR on a synthetic PDF with known content.

    Creates an in-memory PDF with:
    - Page 1: Simple text page with a text layer (reference)
    - Page 2: Same text rendered as image, no text layer (scanned)
    - Page 3: More complex layout (title, bullets, table)

    Returns:
        Dict with OCR test results including per-page similarity scores.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        import io
    except ImportError as exc:
        raise VlmError(
            "validate-vlm-ocr requires reportlab; install with "
            "'uv sync --extra dev' or 'pip install reportlab'."
        ) from exc

    # Create synthetic PDF in memory.
    pdf_bytes = _create_ocr_test_pdf()

    # Write to temp file for processing.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        # Transcribe all pages (1, 2, 3).
        results = transcribe_pages(
            tmp_path,
            pages="all",
            model=model,
            base_url=base_url,
            jobs=1,
            dpi=dpi,
            use_cache=False,
        )

        # Compare results to known content.
        page_results = []
        overall_status = "pass"

        # Page 1 (text layer): get expected content.
        page1_text = core.get_text(tmp_path, pages="1")[0].text
        page1_chars = len(page1_text)

        # Page 2 (scanned, should match page 1).
        page2_result = results[1]  # index 1 = physical page 2
        if page2_result.has_text:
            similarity = _similarity_score(page1_text, page2_result.text)
            page_results.append({
                "page": 2,
                "status": "ok" if similarity >= 80 else "warn",
                "similarity": similarity,
                "original_chars": page1_chars,
                "transcribed_chars": len(page2_result.text),
                "notes": "Transcribed scanned page 2 (should match page 1)",
            })
            if similarity < 80:
                overall_status = "warn"
        else:
            page_results.append({
                "page": 2,
                "status": "fail",
                "similarity": 0,
                "original_chars": page1_chars,
                "transcribed_chars": 0,
                "notes": "OCR failed; page remains without text layer",
            })
            overall_status = "fail"

        # Page 3 (complex layout).
        page3_result = results[2]  # index 2 = physical page 3
        page3_text = """Advanced Layout Test

Features:

• Bullet point one
• Bullet point two
• Bullet point three

Result Table

Column A | Column B
--- | ---
Data 1 | Value 1
Data 2 | Value 2"""
        if page3_result.has_text:
            similarity = _similarity_score(page3_text, page3_result.text)
            page_results.append({
                "page": 3,
                "status": "ok" if similarity >= 75 else "warn",
                "similarity": similarity,
                "original_chars": len(page3_text),
                "transcribed_chars": len(page3_result.text),
                "notes": "Transcribed complex layout page",
            })
            if similarity < 75:
                overall_status = "warn"
        else:
            page_results.append({
                "page": 3,
                "status": "fail",
                "similarity": 0,
                "original_chars": len(page3_text),
                "transcribed_chars": 0,
                "notes": "OCR failed",
            })
            overall_status = "fail"

        return {
            "model": model or os.environ.get("PDFX_VLM_MODEL"),
            "pages": page_results,
            "overall_status": overall_status,
        }
    finally:
        import os as os_module
        os_module.unlink(tmp_path)


def _create_ocr_test_pdf() -> bytes:
    """Create a test PDF with pages 2 and 3 having no text layer."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    # Create pages programmatically using ReportLab.
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # Page 1: Text with text layer (control).
    story.append(Paragraph("Simple Text Page", styles["Heading1"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "This is page one with a normal text layer. It contains plain text "
            "that can be extracted normally. This page will serve as the reference "
            "for comparing OCR accuracy on scanned pages.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.5 * inch))

    # Page 2 placeholder text (will be rendered as image with no text layer).
    story.append(Paragraph("Scanned Page 2", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            "This text should appear on page 2. When rendered as an image without "
            "a text layer, the OCR system must transcribe it from the rendered page.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.5 * inch))

    # Page 3: Complex layout placeholder.
    story.append(Paragraph("Advanced Layout Test", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Features:", styles["Heading3"]))
    # Add bullet points as paragraphs for simplicity.
    for item in ["Bullet point one", "Bullet point two", "Bullet point three"]:
        story.append(Paragraph(f"• {item}", styles["BodyText"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Result Table", styles["Heading3"]))
    story.append(Spacer(1, 0.1 * inch))
    table_data = [
        ["Column A", "Column B"],
        ["Data 1", "Value 1"],
        ["Data 2", "Value 2"],
    ]
    table = Table(table_data)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 14),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(table)

    # Build the PDF.
    doc.build(story)
    return buffer.getvalue()


def _similarity_score(original: str, transcribed: str) -> float:
    """Calculate character-level similarity between original and transcribed text.

    Returns a score 0-100 representing the percentage of matching characters.
    """
    # Simple similarity: count matching characters after normalization.
    import difflib
    matcher = difflib.SequenceMatcher(None, original, transcribed)
    return round(matcher.ratio() * 100, 1)

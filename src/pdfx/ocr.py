"""VLM-based OCR for scanned (no text layer) pages (roadmap Phase 3).

Pages without a text layer are rendered and sent to a vision-language model for
transcription, over the same OpenAI-compatible API — with the same response
validation, caching, and cost controls — as the Markdown AI pass. Unlike that
pass, the image is the only source here: there is no draft to preserve, so the
prompt asks for a faithful transcription and the length check is the main guard
against refusals and hallucinated non-answers.

`validate_ocr` backs the `pdfx validate-vlm-ocr` command: it generates a small
synthetic PDF whose pages 2-3 contain text drawn only as embedded images (no
text layer), runs the real OCR path against the configured model, and scores
the transcriptions against the known expected text.
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import textwrap
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

from pdfx import core
from pdfx.models import PageText
from pdfx.pages import PageSpec
from pdfx.vlm_utils import (
    VlmError,
    cache_path,
    cache_read,
    cache_write,
    file_sha256,
    make_client,
    strip_code_fence,
)

# Bumped whenever the system prompt or request shape changes, so cached
# responses from an older prompt are not reused.
PROMPT_VERSION = "1"

# Transcriptions shorter than this are rejected. Refusals and non-answers are
# usually short; a real scanned page with less text than this is rare enough
# that keeping the no-text placeholder is the safer failure mode.
MIN_TRANSCRIPTION_CHARS = 20

SYSTEM_PROMPT = """\
You transcribe the text of one scanned PDF page from its image.

Transcribe exactly what you see: keep the original words, numbers, punctuation, and \
capitalization. Do not correct, summarize, translate, or add anything. If a passage is \
illegible, write [illegible] in its place and continue.

Preserve the reading order and structure with plain line breaks: one line per printed line \
for headings, list items, and table rows; blank lines between paragraphs. Include headers, \
footers, and page numbers where they appear.

Return only the transcription — no commentary, no code fences. If the page contains no text \
at all, return [no text]."""


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
    warnings: list[str] | None = None,
) -> list[PageText]:
    """OCR the scanned pages in `pages` via a VLM; returns one PageText per
    scanned page, in page order.

    Pages that already have a text layer are not OCR'd and do not appear in the
    result (extract them with `core.get_text`). A successful transcription has
    `has_text=True`; a failed one (API error, rejected response) keeps
    `has_text=False` with empty text, and a message is appended to `warnings`
    when a list is passed. Configuration, caching, and concurrency behave
    exactly like the Markdown AI pass (see `markdown.to_markdown`); rendering
    the pages requires poppler.
    """
    client, model = make_client(model, base_url, feature="OCR")
    path = Path(path)
    reader = core._open_reader(path, password)
    numbers, labels = core._resolve_pages(reader, pages, physical)

    # Same per-page has_text test as core.get_index.
    scanned = [n for n in numbers if not (reader.pages[n - 1].extract_text() or "").strip()]
    if not scanned:
        return []

    sink = warnings if warnings is not None else []
    file_hash = file_sha256(path)
    cache = cache_path(cache_dir) if use_cache else None
    results: dict[int, str] = {}

    with tempfile.TemporaryDirectory(prefix="pdfx-ocr-") as tmp:
        spec = ",".join(str(n) for n in scanned)
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

        def transcribe(n: int) -> str | None:
            """OCR one page into `results`; returns a warning message or None."""
            key = hashlib.sha256(
                f"ocr:{file_hash}:{n}:{model}:{PROMPT_VERSION}:{dpi}".encode()
            ).hexdigest()
            if cache is not None:
                hit = cache_read(cache, key)
                if hit is not None:
                    results[n] = hit
                    return None
            try:
                response = _call_vlm(client, model, rendered[n])
            except Exception as exc:  # any API failure keeps the placeholder
                return f"page {n}: OCR failed ({exc}); kept no-text placeholder"
            accepted, reason = _accept_response(response)
            if accepted is None:
                return f"page {n}: OCR response rejected ({reason}); kept no-text placeholder"
            results[n] = accepted
            if cache is not None:
                cache_write(cache, key, accepted, PROMPT_VERSION)
            return None

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            sink.extend(w for w in pool.map(transcribe, scanned) if w is not None)

    return [
        PageText(
            physical_page=n,
            labeled_page=core._label_for(labels, n),
            text=results.get(n, ""),
            has_text=n in results,
        )
        for n in scanned
    ]


def _call_vlm(client, model: str, image_path: Path) -> str | None:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this scanned page."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            },
        ],
    )
    return completion.choices[0].message.content


def _accept_response(response: str | None) -> tuple[str | None, str]:
    """Validate an OCR response; (accepted_text, "") or (None, reason)."""
    if response is None:
        return None, "empty response"
    text = strip_code_fence(response.strip())
    if not text:
        return None, "empty response"
    if len(text) < MIN_TRANSCRIPTION_CHARS:
        return None, (
            f"response too short ({len(text)} chars, minimum {MIN_TRANSCRIPTION_CHARS}); "
            "likely a refusal or an empty page"
        )
    return text, ""


# --- validate-vlm-ocr: exercise the OCR path on a known synthetic document ---

# Prose with digits and punctuation, so transcription errors that matter
# (swapped digits, dropped punctuation) lower the score.
VALIDATION_PROSE = (
    "OCR validation page. The quick brown fox jumps over the lazy dog. "
    "Serial number 48291-B, invoice total $1,234.56, date 2026-07-19. "
    "This sentence checks that ordinary prose survives transcription with its "
    "exact characters intact."
)

VALIDATION_LAYOUT_LINES = [
    "OCR Layout Test",
    "",
    "- First bullet item",
    "- Second bullet item",
    "- Third bullet item",
    "",
    "Region  Units  Revenue",
    "North   120    4800",
    "South   95     3610",
]

PROSE_THRESHOLD = 80  # ok at/above; warn below
LAYOUT_THRESHOLD = 70  # layout page tolerates more reflow


def validate_ocr(
    model: str | None = None,
    base_url: str | None = None,
    dpi: int = 150,
    poppler_path: str | Path | None = None,
) -> dict:
    """Run the OCR path end-to-end against a synthetic scanned PDF.

    The document has three pages: page 1 with a normal text layer (verifies
    OCR leaves it alone), and pages 2-3 whose text exists only as embedded
    images — simple prose and a bullets-plus-table layout. Both are OCR'd with
    the configured model (cache bypassed) and scored against the known text.

    Returns a report dict: per-page status (skipped/ok/warn/fail) with
    similarity percentages, any OCR warnings, and an overall_status of
    pass/warn/fail.
    """
    with tempfile.TemporaryDirectory(prefix="pdfx-ocr-validate-") as tmp:
        pdf_path = Path(tmp) / "validation.pdf"
        _write_validation_pdf(pdf_path)

        # The whole point is that pages 2-3 have no text layer; verify rather
        # than assume, so a reportlab/Pillow change can't silently turn this
        # into a test of nothing (the bug this guards against).
        reader = core._open_reader(pdf_path, None)
        layered = [bool((p.extract_text() or "").strip()) for p in reader.pages]
        if layered != [True, False, False]:
            raise VlmError(
                f"internal error: validation PDF text layers are {layered}, "
                "expected [True, False, False]"
            )

        warnings: list[str] = []
        results = {
            r.physical_page: r
            for r in transcribe_pages(
                pdf_path,
                "all",
                model=model,
                base_url=base_url,
                dpi=dpi,
                poppler_path=poppler_path,
                use_cache=False,
                warnings=warnings,
            )
        }

    pages = [
        {
            "physical_page": 1,
            "status": "skipped",
            "detail": "has a text layer; OCR correctly not attempted",
        }
    ]
    expectations = [
        (2, VALIDATION_PROSE, PROSE_THRESHOLD, "prose"),
        (3, "\n".join(VALIDATION_LAYOUT_LINES), LAYOUT_THRESHOLD, "bullets and table"),
    ]
    overall = "pass"
    for page_no, expected, threshold, what in expectations:
        result = results.get(page_no)
        if result is None or not result.has_text:
            pages.append(
                {
                    "physical_page": page_no,
                    "status": "fail",
                    "detail": f"no transcription produced for the {what} page",
                }
            )
            overall = "fail"
            continue
        similarity = _similarity(expected, result.text)
        status = "ok" if similarity >= threshold else "warn"
        if status == "warn" and overall == "pass":
            overall = "warn"
        pages.append(
            {
                "physical_page": page_no,
                "status": status,
                "similarity": similarity,
                "threshold": threshold,
                "expected_chars": len(expected),
                "transcribed_chars": len(result.text),
                "detail": f"transcription of the {what} page",
            }
        )

    return {
        "model": model or os.environ.get("PDFX_VLM_MODEL"),
        "dpi": dpi,
        "pages": pages,
        "warnings": warnings,
        "overall_status": overall,
    }


def _similarity(expected: str, transcribed: str) -> float:
    """Whitespace-insensitive character similarity, as a 0-100 percentage."""
    a, b = " ".join(expected.split()), " ".join(transcribed.split())
    return round(SequenceMatcher(None, a, b).ratio() * 100, 1)


def _write_validation_pdf(path: Path) -> None:
    """Three-page validation PDF: page 1 has a text layer; pages 2-3 carry
    their text only inside embedded images (rendered with Pillow), so they
    genuinely exercise the no-text-layer OCR path."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError as exc:
        raise VlmError(
            "validate-vlm-ocr generates its test PDF with reportlab, which is a "
            "dev dependency of this repo ('uv sync' installs it) or "
            "'pip install reportlab' elsewhere."
        ) from exc

    width, height = letter
    c = rl_canvas.Canvas(str(path), pagesize=letter)

    c.setFont("Helvetica", 12)
    c.drawString(72, 720, "pdfx OCR validation document")
    c.drawString(72, 700, "Page 1 has a normal text layer and must be skipped by OCR.")
    c.drawString(72, 680, "Pages 2 and 3 contain text only as images (no text layer).")
    c.showPage()

    for lines in (textwrap.wrap(VALIDATION_PROSE, width=48), VALIDATION_LAYOUT_LINES):
        image = _text_image(lines)
        c.drawImage(ImageReader(image), 0, 0, width=width, height=height)
        c.showPage()
    c.save()


def _text_image(lines: list[str], scale: int = 2):
    """White letter-page image (2x resolution) with the lines drawn in black."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (612 * scale, 792 * scale), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=18 * scale)
    except TypeError:  # Pillow < 10.1: no size parameter; tiny but legible at 2x
        font = ImageFont.load_default()
    y = 72 * scale
    for line in lines:
        draw.text((72 * scale, y), line, fill="black", font=font)
        y += 26 * scale
    return image

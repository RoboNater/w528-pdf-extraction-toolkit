# Phase 3: OCR for Scanned Pages via Vision-Language Model

## Motivation

Phase 2 introduced VLM-based Markdown refinement: each page is rendered to an image and reviewed by a vision-language model that refines the programmatic extraction. This infrastructure makes OCR nearly free — a VLM reviewing pages can also transcribe scanned ones.

Pages without a text layer ("no text layer" placeholders in Markdown output) are common in digitized documents and represent a real extraction bottleneck. The Phase 2 system prompt already teaches the VLM not to hallucinate (preferring draft text as ground truth), so we can repurpose that safety for OCR by crafting a prompt that asks the VLM to transcribe what it sees in the image when no draft text exists.

## Scope

**In scope:**
- VLM-based OCR via the same OpenAI-compatible API used for Markdown refinement
- Triggered by `--ocr` flag in `pdfx markdown` command (opt-in, like `--ai`)
- Pages with no text layer are sent to the VLM for transcription
- All existing validation, caching, and cost controls from Markdown refinement apply
- New `pdfx validate-vlm-ocr` command to test OCR on a small synthetic PDF with known content

**Out of scope:**
- Local OCR engines (tesseract, paddleOCR) — VLM is the only backend for consistency with Phase 2
- PDF creation/modification
- Fine-grained OCR confidence scores or region-level output
- Non-Latin script tuning (VLM performance varies; use case determines adequacy)

## Design: OCR Transcription Prompt

The Markdown refinement prompt prioritizes the draft text (ground truth for characters). For OCR, we flip the ground truth: the image is ground truth for content, the draft is empty or a placeholder.

**OCR System Prompt:**

```
You are an OCR agent. Your task is to transcribe all text visible in the page image,
preserving the original layout and structure as much as possible.

Guidelines:
- Transcribe exactly what you see; do not correct obvious OCR errors or apply corrections.
- If text is partially obscured or illegible, indicate this with [...] and continue.
- Preserve paragraph breaks, lists, tables, and heading-like formatting.
- If there are page numbers, footers, or headers in the margin, include them at the top/bottom.
- Return ONLY the transcribed text — no commentary, no markdown formatting, no code fences.
```

This is simpler than the Markdown prompt because there's no draft to preserve. The VLM transcribes what it sees, and we apply the same length validation (reject suspiciously short responses) to catch hallucination.

## Implementation: `ocr.py`

New module, parallel to `markdown.py`:

```python
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
) -> list[PageText]
```

- Accepts the same parameters as Markdown refinement
- Returns a list of `PageText` models (same as `core.get_text`)
- Only processes pages with `has_text: false` (scanned pages)
- Caches responses with the same key strategy (file hash + page + model + prompt version + dpi)
- Falls back to empty text on any failure (VLM error, validation failure)
- Populates `page.text` with transcribed content, `page.has_text = true` after successful OCR

## Integration with Markdown

The `to_markdown()` function gains an `--ocr` parameter:

```python
def to_markdown(
    ...,
    ocr: bool = False,  # new parameter
    ...
) -> MarkdownResult
```

When `ocr=True` (and `ai=True` for safety — OCR needs the VLM API key anyway):
1. Stage 1 runs normally (pages without text get the no-text placeholder)
2. Stage 2 refinement runs as before
3. **New stage 3:** After refinement, pages with `has_text=false` are sent for OCR transcription
4. OCR results replace the placeholder with actual extracted text
5. If both `--ai` and `--ocr` are enabled, the page is rendered once for both purposes

## CLI Changes

`pdfx markdown` adds `--ocr` flag:

```sh
pdfx markdown FILE.pdf --ai --ocr --model gpt-4-vision [other options]
```

The flag is only meaningful with `--ai`. A clear error if `--ocr` is passed without `--ai`.

## Validation: `pdfx validate-vlm-ocr`

New CLI command for testing OCR on a short synthetic PDF:

```sh
pdfx validate-vlm-ocr [--model NAME] [--base-url URL] [--dpi N]
```

Creates an in-memory PDF with:
- Page 1: A simple text page with a text layer (for comparison)
- Page 2: The same text rendered as an image, with no text layer (scanned)
- Page 3: A more complex layout (title, bullets, table)

The command runs OCR on pages 2 and 3, compares output to page 1, and reports:
- Whether transcription succeeded
- Character-level similarity to the original (Levenshtein distance as a percentage)
- Warnings if similarity is below a threshold (e.g., < 85%)

Example output:

```json
{
  "model": "gpt-4-vision",
  "pages": [
    {
      "page": 2,
      "status": "ok",
      "similarity": 94.2,
      "original_chars": 250,
      "transcribed_chars": 248,
      "notes": "Minor spacing difference near end"
    },
    {
      "page": 3,
      "status": "ok",
      "similarity": 89.1,
      "original_chars": 480,
      "transcribed_chars": 502,
      "notes": "Table formatting adjusted for clarity"
    }
  ],
  "overall_status": "pass"
}
```

This lets users verify that their VLM choice works well for their document types.

## Testing

- Unit tests for the OCR prompt and validation logic
- Integration test: mock OpenAI-compatible endpoint, verify OCR requests carry the page image
- Synthetic PDF fixture (reportlab-generated) with a text page and a scanned version
- Test cache behavior: repeated OCR calls on the same page use the cache
- Test fallback: when the VLM returns a suspiciously short response, fall back to empty text

## Caching Strategy

OCR responses are cached alongside Markdown refinement, keyed on:
```
sha256(file_hash : page : model : OCR_PROMPT_VERSION : dpi)
```

The version bumps when the OCR system prompt changes, ensuring old cache entries don't apply to new prompts.

## Cost and Performance

- OCR is bounded by the same concurrency and caching as Markdown refinement
- Per-page render happens once (shared between Markdown refinement and OCR if both are enabled)
- Most users won't enable OCR unless they have scanned pages; selective opt-in keeps the default fast

## Future Work

- Integration with Phase 4 RAG: OCR-extracted text is searchable/queryable
- Local OCR fallback (tesseract) for users without API access (separate from Phase 3)
- Confidence/region-level output if a real document demands it
- Language detection and multi-script support (monitor VLM capabilities)

---

## Implementation Notes

**Why VLM-based OCR over Tesseract?**
- Consistency: same infrastructure, same cost controls, same caching as Markdown refinement
- Simplicity: no new binary dependencies
- Quality: modern VLMs (GPT-4V, Claude Vision) often outperform Tesseract on complex layouts
- Tradeoff: requires API access; local-only users can't use it (but neither can Markdown `--ai`)

**Why a separate `ocr.py` module?**
- Clarity: OCR is distinct from Markdown refinement (different prompt, different ground truth)
- Reuse: `transcribe_pages()` can be called independently of Markdown (e.g., to OCR a PDF without Markdown output)
- Testing: easier to isolate and mock

**Why opt-in with `--ocr`?**
- Scanned pages are less common than digital ones
- OCR incurs API cost per page
- User controls when and whether to spend that cost
- Backward compatibility: default behavior unchanged

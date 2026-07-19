# How to run tests

## Unit and integration tests

```bash
uv run pytest
```

uv ensures the environment matches the lockfile, and all fixture PDFs are generated on the fly (no setup needed). You should see ~140+ tests passed.

Useful variations:

```bash
uv run pytest -v                        # list each test by name
uv run pytest tests/test_search.py      # one file
uv run pytest -k labels                 # only tests matching a keyword
uv run pytest -q --tb=short             # compact output, short tracebacks
uv run pytest --co -q                   # just list available tests
```

### Dependencies

Most text, search, and render tests require poppler (pdftotext/pdftoppm) on your PATH or via `PDFX_POPPLER_PATH`. The default text extraction engine shells out to pdftotext (issue #1).

Tests for OCR and Markdown's `--ai` pass require the optional `ai` dependencies: `uv sync --extra ai`. These tests use a mocked OpenAI-compatible endpoint (no real network calls).

## Manual testing

### Testing Markdown conversion

```bash
# Stage 1 only (programmatic)
uv run pdfx markdown report.pdf -o report.md --images-dir media

# With AI refinement (requires --ai dependencies and model configured)
PDFX_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run pdfx markdown report.pdf -o report.md --ai

# With OCR for scanned pages
PDFX_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run pdfx markdown report.pdf -o report.md --ai --ocr
```

### Testing OCR

Use `validate-vlm-ocr` to verify VLM OCR works with your setup:

```bash
PDFX_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run pdfx validate-vlm-ocr
```

Output reports per-page similarity scores (0-100%) compared to the original text. Scores below 80% may indicate the VLM struggles with your document style or language.

You can also test OCR programmatically:

```python
from pdfx.ocr import transcribe_pages

pages = transcribe_pages("scanned.pdf", model="gpt-4o-mini")
for page in pages:
    if page.has_text:
        print(f"Page {page.physical_page}: {len(page.text)} chars")
```

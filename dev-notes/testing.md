# How to run tests

```bash
uv run pytest
```

That's it — uv ensures the environment matches the lockfile, and all fixture
PDFs are generated on the fly (no setup needed). With poppler installed you
should see 168 passed; without it the render-dependent tests skip (see below).

Useful variations:

```bash
uv run pytest -v                        # list each test by name
uv run pytest tests/test_ocr.py         # one file
uv run pytest -k labels                 # only tests matching a keyword
uv run pytest -q --tb=short             # compact output, short tracebacks
```

Things to know:

- Most text, search, render, markdown-AI, and OCR tests need poppler
  (pdftotext/pdftoppm) on your PATH or via the `PDFX_POPPLER_PATH` environment
  variable — the default text extraction engine shells out to pdftotext
  (issue #1), and the AI/OCR passes render pages. If you see a large number of
  skips with reason "poppler (pdftoppm/pdftotext) not installed", your shell
  environment is missing the path for poppler. Any terminal you've opened
  since the winget install has it, so for you they should just run.
- The AI-pass tests (`test_markdown.py`) and OCR tests (`test_ocr.py`) run
  against a fake OpenAI-compatible endpoint served from a local thread (the
  `fake_vlm` fixture in `conftest.py`) — no network, no real API key, no cost.
  Nothing in the suite ever calls a real model.

# Manually testing the VLM features

The automated suite proves the plumbing; whether a *specific model* is good at
refinement/OCR is a judgment call the suite can't make. To exercise the real
thing:

```bash
# Check your OCR setup end-to-end on a synthetic scanned PDF (known text,
# similarity scoring; exits nonzero if OCR produced nothing):
PDFX_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... uv run pdfx validate-vlm-ocr

# Markdown with AI refinement, then with OCR for scanned pages:
PDFX_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run pdfx markdown report.pdf -o report.md --ai
PDFX_VLM_MODEL=gpt-4o-mini OPENAI_API_KEY=sk-... \
  uv run pdfx markdown scanned.pdf -o scanned.md --ai --ocr
```

Local servers (Ollama, LM Studio, vLLM) work the same way with
`--base-url`/`PDFX_VLM_BASE_URL` and no API key.

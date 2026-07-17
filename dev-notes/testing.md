# How to run tests
`uv run pytest`

That's it — uv ensures the environment matches the lockfile, and all fixture PDFs are generated on the fly (no setup needed). You should see 120 passed.

Useful variations:
```bash
uv run pytest -v                        # list each test by name
uv run pytest tests/test_search.py      # one file
uv run pytest -k labels                 # only tests matching a keyword
uv run pytest -q --tb=short             # compact output, short tracebacks
```

One thing to know: most text, search, and render tests need poppler (pdftotext/pdftoppm) on your PATH or via the `PDFX_POPPLER_PATH` environment variable — the default text extraction engine shells out to pdftotext (issue #1). Any terminal you've opened since the winget install has it, so for you they should just run. If you see a large number of skips with reason "poppler (pdftoppm/pdftotext) not installed", your shell environment is missing the path for poppler.

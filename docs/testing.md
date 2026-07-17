# How to run tests
`uv run pytest`

That's it — uv ensures the environment matches the lockfile, and all fixture PDFs are generated on the fly (no setup needed). You should see 111 passed.

Useful variations:
```bash
uv run pytest -v                        # list each test by name
uv run pytest tests/test_search.py      # one file
uv run pytest -k labels                 # only tests matching a keyword
uv run pytest -q --tb=short             # compact output, short tracebacks
```

One thing to know: the 6 render tests need poppler's pdftoppm on your PATH. Any terminal you've opened since the winget install has it, so for you they should just run. If you ever see 5 skipped/6 skipped with reason "poppler (pdftoppm) not installed", your shell environment is missing the path for poppler.

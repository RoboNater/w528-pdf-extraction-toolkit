# AGENTS.md — context for AI development sessions

pdfx is a JSON-first PDF extraction toolkit: a Python library (`pdfx.core`,
`pdfx.markdown`) plus a Typer CLI (`pdfx`) for document index, text, tables,
images, search, page rendering, and Markdown conversion with an optional
AI (vision-language model) review pass.

## Layout

- `src/pdfx/core.py` — pure extraction functions; no printing, no CLI concerns.
- `src/pdfx/markdown.py` — Markdown conversion (stage 1 programmatic, stage 2
  VLM review over any OpenAI-compatible API).
- `src/pdfx/models.py` — pydantic result models. `src/pdfx/pages.py` — page
  spec parsing. `src/pdfx/cli.py` — Typer wrapper only.
- `tests/` — pytest; all fixture PDFs are generated at run time with reportlab
  in `conftest.py` (never commit binary fixtures).
- `ROADMAP.md` — the phased plan and the record of what shipped; keep it
  current. `docs/usage.md` — user guide; update it with any CLI change.
- `dev-notes/` — investigation write-ups for fixed issues.

## Commands

```sh
uv sync                # base deps; add --extra ai for the VLM review pass
uv run pytest
uv run ruff check && uv run ruff format   # line length 100
```

poppler (`pdftotext`/`pdftoppm`) is required for the default text engine and
rendering: `apt install poppler-utils`. Tests needing it use the
`requires_poppler` marker and skip when absent (e.g. Windows CI).

## Conventions

- Core stays import-clean and CLI-free (a future MCP server imports it
  directly). Heavy/optional deps live in extras and are imported lazily —
  `openai` must never be imported unless the AI pass runs.
- Every per-page result carries both `physical_page` (1-based position) and
  `labeled_page` (the PDF's display label, `null` when unlabeled). Page specs
  are interpreted against page labels by default; `--physical` /
  `physical=True` opts out. New features must preserve this.
- Default text engine is poppler's `pdftotext` because in-process extractors
  run words together on PDFs that encode gaps as glyph kerning (issue #1);
  don't quietly switch engines.
- CLI: JSON to stdout by default; errors exit 1 with `{"error": ...}` on
  stdout and a message on stderr; stdout/stderr forced to UTF-8 for Windows.
- Errors subclass `core.PdfxError` so the CLI's `_errors()` handler catches
  them.
- A feature is: core/library function returning pydantic models + CLI wrapper
  + tests + `docs/usage.md` update. Version bumps follow the roadmap phases.

## Testing notes

- VLM tests run against a fake OpenAI-compatible HTTP server on a local thread
  (`FakeVlm` in `tests/test_markdown.py`) — no network, no real keys. VLM env
  vars (`PDFX_VLM_*`, `OPENAI_API_KEY`) are cleared via the `vlm_env` fixture;
  always pass `cache_dir=tmp_path` in AI tests so `~/.cache/pdfx` is untouched.
- AI-pass responses are cached keyed on file hash + page + model +
  `PROMPT_VERSION` (+ dpi + outline context). Bump `PROMPT_VERSION` in
  `markdown.py` whenever the prompt or request shape changes.

## Workflow

- Each roadmap phase (and any sizeable change) lands on its own feature
  branch, fully tested, then merges to `main` via PR.
- Run the full suite and both ruff commands before committing; keep
  README/usage/roadmap in sync with behavior in the same commit.

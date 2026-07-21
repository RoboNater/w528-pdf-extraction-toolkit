# pdfx

PDF extraction toolkit: a JSON-first Python library and CLI for pulling structured
information out of PDF files — document index, text, tables, embedded images,
page renders, and Markdown conversion with optional AI review.

Permissive dependencies only (`pypdf`, `pdfplumber`, `pdf2image`, `typer`, `pydantic`);
no PyMuPDF/AGPL. The core library is CLI-free so a future MCP server can import it
directly.

See [docs/usage.md](docs/usage.md) for the full usage guide with examples.

## Setup

Managed with [uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

Text extraction (default engine) and page rendering additionally require
[poppler](https://poppler.freedesktop.org/):

- Linux: `apt install poppler-utils`
- macOS: `brew install poppler`
- Windows: `winget install oschwartz10612.Poppler`

If poppler is not on `PATH`, point `PDFX_POPPLER_PATH` (or `--poppler-path`) at its
`bin` directory. Text extraction defaults to poppler's `pdftotext` because it
segments words correctly on PDFs that encode word gaps as glyph positioning
rather than space characters; `--engine pypdf` / `--engine pdfplumber` select
in-process extractors that avoid the subprocess but can run words together on
such files.

## CLI

`--pages` accepts `all`, `5`, `3-7`, or `1,3-5,9`. When the PDF defines page labels
(ebook-style `cover`, `i`-`xx`, restarting at `1` for content), specs are interpreted
against those labels — matching what PDF readers display; pass `--physical` for
plain 1-based physical numbering.
Output is JSON on stdout by default; errors exit nonzero with `{"error": ...}` on
stdout and a message on stderr. Encrypted PDFs take `--password`.

```sh
uv run pdfx index  FILE                          # document index as JSON
uv run pdfx text   FILE --pages 3-7 [--layout]   # text; --plain for raw, --engine to pick extractor
uv run pdfx search FILE "query" [--regex]        # find text; hits with page context
uv run pdfx tables FILE --pages all [--csv DIR]  # tables as JSON, or one CSV per table
uv run pdfx images FILE --pages all --out DIR    # extract embedded images
uv run pdfx render FILE --pages 1-3 --out DIR --dpi 200 --format png
uv run pdfx markdown FILE -o out.md [--images-dir media] [--ai]  # Markdown conversion
```

`markdown` converts pages to Markdown (prose, pipe tables, image links, with
page-provenance comments). `--ai` adds a review pass where a vision-language
model — any OpenAI-compatible API — checks each page's draft against the
rendered page image and fixes structure. `--outline-headings` and
`--outline-context` (with `--ai`) use the PDF's outline to get heading levels
right on pages extracted mid-document; see
[docs/usage.md](docs/usage.md#pdfx-markdown--convert-to-markdown) for
configuration. The AI pass needs
the optional dependencies: `uv sync --extra ai`.

## Configuration file

Any CLI option can be given a persistent default in an optional TOML config
file, so a bare `pdfx FILE.pdf` (just the PDF path, no subcommand) finds the
config and runs the action it prescribes:

```toml
[default]
command = "markdown"          # what `pdfx FILE.pdf` runs; omit → "index"

[markdown]                    # per-command defaults
ai = true
engine = "pypdf"
outline_headings = true

[text]
engine = "pypdf"
layout = true

[vlm]                         # shared VLM settings (model / base_url / ...)
model = "gpt-4o-mini"
base_url = "https://openrouter.ai/api/v1"
organization = "org-abc123"
cache_dir = "~/.cache/pdfx"
# the API key is never read from the config file — it stays in the environment
# (PDFX_VLM_API_KEY / OPENAI_API_KEY).
```

Every option resolves by precedence **flag → environment variable → config file
→ built-in default**. Because flags win, boolean options are paired so you can
turn a config-enabled feature back off on the command line — e.g. `--no-ai`
overrides `[markdown] ai = true`, and every `--flag` has a matching `--no-flag`.
VLM keys set in a command section (say `[markdown] model`) override the same key
in `[vlm]` for that command.

The file is discovered, in order: an explicit `--config PATH` (or `$PDFX_CONFIG`);
the nearest `pdfx.toml` walking up from the current directory; then
`~/.config/pdfx/config.toml`. When both a project and a user file are found they
merge per key with the project file winning. A malformed file reports a clear
error rather than a traceback.

## Library

```python
from pdfx import core

index = core.get_index("doc.pdf")            # DocumentIndex
texts = core.get_text("doc.pdf", "1-3")      # list[PageText]
tables = core.get_tables("doc.pdf", "all")   # list[Table]
images = core.get_images("doc.pdf", "all", out_dir=None)  # list[ImageInfo]
rendered = core.render_pages("doc.pdf", "1", "out/", dpi=200)  # list[RenderedPage]

from pdfx.markdown import to_markdown
result = to_markdown("doc.pdf", images_dir="media")  # MarkdownResult
```

Core functions return pydantic models; serialize with `.model_dump_json()`.

## Development

```sh
uv run pytest        # test PDFs are generated at run time; no binary fixtures
uv run ruff check src tests
uv run ruff format src tests
```

Tests that need poppler (text extraction with the default engine, search, render)
skip automatically when it is not installed.

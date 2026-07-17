# pdfx

PDF extraction toolkit: a JSON-first Python library and CLI for pulling structured
information out of PDF files — document index, text, tables, embedded images, and
page renders.

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
```

## Library

```python
from pdfx import core

index = core.get_index("doc.pdf")            # DocumentIndex
texts = core.get_text("doc.pdf", "1-3")      # list[PageText]
tables = core.get_tables("doc.pdf", "all")   # list[Table]
images = core.get_images("doc.pdf", "all", out_dir=None)  # list[ImageInfo]
rendered = core.render_pages("doc.pdf", "1", "out/", dpi=200)  # list[RenderedPage]
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

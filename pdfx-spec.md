# pdfx — PDF Extraction Toolkit Specification

## Purpose

A Python library + CLI for extracting structured information from PDF files, designed for
programmatic consumption (JSON-first output). A future MCP server will wrap the same core
API, so the core must remain free of CLI/formatting concerns.

## Constraints

- **License:** Permissive dependencies only — no AGPL (this excludes PyMuPDF).
- **Python:** 3.11+
- **Dependencies:**
  - `pypdf` — document metadata, outline/TOC, page-level text extraction
  - `pdfplumber` — table extraction, higher-fidelity text with layout when needed
  - `pdf2image` + system `poppler-utils` — page rasterization to images
  - `typer` — CLI
  - `pydantic` — typed result models / JSON serialization
- **Packaging:** `uv` for environment and dependency management (`uv add`, `uv sync`);
  `pyproject.toml` with entry point `pdfx`, runnable via `uv run pdfx`

## Architecture

```
pdfx/
├── pyproject.toml
├── README.md
├── src/pdfx/
│   ├── __init__.py
│   ├── core.py          # pure extraction functions; no printing, no CLI
│   ├── models.py        # pydantic models: DocumentIndex, PageText, Table, ImageInfo, ...
│   ├── pages.py         # page-range parsing utility ("3", "3-7", "1,4-6", "all")
│   └── cli.py           # typer app wrapping core functions
└── tests/
    ├── conftest.py      # fixtures; generate small test PDFs programmatically
    └── test_*.py
```

**Design rule:** `core.py` functions accept a path (or open handle) plus parameters and
return pydantic models. `cli.py` only parses args, calls core, and serializes output.
The future MCP server (`FastMCP` from the official `mcp` SDK) will import `core` directly.

## Core API

All page numbers are **1-based** in the public API and CLI.

```python
def get_index(path: Path) -> DocumentIndex
    # page_count, metadata (title/author/dates), outline/bookmarks tree,
    # per-page summary (page number, width/height, rotation, has_text flag)

def get_text(path: Path, pages: PageSpec, layout: bool = False) -> list[PageText]
    # pypdf extract_text() by default; pdfplumber when layout=True

def get_tables(path: Path, pages: PageSpec) -> list[Table]
    # pdfplumber extract_tables(); Table = page, index, rows (list[list[str|None]])

def get_images(path: Path, pages: PageSpec, out_dir: Path | None) -> list[ImageInfo]
    # embedded images via pypdf page.images; save to out_dir if given,
    # otherwise return metadata only (name, page, size, format)

def render_pages(path: Path, pages: PageSpec, out_dir: Path,
                 dpi: int = 200, fmt: str = "png") -> list[RenderedPage]
    # pdf2image convert_from_path with first_page/last_page batching
```

`PageSpec` accepts: `"all"`, single page `"5"`, range `"3-7"`, mixed list `"1,3-5,9"`.

## CLI Design

```
pdfx index  FILE                          # document index as JSON
pdfx text   FILE --pages 3-7 [--layout]   # text; JSON default, --plain for raw text
pdfx tables FILE --pages all [--csv DIR]  # tables as JSON, or one CSV per table
pdfx images FILE --pages all --out DIR    # extract embedded images
pdfx render FILE --pages 1-3 --out DIR --dpi 200 --format png
```

Conventions:
- JSON to stdout by default (machine-friendly); `--plain`/`--csv` for human/file variants
- Errors: nonzero exit code, message to stderr, structured `{"error": ...}` on stdout
- Encrypted PDFs: accept `--password`; fail clearly if missing/wrong

## Error Handling

- Missing file, non-PDF file, corrupt PDF → clear error, exit 1
- Page numbers out of range → error listing the valid range
- `pdf2image` missing poppler → detect and report install hint (`apt install poppler-utils`)
- Pages with no extractable text (scanned) → return empty text with `has_text: false`,
  not an error (OCR is out of scope for v1)

## Testing

- Generate small test PDFs in `conftest.py` using `reportlab` (dev dependency):
  text pages, a table, an embedded image, multi-page doc with bookmarks
- Test: page-spec parsing, index/outline, text by range, table rows, image extraction,
  render output files exist with correct dimensions
- `pytest`; aim for tests to run without any binary fixtures checked into the repo

## Out of Scope (v1)

- Form field extraction
- PDF modification/creation
- MCP server (v2 — but keep core importable and CLI-free to enable it)

## Phase 3 — OCR for Scanned Pages (VLM-based)

A `--ocr` flag for `pdfx markdown` command that uses a vision-language model to
transcribe pages without a text layer. Leverages the same VLM infrastructure as
the Markdown refinement pass (Phase 2), so cost is minimal when both features are
used together. Pages with a text layer are unaffected.

**CLI:**

```sh
pdfx markdown FILE.pdf --ai --ocr --model NAME [other options]
```

The `--ocr` flag is only meaningful with `--ai` (OCR requires the VLM API key anyway).

**New validation command:**

```sh
pdfx validate-vlm-ocr [--model NAME] [--base-url URL] [--dpi N]
```

Tests OCR on a synthetic PDF with known content and reports similarity scores,
allowing users to verify their VLM choice works well for their documents.

---

# Claude Code Kickoff Prompt

Copy the text below into Claude Code from the project root directory:

```
Read pdfx-spec.md in this directory and implement the project it describes.

Work in this order:
1. Scaffold the project: pyproject.toml (src layout, typer entry point `pdfx`),
   package skeleton, and dev tooling (pytest, ruff). Use uv for all environment
   and dependency management: `uv add` for dependencies, `uv add --dev` for dev
   tools, `uv run` to execute pytest and the CLI. Never invoke pip directly.
2. Implement pages.py (PageSpec parsing) with tests first.
3. Implement models.py and core.py function by function: get_index, get_text,
   get_tables, get_images, render_pages. Write tests alongside each using
   reportlab-generated fixture PDFs in conftest.py.
4. Implement cli.py with typer, matching the CLI design in the spec exactly.
5. Run the full test suite and fix failures. Then run each CLI command against
   a generated sample PDF and show me the output.

Constraints:
- Permissive licenses only: pypdf, pdfplumber, pdf2image, typer, pydantic.
  Do NOT use PyMuPDF/fitz.
- core.py must not print or import typer — it returns pydantic models only.
- Public API and CLI use 1-based page numbers.
- If poppler-utils is not installed, install it or clearly flag it.

When done, summarize what was built, test results, and any spec deviations.
```

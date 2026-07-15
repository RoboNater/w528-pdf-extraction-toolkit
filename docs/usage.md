# pdfx Usage Guide

`pdfx` extracts structured information from PDF files. It is JSON-first: every
command prints JSON to stdout by default so output can be piped into other tools.
The same functionality is available as a Python library (`pdfx.core`).

## Conventions

- **Page numbers are 1-based** everywhere (CLI and library).
- **`--pages`** accepts:

  | Spec        | Meaning                          |
  |-------------|----------------------------------|
  | `all`       | every page (default)             |
  | `5`         | page 5                           |
  | `3-7`       | pages 3 through 7, inclusive     |
  | `1,3-5,9`   | mixed list; deduplicated, sorted |

- **Errors** exit with code 1, print a human-readable message to stderr, and print
  `{"error": "..."}` to stdout so scripted callers always get parseable JSON.
- **Encrypted PDFs**: pass `--password PW` (library: `password="PW"`). Missing or
  wrong passwords produce a clear error.

## CLI

Run via `uv run pdfx ...` from the project directory (or just `pdfx ...` inside an
activated environment). `pdfx --help` and `pdfx COMMAND --help` show full options.

### `pdfx index` — document overview

```sh
uv run pdfx index report.pdf
```

Returns page count, metadata (title, author, dates), the bookmark/outline tree, and
a per-page summary:

```json
{
  "path": "report.pdf",
  "page_count": 3,
  "metadata": { "title": "Quarterly Report", "author": "...", ... },
  "outline": [ { "title": "Introduction", "page": 1, "children": [] }, ... ],
  "pages": [
    { "page": 1, "width": 612.0, "height": 792.0, "rotation": 0, "has_text": true },
    ...
  ]
}
```

`has_text: false` usually means a scanned/image-only page (OCR is out of scope for v1).

### `pdfx text` — extract text

```sh
uv run pdfx text report.pdf --pages 3-7           # JSON: [{page, text, has_text}, ...]
uv run pdfx text report.pdf --pages 1 --plain     # raw text only
uv run pdfx text report.pdf --pages all --layout  # layout-aware (slower, better columns)
```

The default extractor is pypdf. `--layout` switches to pdfplumber's layout-aware
extraction, which preserves horizontal positioning — useful for multi-column pages
or when reading order matters.

### `pdfx tables` — extract tables

```sh
uv run pdfx tables report.pdf --pages all            # JSON: [{page, index, rows}, ...]
uv run pdfx tables report.pdf --pages 2 --csv out/   # one CSV file per table
```

`rows` is a list of rows of cell strings; empty cells are `null` in JSON. With
`--csv`, files are written as `table_pageNNNN_MM.csv` and the JSON output lists the
written paths. Detection works best on ruled (lined) tables.

### `pdfx images` — embedded images

```sh
uv run pdfx images report.pdf --pages all             # metadata only
uv run pdfx images report.pdf --pages all --out imgs/ # also save the image files
```

Reports name, page, pixel size, and format for each embedded image. With `--out`,
files are saved as `pageNNNN_imgMM_<name>` and `saved_path` is filled in.

### `pdfx render` — rasterize pages

```sh
uv run pdfx render report.pdf --pages 1-3 --out renders/ --dpi 200 --format png
```

Writes `page_NNNN.png` (or `.jpg` with `--format jpeg`) into `--out` and reports the
pixel dimensions of each file. Requires poppler (see below).

## Library

All core functions accept a path plus parameters and return pydantic models —
serialize with `.model_dump()` / `.model_dump_json()`.

```python
from pdfx import core

index = core.get_index("report.pdf")
print(index.page_count, index.metadata.title)

for page_text in core.get_text("report.pdf", "1-3", layout=False):
    print(page_text.page, page_text.text[:80])

for table in core.get_tables("report.pdf", "all"):
    print(f"page {table.page}, table {table.index}: {len(table.rows)} rows")

images = core.get_images("report.pdf", "all", out_dir=None)   # metadata only
rendered = core.render_pages("report.pdf", "1", "out/", dpi=200)

# Encrypted files
text = core.get_text("locked.pdf", "all", password="secret")
```

Errors raise `FileNotFoundError`, `pdfx.PageSpecError`, or subclasses of
`pdfx.core.PdfxError` (`InvalidPdfError`, `PasswordError`, `PopplerNotFoundError`).

## Poppler (rendering only)

`pdfx render` shells out to poppler via pdf2image; everything else works without it.

- Linux: `apt install poppler-utils`
- macOS: `brew install poppler`
- Windows: `winget install oschwartz10612.Poppler`

If poppler is not on `PATH` (common on Windows), point at its `bin` directory with
`--poppler-path DIR` or the `PDFX_POPPLER_PATH` environment variable.

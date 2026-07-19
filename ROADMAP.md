# pdfx Roadmap

Plan for the next phases of pdfx development. Each phase lands on its own
feature branch, fully tested and documented, before the next begins. Version
bumps: 0.2.0 after Phase 1, 0.3.0 after Phase 2, 0.4.0 after Phase 3, 0.5.0
after Phase 4, 0.6.0 after Phase 5.

## Phase 1 — Search ✅ (shipped in 0.2.0)

A `pdfx search` command so finding content in a large document doesn't require
extracting text and grepping it manually — with results reported in both
numbering schemes, closing the loop with page labels.

**Core** (`core.search`):

```python
def search(path, query, pages="all", regex=False, ignore_case=True,
           context=80, max_hits=100, password=None, physical=False) -> list[SearchHit]
```

- `SearchHit` model: `physical_page`, `labeled_page`, `snippet` (match with
  ~`context` characters either side, match delimited so callers can highlight),
  `match` (the exact matched text).
- Plain (non-regex) queries match with whitespace normalized — runs of
  spaces/newlines collapse to single spaces — so phrases match across line
  wraps in extracted text. `--regex` searches the raw page text.
- `max_hits` caps result size (JSON-first tool; a common word in a 500-page
  ebook shouldn't produce megabytes).

**CLI:**

```sh
pdfx search FILE QUERY [--pages SPEC] [--regex] [--case-sensitive]
                       [--context N] [--max N] [--plain] [--password PW] [--physical]
```

JSON by default; `--plain` prints one line per hit (`page 12 (pp 39): ...snippet...`)
for interactive use.

**Tests:** hits with correct pages/labels, multi-hit pages, phrase across a line
break, regex mode, case sensitivity, max cap, no-match returns `[]` not an error.

Landed as designed. Also fixed along the way: text extraction now defaults to
`pdftotext` for correct word spacing (issue #1), and CLI stdout/stderr are
forced to UTF-8 on Windows.

## Phase 2 — Markdown conversion

A `pdfx markdown` command that turns a PDF (or page range) into clean Markdown,
in two stages: a fast programmatic pass built from the existing extractors, and
an optional AI pass where a vision-language model reviews each page's draft
Markdown against the rendered page image and corrects it.

**Stage 1 — programmatic pass** (`markdown.py`, pure assembly over `core`):

```python
def to_markdown(path, pages="all", images_dir=None, ai=False, model=None,
                base_url=None, dpi=150, password=None, physical=False) -> MarkdownResult
```

- Text via `get_text` (pdftotext layout), tables via `get_tables` rendered as
  GitHub-flavored pipe tables, images extracted to `images_dir` and referenced
  with relative links (skipped when `images_dir` is `None`).
- Per-page output joined with an HTML-comment delimiter carrying provenance
  (`<!-- page 12 (pp 39) -->`), labels-first like everything else.
- Models: `MarkdownPage` (`physical_page`, `labeled_page`, `markdown`,
  `ai_refined: bool`), `MarkdownResult` (pages + joined `markdown`).

**Stage 2 — AI review pass** (opt-in via `ai=True` / `--ai`):

- Each page is rendered to an image (`render_pages`, requires poppler) and sent
  with its draft Markdown to a vision-language model, which returns corrected
  Markdown: fixes reading order, merged/split words, table structure, missing
  headings, and content the programmatic pass dropped or garbled.
- **OpenAI-compatible API only** — works against OpenAI, OpenRouter, Ollama,
  LM Studio, vLLM, etc. Configuration: `--model`/`PDFX_VLM_MODEL`,
  `--base-url`/`PDFX_VLM_BASE_URL`, key from `PDFX_VLM_API_KEY` falling back to
  `OPENAI_API_KEY`. Clear error when model or key is missing.
- The `openai` client lives in an optional dependency group (`uv sync --extra
  ai`); the base install stays light and stage 1 never imports it.
- Per-page failure (API error, timeout) falls back to the programmatic draft
  for that page with `ai_refined: false` and a warning — one bad page never
  sinks the document.

**CLI:**

```sh
pdfx markdown FILE [-o OUT.md] [--pages SPEC] [--images-dir DIR]
                   [--ai] [--model NAME] [--base-url URL] [--dpi N]
                   [--password PW] [--physical]
```

Markdown to stdout by default (`-o` writes a file); `--json` emits the
`MarkdownResult` for programmatic callers, consistent with the JSON-first rest
of the tool.

**Tests:** stage 1 on existing fixtures — headings/paragraph text, a table
rendered as a valid pipe table, image links pointing at extracted files, page
delimiters with correct labels. Stage 2 against a faked OpenAI-compatible
endpoint (no network in CI): request carries image + draft, response replaces
the page, API error falls back to the draft with `ai_refined: false`.

## Phase 3 — Quality of life

Three independent, small items.

**3a. `index` performance flag.** `get_index` currently extracts text from every
page to compute `has_text` — the slowest part of indexing a large ebook. Add
`check_text: bool = True` to `core.get_index` and `--no-text-check` to the CLI;
when disabled, `has_text` is `null` in output (model field becomes
`bool | None`). Index of a several-hundred-page PDF becomes near-instant.

**3b. Form fields.** `core.get_fields(path, password) -> list[FormField]` via
pypdf `reader.get_fields()`; model: `name`, `field_type` (text/checkbox/radio/
choice/signature), `value`, `default_value`. New CLI command `pdfx fields FILE`.
Documents without forms return `[]`. Fixture: generate a simple AcroForm with
pypdf in conftest.

**3c. CI.** GitHub Actions workflow: matrix of ubuntu-latest + windows-latest,
steps = install uv (`astral-sh/setup-uv`), `uv sync`, `ruff check` +
`ruff format --check`, `uv run pytest`. Ubuntu installs `poppler-utils` so
render tests run; Windows skips them (already automatic). Requires the repo to
be on GitHub — skip this item if it stays on a local remote.

## Phase 4 — RAG: chunking and vector store

Make a PDF semantically queryable: chunk → embed → store → query, with page
provenance carried through so answers can cite labeled pages.

**Design principles:**

- Core stays import-clean: new modules `chunking.py` (pure) and `rag.py`
  (store/embedding); CLI wraps them like everything else.
- Heavy dependencies live in an optional group: `uv sync --extra rag`. Base
  install stays light.
- Local-first: no API keys required for the default path.

**Chunking** (`core`/`chunking.py`):

```python
def chunk_document(path, pages="all", target_chars=1200, overlap_chars=150,
                   password=None) -> list[Chunk]
```

- Splits on paragraph boundaries first, sentence boundaries as fallback,
  hard-split as last resort; adjacent chunks overlap by `overlap_chars`.
- `Chunk` model: `id` (stable hash of doc + span), `text`, `start_physical_page`,
  `end_physical_page`, `start_labeled_page`, `end_labeled_page`, `index`.
- `pdfx chunk FILE` emits chunks as JSON — useful standalone for feeding any
  external RAG pipeline, independent of our store.

**Vector store** (`rag.py`):

- **Engine: chromadb** (Apache-2.0, embedded/local, persistent directory).
  Alternative considered: LanceDB — also fine; chroma chosen for the simplest
  embedded API and built-in default embedding.
- **Embeddings: pluggable from day one**, selected via `--embedder` (env
  `PDFX_EMBEDDER`). Two implementations ship in Phase 4:
  - `local` (default): chroma's built-in ONNX MiniLM — downloads once, no
    torch, no API key.
  - `voyage` (API-based, higher quality): reads `VOYAGE_API_KEY`; errors
    clearly when the key is missing.
  The embedder interface is a small protocol (name + embed batch) so further
  providers are additive; the embedder name is stored in collection metadata
  and ingest/query refuse to mix embedders within a collection.
- Chunk metadata (pages, labels, source path, file hash) stored alongside
  vectors; re-ingesting an unchanged file is a no-op (file hash + chunk params).

**CLI:**

```sh
pdfx ingest FILE [--db DIR] [--collection NAME] [--embedder NAME]
                 [--target-chars N] [--overlap N]
pdfx query "question" [--db DIR] [--collection NAME] [--top-k K]
```

`query` output: hits with `score`, `text`, page provenance, and source path.

DB location resolution: `--db` flag, else `PDFX_DB` environment variable, else
`./.pdfx-db` in the current directory.

**Tests:** chunker is pure-python — test sizes, overlap, page provenance,
paragraph preservation. Store tests inject a deterministic dummy embedding
function (no model download in CI); one optional integration test runs the real
default embedder when the model is available locally.

## Phase 5 — MCP server

The spec's v2 goal: expose the same core to agents via MCP.

- `FastMCP` from the official `mcp` SDK; optional dependency group `mcp`;
  console script `pdfx-mcp` (stdio transport).
- Tools, mapped 1:1 onto core functions and returning their pydantic models as
  structured content: `pdf_index`, `pdf_text`, `pdf_tables`, `pdf_images`
  (metadata only), `pdf_search`, and — with a RAG store present — `pdf_query`.
  Rendering is omitted initially (file output is less useful over MCP; revisit
  with image content blocks if needed).
- Page specs behave exactly like the CLI, labels-first with a `physical`
  parameter, so agent ergonomics match human ergonomics.
- Configurable root directory allowlist so the server only reads PDFs under
  permitted paths.
- Tests: in-process client via the SDK's test transport; no subprocess needed.

## Out of scope (unchanged)

OCR for scanned pages, PDF modification/creation — revisit only when a real
document needs them.

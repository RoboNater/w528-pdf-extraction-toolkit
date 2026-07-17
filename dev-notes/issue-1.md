# Text extraction sometimes runs words together (missing inter-word spaces)

## Symptom

`pdfx text` (and therefore `pdfx search`) sometimes produces output where words
are concatenated with no spaces:

```
Whetheryouarelookingforaquickreference...
```

instead of

```
Whether you are looking for a quick reference...
```

Observed on PDFs processed in a remote environment; the affected file is not
available locally. Besides producing unreadable text, this silently poisons
downstream consumers: phrase search returns no hits, and any NLP/RAG pipeline
built on the extracted text gets garbage tokens with no error signal.

## Root cause

This is not a post-processing bug — whitespace normalization cannot fix it,
because the spaces are never extracted in the first place.

PDFs are not required to contain space characters. Many encode word gaps purely
as glyph positioning: a text line is a `TJ` operator whose array holds glyph
runs interleaved with kerning offsets, e.g.

```
[(Whether) -120 (you) -120 (are) ...] TJ
```

Extractors must *infer* word boundaries by comparing horizontal gaps against
font metrics. Both pure-Python extractors pdfx uses get this wrong on such
files:

- **pypdf** (`extract_text()`, our default): inserts a space only when a
  displacement exceeds an absolute threshold; smaller kerning-style word gaps
  produce no space.
- **pdfplumber** (used for `--layout`): merges characters into one word when the
  gap is below `x_tolerance` (default 3pt) — typical kerned word gaps at body
  font sizes fall below it, in both normal and layout mode.
- **poppler's `pdftotext`** segments the same files correctly; its word-break
  heuristics are relative to font size and much more mature.

## Reproduction

A synthetic PDF (checked in as the `kerned_pdf` test fixture,
`tests/conftest.py`) draws each line as a single `TJ` array with 0.12 em kerning
offsets between words and **no space glyphs anywhere**. Extraction results:

| Extractor            | Output                          |
|----------------------|---------------------------------|
| pypdf                | `Whetheryouarelookingfora`      |
| pdfplumber           | `Whetheryouarelookingfora`      |
| pdfplumber (layout)  | `Whetheryouarelookingfora`      |
| pdftotext (poppler)  | `Whether you are looking for a` |

This matches the signature reported from the remote environment (both Python
libraries fail, `pdftotext` succeeds).

## Resolution

Default to correctness: `pdfx text` and `pdfx search` now shell out to
poppler's `pdftotext` by default (one subprocess per contiguous page run,
pages split on the form-feed separator). The pure-Python extractors remain
available as explicit opt-ins via `--engine pypdf` / `--engine pdfplumber`
(library: `engine=...`) for poppler-free environments or callers who accept
the mis-segmentation risk.

Auto-detection (extract with pypdf, fall back to poppler when the space ratio
looks anomalous) was considered and rejected: thresholds can pass borderline
pages and still feed corrupted text to downstream processing with no error
signal.

Performance turns out not to be a trade-off for typical use: on the 827-page
sample ebook, extracting pages 20–39 takes ~1.0s via poppler vs ~1.2s via pypdf
and ~6s via pdfplumber (whole book via poppler: ~14s), since a contiguous page
range costs a single subprocess.

Requires poppler to be installed for default text extraction (it was already
required for `pdfx render`); `PDFX_POPPLER_PATH` / `--poppler-path` are honored
as before, and the error message when poppler is missing explains both the
install options and the engine fallbacks.

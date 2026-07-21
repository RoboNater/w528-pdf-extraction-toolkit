# Phase 3: OCR for scanned pages via the Phase 2 VLM integration

## Motivation

Phase 2's AI pass renders each page and sends it to a vision-language model
over an OpenAI-compatible API, with response validation, a per-page cache, and
bounded concurrency. That infrastructure makes OCR nearly free: a VLM that
reviews pages can also transcribe scanned ones. The roadmap's out-of-scope
note anticipated exactly this — "Phase 2 is the natural moment to revisit that
line deliberately" — and Phase 3 crosses it on those terms.

Pages without a text layer currently surface as `has_text: false` in `index`
output and `<!-- page N: no text layer -->` placeholders in `markdown` output.
For digitized documents that's the whole document.

## Scope

**In scope:**

- VLM-based OCR (`pdfx.ocr.transcribe_pages`) over the same OpenAI-compatible
  API, configuration, validation, caching, and concurrency as the Markdown AI
  pass.
- `pdfx markdown --ocr` (requires `--ai`): scanned pages get transcriptions
  instead of placeholders.
- `pdfx validate-vlm-ocr`: prove the user's model/endpoint can OCR before
  spending money on a real document.

**Out of scope:**

- Local OCR engines (tesseract, PaddleOCR, …). VLM-only keeps one backend, no
  new dependencies, and one set of cost controls. Revisit only if a real
  document needs offline OCR.
- OCR confidence scores or region/bounding-box output.
- PDF modification (e.g. writing a text layer back into the file).

## Design

### Ground truth flips relative to the AI pass

The Phase 2 prompt treats the *draft* as ground truth for characters and the
image as ground truth for structure only, because VLMs hallucinate when
transcribing. OCR has no draft: the image is the only source. The prompt
therefore demands faithful transcription — keep exact words, numbers,
punctuation, capitalization; no corrections, summaries, or additions; write
`[illegible]` rather than guessing; `[no text]` for a blank page. Structure is
conveyed with plain line breaks (one line per printed line, blank line between
paragraphs), which reads fine in Markdown output and keeps the API useful as a
plain-text extractor.

Without a draft there is no length-ratio check, so validation is weaker by
nature. What remains: strip a wrapping code fence, reject empty responses, and
reject responses under `MIN_TRANSCRIPTION_CHARS` (20) — refusals and
non-answers are short, and a real page with less text than that is rare enough
that keeping the placeholder is the safer failure mode.

### `pdfx/ocr.py`

```python
def transcribe_pages(path, pages="all", model=None, base_url=None, jobs=1,
                     dpi=150, password=None, physical=False, poppler_path=None,
                     cache_dir=None, use_cache=True, warnings=None) -> list[PageText]
```

- Scanned-page detection uses the same per-page test as `core.get_index`:
  pypdf `extract_text()` is empty after stripping. Only those pages are
  rendered (poppler) and sent; **one `PageText` per scanned page** comes back,
  in page order. Pages with a text layer are not in the result — extracting
  them is `core.get_text`'s job, and returning them here with empty text would
  misreport `has_text`.
- Failures (API error, rejected response) never raise: the page's result keeps
  `has_text=False`/empty text and a message is appended to the caller's
  `warnings` list. Configuration errors (no model, no key, missing `openai`
  package) raise `VlmError` up front, same as the AI pass.
- Cache key: `sha256("ocr:" + file_hash : page : model : PROMPT_VERSION : dpi)`
  — the `ocr:` prefix and separate `PROMPT_VERSION` keep OCR and AI-pass
  entries from ever colliding, and the version bumps when the prompt changes.

### Shared plumbing: `pdfx/vlm_utils.py`

`markdown.py` and `ocr.py` share client construction (`make_client`: model/
base-URL/key resolution from args then `PDFX_VLM_*` env, lazy `openai` import,
`VlmError` on misconfiguration), the best-effort response cache, code-fence
stripping, and file hashing. Factored out of `markdown.py` because importing it
from `ocr.py` directly would be circular (`markdown` imports `ocr` for stage 3).

One trap worth recording: `to_markdown`'s `ocr` boolean parameter shadows the
`ocr` module name inside that function, so stage 3 imports `transcribe_pages`
at function level. An earlier draft called `ocr.transcribe_pages(...)` and
crashed with `AttributeError: 'bool' object has no attribute ...` on every
`--ocr` run.

### `pdfx markdown --ocr` (stage 3)

Requires `--ai` — OCR needs the same key/model anyway, and a standalone `--ocr`
that silently skipped refinement would surprise. `--ocr` without `--ai` errors
immediately.

After stage 2, pages still lacking text are passed to `transcribe_pages`.
Successes replace the placeholder body and set `ocr_transcribed: true` (new
`MarkdownPage` field, so JSON consumers can tell transcribed content from
extracted content — it is *not* `ai_refined`, which keeps meaning "the AI pass
restructured a draft"). Failures keep the placeholder and land in
`result.warnings`. Each stage renders its own pages: refinement renders pages
*with* text, OCR renders pages *without*, so no page is rendered twice and
sharing renders across stages isn't worth the coupling.

## `pdfx validate-vlm-ocr`

```sh
pdfx validate-vlm-ocr [--model NAME] [--base-url URL] [--dpi N] [--poppler-path DIR]
```

Generates a three-page synthetic PDF (reportlab + Pillow, in a temp dir):

1. **Page 1 — text layer.** Must be *skipped* by OCR; validates scanned-page
   detection, not transcription.
2. **Page 2 — prose as image.** Known prose containing digits, a serial
   number, currency, and a date — the things VLM transcription gets wrong —
   drawn with Pillow onto a white image embedded as the full page. No text
   layer.
3. **Page 3 — layout as image.** Heading, bullets, and a small aligned table.

The generator's output is verified (page 1 has a text layer, pages 2-3 don't)
before any API call — if a reportlab/Pillow change breaks that shape, the
command fails loudly instead of testing nothing. The real `transcribe_pages`
path then runs with the cache bypassed, and each transcription is scored
against the known text with a whitespace-insensitive `difflib` ratio.

Report (JSON, like everything else): per-page `status` — `skipped` / `ok` /
`warn` (below threshold: 80 for prose, 70 for layout) / `fail` (no
transcription) — with similarity and character counts, plus OCR warnings and
an `overall_status` of `pass`/`warn`/`fail`. `fail` exits nonzero; `warn`
exits zero but tells the user their model may struggle with their documents.

reportlab is imported lazily (it's a dev dependency of this repo, not a
runtime dependency); the command says how to get it if missing.

## Testing

All OCR tests run against the same faked OpenAI-compatible endpoint as the
Phase 2 tests (`fake_vlm` in conftest, promoted there from `test_markdown.py`);
no network, no real key. Rendering tests carry `@requires_poppler`.

- Response validation: fence stripped, empty/short rejected.
- `transcribe_pages`: scanned page transcribed with the image in the request;
  text-layer pages produce no API traffic and no result entries; API error and
  short response keep `has_text=False` and append warnings; second run served
  from cache; missing model/key raise `VlmError`.
- `markdown --ocr`: placeholder replaced and `ocr_transcribed` set; OCR failure
  keeps the placeholder with a warning; without `--ocr` the placeholder stays;
  `--ocr` without `--ai` rejected (library and CLI).
- Validation: the synthetic PDF has text layers exactly `[True, False, False]`
  (the property that makes the command test anything at all); end-to-end
  pass/warn/fail paths against the fake endpoint.

## Future work

- Feed OCR'd text into Phase 5 chunking/RAG so scanned documents become
  queryable.
- Optional local OCR fallback (tesseract) if offline use ever matters.
- A `pdfx ocr` CLI command exposing `transcribe_pages` directly, if plain-text
  OCR without Markdown assembly turns out to be wanted.

"""PDF → Markdown conversion (roadmap Phase 2).

Stage 1 assembles per-page Markdown programmatically from the extractors in
pdfx.core: prose text, tables as GitHub pipe tables, embedded images as links.
Table regions are cropped out of the prose via their bounding boxes so each
table appears exactly once, in flow position.

Stage 2 (opt-in, ai=True) sends each page's draft plus its rendered image to a
vision-language model over an OpenAI-compatible API. The draft is ground truth
for characters; the image is ground truth for structure — the model rearranges
and re-tags, it does not re-transcribe. Responses are validated before being
accepted; any per-page failure falls back to the programmatic draft. The
`openai` client is imported lazily so the base install never needs it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pdfplumber

from pdfx import core
from pdfx.models import ImageInfo, MarkdownPage, MarkdownResult
from pdfx.pages import PageSpec

# Bumped whenever the system prompt or request shape changes, so cached
# responses from an older prompt are not reused.
PROMPT_VERSION = "1"

SYSTEM_PROMPT = """\
You review machine-extracted Markdown for one PDF page against the page's rendered image.

The draft's characters are ground truth: keep its exact words, numbers, and punctuation. \
Do not re-transcribe text from the image and do not invent content that is not in the draft, \
except to restore short passages that are clearly visible in the image but missing from the draft.

Use the image only to fix structure: reading order, paragraph breaks, heading levels, lists, \
table shape and cell alignment, and text the extractor placed out of order. Merge words the \
extractor split and split words it ran together only where the image clearly shows it.

Keep image links exactly as they appear in the draft.

Return only the corrected Markdown for the page — no commentary, no code fences."""


class VlmError(core.PdfxError):
    """The AI pass is misconfigured (missing model, key, or openai package)."""


def to_markdown(
    path: Path,
    pages: PageSpec = "all",
    images_dir: Path | None = None,
    ai: bool = False,
    model: str | None = None,
    base_url: str | None = None,
    jobs: int = 1,
    dpi: int = 150,
    engine: core.TextEngine = "poppler",
    outline_headings: bool = False,
    outline_context: bool = False,
    password: str | None = None,
    physical: bool = False,
    poppler_path: str | Path | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> MarkdownResult:
    """Convert pages to Markdown.

    Stage 1 always runs: prose via the selected text engine (tables cropped out
    of it by bounding box), tables as pipe tables, and — when images_dir is
    given — embedded images extracted there and referenced with links relative
    to images_dir's parent (put images_dir next to your output file).

    ai=True adds the VLM review pass: model/base_url come from the arguments or
    the PDFX_VLM_MODEL / PDFX_VLM_BASE_URL environment variables, the API key
    from PDFX_VLM_API_KEY or OPENAI_API_KEY. Requires poppler (page rendering)
    and the optional `ai` dependency group. Accepted responses are cached under
    cache_dir (default ~/.cache/pdfx/vlm, override with PDFX_CACHE_DIR) keyed
    on file hash + page + model + prompt version + dpi + outline context, so
    interrupted runs resume without re-billing.

    Heading levels are otherwise page-local; two opt-in options anchor them to
    the document's outline (PDF bookmarks), and both are no-ops on documents
    without one. outline_headings=True promotes outline titles found on their
    destination pages to Markdown headings by outline depth (stage 1, no AI
    needed). outline_context=True (requires ai=True) tells the VLM each page's
    position in the outline so the levels it assigns match the document
    hierarchy rather than the single page's visual scale.
    """
    if outline_context and not ai:
        raise VlmError("outline_context requires the AI pass (--outline-context needs --ai).")
    path = Path(path)
    reader = core._open_reader(path, password)
    numbers, labels = core._resolve_pages(reader, pages, physical)

    flat_outline: list[tuple[str, int, int]] = []
    if outline_headings or outline_context:
        flat_outline = _flatten_outline(core._convert_outline(reader, reader.outline, labels))
    entries_by_page: dict[int, list[tuple[str, int]]] = {}
    for title, page_no, depth in flat_outline:
        entries_by_page.setdefault(page_no, []).append((title, depth))

    images_by_page: dict[int, list[ImageInfo]] = {}
    if images_dir is not None:
        spec = ",".join(str(n) for n in numbers)
        for info in core.get_images(
            path, spec, out_dir=images_dir, password=password, physical=True
        ):
            images_by_page.setdefault(info.physical_page, []).append(info)

    bodies: dict[int, str] = {}
    has_content: dict[int, bool] = {}
    with pdfplumber.open(path, password=password) as pdf:
        tables_by_page = {n: pdf.pages[n - 1].find_tables() for n in numbers}
        plain_pages = [n for n in numbers if not tables_by_page[n]]
        texts = (
            core._page_texts(path, reader, plain_pages, engine, False, password, poppler_path)
            if plain_pages
            else {}
        )
        for n in numbers:
            found = tables_by_page[n]
            if found:
                body = _page_with_tables(pdf.pages[n - 1], found)
            else:
                body = _clean_text(texts[n])
            if outline_headings:
                body = _tag_outline_headings(body, entries_by_page.get(n, []))
            image_links = _image_links(images_by_page.get(n, []), images_dir)
            body = "\n\n".join(part for part in (body, image_links) if part)
            bodies[n] = body
            has_content[n] = bool(body)

    result_pages = [
        MarkdownPage(
            physical_page=n,
            labeled_page=core._label_for(labels, n),
            markdown=bodies[n],
            has_text=has_content[n],
        )
        for n in numbers
    ]

    warnings: list[str] = []
    if ai:
        contexts = (
            {n: _outline_context_for(flat_outline, n) for n in numbers} if outline_context else {}
        )
        _refine_pages(
            path,
            [p for p in result_pages if p.has_text],
            model=model,
            base_url=base_url,
            jobs=jobs,
            dpi=dpi,
            password=password,
            poppler_path=poppler_path,
            cache_dir=cache_dir,
            use_cache=use_cache,
            warnings=warnings,
            contexts=contexts,
        )

    return MarkdownResult(
        path=str(path),
        pages=result_pages,
        markdown="\n\n".join(_delimited(p) for p in result_pages) + "\n",
        warnings=warnings,
    )


def _delimited(page: MarkdownPage) -> str:
    """Page body prefixed with its provenance delimiter; no-text pages collapse
    to the placeholder comment alone."""
    if page.labeled_page is not None:
        where = f"page {page.labeled_page} (pp {page.physical_page})"
    else:
        where = f"page {page.physical_page}"
    if not page.has_text:
        return f"<!-- {where}: no text layer -->"
    return f"<!-- {where} -->\n\n{page.markdown}"


# --- stage 1: programmatic assembly ---


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _pipe_table(rows: list[list[str | None]]) -> str:
    width = max(len(row) for row in rows)

    def cell(value: str | None) -> str:
        if value is None:
            return ""
        return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    def line(row: list[str | None]) -> str:
        padded = list(row) + [None] * (width - len(row))
        return "| " + " | ".join(cell(v) for v in padded) + " |"

    header, *body = rows
    return "\n".join([line(header), "| " + " | ".join(["---"] * width) + " |", *map(line, body)])


def _page_with_tables(pl_page, found_tables) -> str:
    """Interleave prose and pipe tables in vertical flow order. Prose comes from
    cropping the page to the horizontal bands between table bounding boxes, so
    table content never appears twice (the dedup the roadmap calls out).

    Uses pdfplumber for the prose on these pages (the band cropping needs
    character positions); pages without tables keep the default engine.
    """
    page_top, page_bottom = pl_page.bbox[1], pl_page.bbox[3]
    blocks: list[str] = []
    cursor = page_top
    for table in sorted(found_tables, key=lambda t: t.bbox[1]):
        top, bottom = table.bbox[1], table.bbox[3]
        if top - cursor > 1:
            blocks.append(_band_text(pl_page, cursor, top))
        blocks.append(_pipe_table(table.extract()))
        cursor = max(cursor, bottom)
    if page_bottom - cursor > 1:
        blocks.append(_band_text(pl_page, cursor, page_bottom))
    return "\n\n".join(block for block in blocks if block)


def _band_text(pl_page, top: float, bottom: float) -> str:
    x0, page_top, x1, page_bottom = pl_page.bbox
    band = pl_page.crop((x0, max(page_top, top), x1, min(page_bottom, bottom)))
    return _clean_text(band.extract_text() or "")


def _image_links(infos: list[ImageInfo], images_dir: Path | None) -> str:
    if not infos or images_dir is None:
        return ""
    links = []
    for info in infos:
        if info.saved_path is None:
            continue
        rel = Path(images_dir).name + "/" + Path(info.saved_path).name
        links.append(f"![{info.name}]({rel})")
    return "\n".join(links)


# --- outline-aware headings (both options are no-ops without an outline) ---


def _flatten_outline(items, depth: int = 0) -> list[tuple[str, int, int]]:
    """Outline tree -> [(title, physical_page, depth)] in document order.
    Entries whose destination page could not be resolved are dropped, but their
    children are kept (at their own depth)."""
    flat: list[tuple[str, int, int]] = []
    for item in items:
        if item.physical_page is not None:
            flat.append((item.title, item.physical_page, depth))
        flat.extend(_flatten_outline(item.children, depth + 1))
    return flat


def _norm_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip(".:-–—·").strip().casefold()


def _heading_match(line: str, title: str) -> bool:
    """Conservative fuzzy match: equal after normalization, or the title makes
    up nearly the whole line (tolerates trailing section numbers/punctuation)."""
    norm_line, norm_title = _norm_heading(line), _norm_heading(title)
    if not norm_line or not norm_title:
        return False
    return norm_line == norm_title or (
        norm_title in norm_line and len(norm_title) >= 0.8 * len(norm_line)
    )


def _tag_outline_headings(body: str, entries: list[tuple[str, int]]) -> str:
    """Promote lines that match an outline title on this page to Markdown
    headings, leveled by outline depth (top level = '#'). Each title tags at
    most one line; table/link/heading lines are never touched."""
    if not entries or not body:
        return body
    lines = body.split("\n")
    remaining = list(entries)
    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith(("|", "#", "!")):
            continue
        for entry in remaining:
            title, depth = entry
            if _heading_match(line, title):
                lines[i] = "#" * min(depth + 1, 6) + " " + line.strip()
                remaining.remove(entry)
                break
    return "\n".join(lines)


def _outline_context_for(flat_outline: list[tuple[str, int, int]], n: int) -> str:
    """Prompt block telling the VLM where page n sits in the outline: the
    section path open at this page, and any outline entries pointing at it."""
    if not flat_outline:
        return ""
    stack: list[tuple[str, int]] = []
    for title, page_no, depth in flat_outline:
        if page_no <= n:
            del stack[depth:]
            stack.append((title, depth))
    on_page = [(title, depth) for title, page_no, depth in flat_outline if page_no == n]
    if not stack and not on_page:
        return ""
    parts = ["Document outline context (from the PDF's bookmarks):"]
    if stack:
        parts.append("- Section path at this page: " + " > ".join(title for title, _ in stack))
    if on_page:
        listed = ", ".join(f"{title} (level {depth + 1})" for title, depth in on_page)
        parts.append(f"- Outline entries pointing at this page: {listed}")
    parts.append(
        "Use this to assign heading levels that match the document hierarchy: "
        "level 1 = '#', level 2 = '##', and so on."
    )
    return "\n".join(parts)


# --- stage 2: AI review pass ---


def _refine_pages(
    path: Path,
    pages: list[MarkdownPage],
    model: str | None,
    base_url: str | None,
    jobs: int,
    dpi: int,
    password: str | None,
    poppler_path: str | Path | None,
    cache_dir: Path | None,
    use_cache: bool,
    warnings: list[str],
    contexts: dict[int, str],
) -> None:
    """Review each page's draft against its rendered image; mutate accepted
    pages in place. Every failure path keeps the draft and appends a warning."""
    model = model or os.environ.get("PDFX_VLM_MODEL")
    if not model:
        raise VlmError("The AI pass needs a model: pass model=/--model or set PDFX_VLM_MODEL.")
    base_url = base_url or os.environ.get("PDFX_VLM_BASE_URL")
    api_key = os.environ.get("PDFX_VLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        if base_url is None:
            raise VlmError(
                "The AI pass needs an API key: set PDFX_VLM_API_KEY (or OPENAI_API_KEY). "
                "Local servers that skip auth also need --base-url/PDFX_VLM_BASE_URL."
            )
        api_key = "unused"  # local OpenAI-compatible servers ignore the key
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise VlmError(
            "The AI pass requires the 'openai' package; install the optional ai "
            "dependencies with 'uv sync --extra ai' or 'pip install pdfx[ai]'."
        ) from exc

    if not pages:
        return
    client = OpenAI(api_key=api_key, base_url=base_url)
    file_hash = _file_sha256(path)
    cache = _cache_path(cache_dir) if use_cache else None

    with tempfile.TemporaryDirectory(prefix="pdfx-vlm-") as tmp:
        spec = ",".join(str(p.physical_page) for p in pages)
        rendered = {
            r.physical_page: Path(r.path)
            for r in core.render_pages(
                path,
                spec,
                Path(tmp),
                dpi=dpi,
                password=password,
                poppler_path=poppler_path,
                physical=True,
            )
        }

        def refine(page: MarkdownPage) -> str | None:
            n = page.physical_page
            context = contexts.get(n, "")
            key = hashlib.sha256(
                f"{file_hash}:{n}:{model}:{PROMPT_VERSION}:{dpi}:{context}".encode()
            ).hexdigest()
            if cache is not None:
                hit = _cache_read(cache, key)
                if hit is not None:
                    page.markdown, page.ai_refined = hit, True
                    return None
            try:
                response = _call_vlm(client, model, page.markdown, rendered[n], context)
            except Exception as exc:  # any API failure keeps the draft
                return f"page {n}: AI pass failed ({exc}); kept programmatic draft"
            accepted, reason = _accept_response(page.markdown, response)
            if accepted is None:
                return f"page {n}: AI response rejected ({reason}); kept programmatic draft"
            page.markdown, page.ai_refined = accepted, True
            if cache is not None:
                _cache_write(cache, key, accepted)
            return None

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            warnings.extend(w for w in pool.map(refine, pages) if w is not None)


def _call_vlm(client, model: str, draft: str, image_path: Path, context: str = "") -> str | None:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    text = f"Draft Markdown for this page:\n\n{draft}"
    if context:
        text += f"\n\n{context}"
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            },
        ],
    )
    return completion.choices[0].message.content


_FENCE = re.compile(r"\A```[\w-]*\n(.*)\n```\Z", re.DOTALL)


def _accept_response(draft: str, response: str | None) -> tuple[str | None, str]:
    """Validate a VLM response; (accepted_markdown, "") or (None, reason)."""
    if response is None:
        return None, "empty response"
    text = response.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text:
        return None, "empty response"
    if len(draft) >= 200 and len(text) < len(draft) // 2:
        return None, f"response suspiciously short ({len(text)} vs draft {len(draft)} chars)"
    return text, ""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_path(cache_dir: Path | None) -> Path:
    if cache_dir is None:
        base = os.environ.get("PDFX_CACHE_DIR")
        cache_dir = Path(base) if base else Path.home() / ".cache" / "pdfx"
    return Path(cache_dir) / "vlm"


def _cache_read(cache: Path, key: str) -> str | None:
    target = cache / f"{key}.json"
    try:
        return json.loads(target.read_text(encoding="utf-8"))["markdown"]
    except (OSError, ValueError, KeyError):
        return None


def _cache_write(cache: Path, key: str, markdown: str) -> None:
    try:
        cache.mkdir(parents=True, exist_ok=True)
        payload = {"markdown": markdown, "prompt_version": PROMPT_VERSION}
        (cache / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; never fail the conversion over it

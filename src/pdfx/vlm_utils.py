"""Shared VLM plumbing for the Markdown AI pass and OCR.

Factored out of pdfx.markdown so pdfx.ocr can reuse it without a circular
import: client configuration (model/base URL/API key resolution and the lazy
`openai` import), the best-effort response cache, and response cleanup helpers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from pdfx import core


class VlmError(core.PdfxError):
    """A VLM pass is misconfigured (missing model, key, or openai package)."""


def make_client(model: str | None, base_url: str | None, feature: str = "The AI pass"):
    """Resolve VLM configuration and return (OpenAI client, model name).

    model/base_url fall back to PDFX_VLM_MODEL / PDFX_VLM_BASE_URL; the API key
    comes from PDFX_VLM_API_KEY or OPENAI_API_KEY. With a base_url set, a
    missing key is allowed (local OpenAI-compatible servers ignore it).
    `feature` names the caller in error messages ("The AI pass", "OCR").
    """
    model = model or os.environ.get("PDFX_VLM_MODEL")
    if not model:
        raise VlmError(f"{feature} needs a model: pass model=/--model or set PDFX_VLM_MODEL.")
    base_url = base_url or os.environ.get("PDFX_VLM_BASE_URL")
    api_key = os.environ.get("PDFX_VLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        if base_url is None:
            raise VlmError(
                f"{feature} needs an API key: set PDFX_VLM_API_KEY (or OPENAI_API_KEY). "
                "Local servers that skip auth also need --base-url/PDFX_VLM_BASE_URL."
            )
        api_key = "unused"  # local OpenAI-compatible servers ignore the key
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise VlmError(
            f"{feature} requires the 'openai' package; install the optional ai "
            "dependencies with 'uv sync --extra ai' or 'pip install pdfx[ai]'."
        ) from exc
    return OpenAI(api_key=api_key, base_url=base_url), model


_FENCE = re.compile(r"\A```[\w-]*\n(.*)\n```\Z", re.DOTALL)


def strip_code_fence(text: str) -> str:
    """Remove a code fence wrapping the whole response, if present."""
    fenced = _FENCE.match(text)
    return fenced.group(1).strip() if fenced else text


def cache_path(cache_dir: Path | None) -> Path:
    if cache_dir is None:
        base = os.environ.get("PDFX_CACHE_DIR")
        cache_dir = Path(base) if base else Path.home() / ".cache" / "pdfx"
    return Path(cache_dir) / "vlm"


def cache_read(cache: Path, key: str) -> str | None:
    target = cache / f"{key}.json"
    try:
        return json.loads(target.read_text(encoding="utf-8"))["markdown"]
    except (OSError, ValueError, KeyError):
        return None


def cache_write(cache: Path, key: str, text: str, prompt_version: str) -> None:
    try:
        cache.mkdir(parents=True, exist_ok=True)
        payload = {"markdown": text, "prompt_version": prompt_version}
        (cache / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; never fail the conversion over it


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

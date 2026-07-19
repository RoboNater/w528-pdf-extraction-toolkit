"""Shared VLM utilities used by markdown and ocr modules.

Factored out to avoid circular imports.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pdfx import core


class VlmError(core.PdfxError):
    """The AI pass is misconfigured (missing model, key, or openai package)."""


def cache_path(cache_dir: Path | None) -> Path:
    """Get the VLM cache directory."""
    if cache_dir is None:
        base = os.environ.get("PDFX_CACHE_DIR")
        cache_dir = Path(base) if base else Path.home() / ".cache" / "pdfx"
    return Path(cache_dir) / "vlm"


def cache_read(cache: Path, key: str) -> str | None:
    """Read a cached markdown or OCR response."""
    target = cache / f"{key}.json"
    try:
        return json.loads(target.read_text(encoding="utf-8"))["markdown"]
    except (OSError, ValueError, KeyError):
        return None


def cache_write(cache: Path, key: str, markdown: str) -> None:
    """Write a markdown or OCR response to cache."""
    try:
        cache.mkdir(parents=True, exist_ok=True)
        payload = {"markdown": markdown, "prompt_version": "1"}
        (cache / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; never fail over it


def file_sha256(path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

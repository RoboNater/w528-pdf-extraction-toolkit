"""Typer CLI wrapping pdfx.core. Parses args, calls core, serializes output.

Conventions:
- JSON to stdout by default; --plain/--csv for human/file variants.
- Errors: exit code 1, message to stderr, structured {"error": ...} on stdout.
"""

from __future__ import annotations

import csv
import enum
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Optional

import typer
from pydantic import BaseModel

from pdfx import core
from pdfx.pages import PageSpecError

app = typer.Typer(no_args_is_help=True, add_completion=False)

# On Windows, redirected/piped output defaults to the legacy code page (e.g. cp1252),
# which cannot encode arbitrary extracted PDF text. Force UTF-8 on both streams.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

FileArg = Annotated[Path, typer.Argument(help="Path to the PDF file")]
PagesOpt = Annotated[str, typer.Option("--pages", help="Pages: 'all', '5', '3-7', '1,3-5,9'")]
PasswordOpt = Annotated[
    Optional[str], typer.Option("--password", help="Password for encrypted PDFs")
]
PhysicalOpt = Annotated[
    bool,
    typer.Option(
        "--physical",
        help="Interpret --pages as physical positions (first page = 1), "
        "ignoring the PDF's page labels",
    ),
]


class TextEngine(str, enum.Enum):
    poppler = "poppler"
    pypdf = "pypdf"
    pdfplumber = "pdfplumber"


EngineOpt = Annotated[
    TextEngine,
    typer.Option(
        "--engine",
        help="Text extractor: poppler (default; correct word spacing, needs poppler "
        "installed), or pypdf/pdfplumber (in-process, faster, but may run words "
        "together on some PDFs)",
    ),
]
PopplerPathOpt = Annotated[
    Optional[Path],
    typer.Option("--poppler-path", help="Poppler bin directory if not on PATH"),
]


def _announce_labels(file: Path, pages: str, physical: bool, password: Optional[str]) -> None:
    """Tell the user (on stderr) when --pages is interpreted via page labels."""
    if physical or pages.strip().lower() == "all":
        return
    if core.get_page_labels(file, password=password) is not None:
        print(
            "Interpreting --pages using the PDF's page labels; "
            "pass --physical for 1-based physical page numbers.",
            file=sys.stderr,
        )


@contextmanager
def _errors():
    try:
        yield
    except (core.PdfxError, PageSpecError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}))
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1) from exc


def _dump(result: BaseModel | list[BaseModel] | dict) -> None:
    if isinstance(result, BaseModel):
        data = result.model_dump(mode="json")
    elif isinstance(result, list):
        data = [item.model_dump(mode="json") for item in result]
    else:
        data = result
    print(json.dumps(data, indent=2, ensure_ascii=False))


@app.command()
def index(file: FileArg, password: PasswordOpt = None) -> None:
    """Document index (metadata, outline, page summaries) as JSON."""
    with _errors():
        _dump(core.get_index(file, password=password))


@app.command()
def text(
    file: FileArg,
    pages: PagesOpt = "all",
    layout: Annotated[
        bool,
        typer.Option("--layout", help="Layout-preserving extraction (columns, indentation)"),
    ] = False,
    engine: EngineOpt = TextEngine.poppler,
    plain: Annotated[bool, typer.Option("--plain", help="Raw text instead of JSON")] = False,
    password: PasswordOpt = None,
    physical: PhysicalOpt = False,
    poppler_path: PopplerPathOpt = None,
) -> None:
    """Extract text; JSON by default, --plain for raw text."""
    with _errors():
        _announce_labels(file, pages, physical, password)
        result = core.get_text(
            file,
            pages,
            layout=layout,
            engine=engine.value,
            password=password,
            physical=physical,
            poppler_path=poppler_path,
        )
        if plain:
            print("\n\n".join(page.text for page in result))
        else:
            _dump(result)


@app.command()
def tables(
    file: FileArg,
    pages: PagesOpt = "all",
    csv_dir: Annotated[
        Optional[Path], typer.Option("--csv", help="Write one CSV per table to this directory")
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = False,
) -> None:
    """Extract tables as JSON, or one CSV file per table with --csv."""
    with _errors():
        _announce_labels(file, pages, physical, password)
        result = core.get_tables(file, pages, password=password, physical=physical)
        if csv_dir is None:
            _dump(result)
            return
        csv_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for table in result:
            stem = core.page_stem(table.physical_page, table.labeled_page)
            target = csv_dir / f"table_{stem}_{table.index:02d}.csv"
            with open(target, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for row in table.rows:
                    writer.writerow(["" if cell is None else cell for cell in row])
            written.append(str(target))
        _dump({"written": written})


@app.command()
def search(
    file: FileArg,
    query: Annotated[str, typer.Argument(help="Phrase (or regex with --regex) to search for")],
    pages: PagesOpt = "all",
    regex: Annotated[
        bool, typer.Option("--regex", help="Treat QUERY as a regular expression")
    ] = False,
    case_sensitive: Annotated[
        bool, typer.Option("--case-sensitive", help="Match case exactly")
    ] = False,
    context: Annotated[
        int, typer.Option("--context", help="Context characters around each match")
    ] = 80,
    max_hits: Annotated[int, typer.Option("--max", help="Maximum number of hits")] = 100,
    engine: EngineOpt = TextEngine.poppler,
    plain: Annotated[
        bool, typer.Option("--plain", help="One human-readable line per hit instead of JSON")
    ] = False,
    password: PasswordOpt = None,
    physical: PhysicalOpt = False,
    poppler_path: PopplerPathOpt = None,
) -> None:
    """Search page text; hits report both physical and labeled page numbers."""
    with _errors():
        _announce_labels(file, pages, physical, password)
        result = core.search(
            file,
            query,
            pages,
            regex=regex,
            ignore_case=not case_sensitive,
            context=context,
            max_hits=max_hits,
            engine=engine.value,
            password=password,
            physical=physical,
            poppler_path=poppler_path,
        )
        if plain:
            for hit in result:
                if hit.labeled_page is not None:
                    where = f"page {hit.labeled_page} (pp {hit.physical_page})"
                else:
                    where = f"page {hit.physical_page}"
                print(f"{where}: …{hit.before}[{hit.match}]{hit.after}…")
        else:
            _dump(result)
        if len(result) >= max_hits:
            print(
                f"Results capped at {max_hits}; pass --max to raise the limit.",
                file=sys.stderr,
            )


@app.command()
def images(
    file: FileArg,
    pages: PagesOpt = "all",
    out: Annotated[
        Optional[Path],
        typer.Option("--out", help="Save images to this directory (metadata only if omitted)"),
    ] = None,
    password: PasswordOpt = None,
    physical: PhysicalOpt = False,
) -> None:
    """Extract embedded images."""
    with _errors():
        _announce_labels(file, pages, physical, password)
        _dump(core.get_images(file, pages, out_dir=out, password=password, physical=physical))


@app.command()
def render(
    file: FileArg,
    out: Annotated[Path, typer.Option("--out", help="Output directory for rendered images")],
    pages: PagesOpt = "all",
    dpi: Annotated[int, typer.Option("--dpi", help="Render resolution")] = 200,
    fmt: Annotated[str, typer.Option("--format", help="Image format: png or jpeg")] = "png",
    password: PasswordOpt = None,
    poppler_path: PopplerPathOpt = None,
    physical: PhysicalOpt = False,
) -> None:
    """Rasterize pages to image files."""
    with _errors():
        _announce_labels(file, pages, physical, password)
        _dump(
            core.render_pages(
                file,
                pages,
                out,
                dpi=dpi,
                fmt=fmt,
                password=password,
                poppler_path=poppler_path,
                physical=physical,
            )
        )


if __name__ == "__main__":
    app()

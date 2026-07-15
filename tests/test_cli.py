"""CLI tests run against the installed `pdfx` entry point via subprocess."""

import json
import subprocess

from conftest import ENCRYPTED_PASSWORD, TABLE_DATA, requires_poppler


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["pdfx", *[str(a) for a in args]], capture_output=True, text=True, encoding="utf-8"
    )


def test_index_json(text_pdf):
    result = run_cli("index", text_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["page_count"] == 3
    assert data["metadata"]["title"] == "Test Document"
    assert len(data["outline"]) == 3


def test_text_json(text_pdf):
    result = run_cli("text", text_pdf, "--pages", "2")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["page"] == 2
    assert "Chapter Two" in data[0]["text"]


def test_text_plain(text_pdf):
    result = run_cli("text", text_pdf, "--pages", "1", "--plain")
    assert result.returncode == 0
    assert "Chapter One" in result.stdout
    assert not result.stdout.lstrip().startswith(("[", "{"))


def test_tables_json(table_pdf):
    result = run_cli("tables", table_pdf, "--pages", "all")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["rows"] == TABLE_DATA


def test_tables_csv(table_pdf, tmp_path):
    result = run_cli("tables", table_pdf, "--csv", tmp_path)
    assert result.returncode == 0
    written = json.loads(result.stdout)["written"]
    assert len(written) == 1
    content = open(written[0], encoding="utf-8").read()
    assert "Name,Qty,Price" in content


def test_images_metadata(image_pdf):
    result = run_cli("images", image_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["width"] == 64
    assert data[0]["saved_path"] is None


def test_password_flag(encrypted_pdf):
    result = run_cli("text", encrypted_pdf, "--pages", "1", "--password", ENCRYPTED_PASSWORD)
    assert result.returncode == 0
    assert "Chapter One" in json.loads(result.stdout)[0]["text"]


def test_error_is_structured(tmp_path):
    result = run_cli("index", tmp_path / "missing.pdf")
    assert result.returncode == 1
    assert "error" in json.loads(result.stdout)
    assert result.stderr.strip() != ""


def test_page_range_error(text_pdf):
    result = run_cli("text", text_pdf, "--pages", "99")
    assert result.returncode == 1
    assert "1-3" in json.loads(result.stdout)["error"]


@requires_poppler
def test_render(text_pdf, tmp_path):
    result = run_cli("render", text_pdf, "--pages", "1", "--out", tmp_path, "--dpi", "72")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["page"] == 1
    assert data[0]["dpi"] == 72

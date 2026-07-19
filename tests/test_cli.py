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


@requires_poppler
def test_text_json(text_pdf):
    result = run_cli("text", text_pdf, "--pages", "2")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["physical_page"] == 2
    assert "Chapter Two" in data[0]["text"]


@requires_poppler
def test_text_default_engine_spaces_kerned_pdf(kerned_pdf):
    result = run_cli("text", kerned_pdf, "--plain")
    assert result.returncode == 0
    assert "Whether you are looking for a" in result.stdout


def test_text_engine_pypdf(kerned_pdf):
    # pure-Python engine: no poppler needed, but mis-segments this PDF (issue #1)
    result = run_cli("text", kerned_pdf, "--engine", "pypdf", "--plain")
    assert result.returncode == 0
    assert "Whetheryouarelooking" in result.stdout


@requires_poppler
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


def test_tables_csv_labeled_names(labeled_table_pdf, tmp_path):
    from pathlib import Path

    result = run_cli("tables", labeled_table_pdf, "--csv", tmp_path)
    assert result.returncode == 0
    written = json.loads(result.stdout)["written"]
    assert Path(written[0]).name == "table_page0030_pp0001_00.csv"


def test_images_metadata(image_pdf):
    result = run_cli("images", image_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["width"] == 64
    assert data[0]["saved_path"] is None


@requires_poppler
def test_password_flag(encrypted_pdf):
    result = run_cli("text", encrypted_pdf, "--pages", "1", "--password", ENCRYPTED_PASSWORD)
    assert result.returncode == 0
    assert "Chapter One" in json.loads(result.stdout)[0]["text"]


@requires_poppler
def test_labels_default_with_notice(labeled_pdf):
    result = run_cli("text", labeled_pdf, "--pages", "1", "--plain")
    assert result.returncode == 0
    assert "Physical page 8" in result.stdout
    assert "page labels" in result.stderr


@requires_poppler
def test_physical_flag(labeled_pdf):
    result = run_cli("text", labeled_pdf, "--pages", "1", "--plain", "--physical")
    assert result.returncode == 0
    assert "Physical page 1" in result.stdout
    assert result.stderr.strip() == ""


@requires_poppler
def test_no_notice_for_unlabeled_pdf(text_pdf):
    result = run_cli("text", text_pdf, "--pages", "1")
    assert result.returncode == 0
    assert result.stderr.strip() == ""


def test_unknown_label_error(labeled_pdf):
    result = run_cli("text", labeled_pdf, "--pages", "42")
    assert result.returncode == 1
    assert "No page labeled" in json.loads(result.stdout)["error"]


def test_index_shows_labels(labeled_pdf):
    result = run_cli("index", labeled_pdf)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["has_page_labels"] is True
    assert data["pages"][0]["labeled_page"] == "cover"
    assert data["pages"][7]["labeled_page"] == "1"


@requires_poppler
def test_unicode_output_is_utf8(unicode_pdf):
    # run_cli decodes stdout strictly as UTF-8, so this fails if the CLI writes
    # console-code-page bytes (the Windows default for piped output)
    result = run_cli("text", unicode_pdf, "--pages", "1", "--plain")
    assert result.returncode == 0
    assert "Café — Über naïve résumé" in result.stdout


@requires_poppler
def test_unicode_json_output(unicode_pdf):
    result = run_cli("text", unicode_pdf, "--pages", "1")
    assert result.returncode == 0
    assert "Café" in json.loads(result.stdout)[0]["text"]


def test_error_is_structured(tmp_path):
    result = run_cli("index", tmp_path / "missing.pdf")
    assert result.returncode == 1
    assert "error" in json.loads(result.stdout)
    assert result.stderr.strip() != ""


def test_page_range_error(text_pdf):
    result = run_cli("text", text_pdf, "--pages", "99")
    assert result.returncode == 1
    assert "1-3" in json.loads(result.stdout)["error"]


def test_markdown_stdout(table_pdf):
    result = run_cli("markdown", table_pdf)
    assert result.returncode == 0
    assert "| Name | Qty | Price |" in result.stdout
    assert "<!-- page 1 -->" in result.stdout


def test_markdown_out_file(table_pdf, tmp_path):
    target = tmp_path / "out.md"
    result = run_cli("markdown", table_pdf, "-o", target)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "| Apple | 3 | 1.20 |" in target.read_text(encoding="utf-8")


def test_markdown_json(table_pdf):
    result = run_cli("markdown", table_pdf, "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["pages"][0]["physical_page"] == 1
    assert data["pages"][0]["ai_refined"] is False
    assert "| Name | Qty | Price |" in data["markdown"]
    assert data["warnings"] == []


def test_markdown_ai_config_error(table_pdf):
    result = run_cli("markdown", table_pdf, "--ai")
    assert result.returncode == 1
    assert "model" in json.loads(result.stdout)["error"]


@requires_poppler
def test_render(text_pdf, tmp_path):
    result = run_cli("render", text_pdf, "--pages", "1", "--out", tmp_path, "--dpi", "72")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data[0]["physical_page"] == 1
    assert data[0]["dpi"] == 72

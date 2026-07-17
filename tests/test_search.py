import json

import pytest
from conftest import requires_poppler
from test_cli import run_cli

from pdfx import core

# The default text engine shells out to poppler's pdftotext (issue #1).
pytestmark = requires_poppler


class TestSearchCore:
    def test_basic_hit(self, text_pdf):
        hits = core.search(text_pdf, "Chapter Two")
        assert len(hits) == 1
        hit = hits[0]
        assert hit.physical_page == 2
        assert hit.match == "Chapter Two"
        assert "This is page 2" in hit.after

    def test_hit_per_page(self, text_pdf):
        hits = core.search(text_pdf, "test document")
        assert [h.physical_page for h in hits] == [1, 2, 3]

    def test_page_spec_restricts(self, text_pdf):
        hits = core.search(text_pdf, "test document", pages="1-2")
        assert [h.physical_page for h in hits] == [1, 2]

    def test_case_insensitive_by_default(self, text_pdf):
        assert len(core.search(text_pdf, "cHaPtEr oNe")) == 1

    def test_case_sensitive(self, text_pdf):
        assert core.search(text_pdf, "chapter one", ignore_case=False) == []
        assert len(core.search(text_pdf, "Chapter One", ignore_case=False)) == 1

    def test_phrase_matches_across_line_break(self, text_pdf):
        # "Chapter One" and "This is page 1..." are separate lines in the PDF
        hits = core.search(text_pdf, "Chapter One This is page 1")
        assert len(hits) == 1
        assert hits[0].physical_page == 1

    def test_labeled_pages_reported(self, labeled_pdf):
        hits = core.search(labeled_pdf, "Physical page 8")
        assert len(hits) == 1
        assert hits[0].physical_page == 8
        assert hits[0].labeled_page == "1"

    def test_labels_used_for_page_spec(self, labeled_pdf):
        hits = core.search(labeled_pdf, "Physical page", pages="1-2")
        assert [h.physical_page for h in hits] == [8, 9]

    def test_regex(self, text_pdf):
        hits = core.search(text_pdf, r"page \d of", regex=True)
        assert len(hits) == 3
        assert hits[0].match == "page 1 of"

    def test_invalid_regex(self, text_pdf):
        with pytest.raises(core.QueryError, match="Invalid regular expression"):
            core.search(text_pdf, "(unclosed", regex=True)

    def test_empty_query(self, text_pdf):
        with pytest.raises(core.QueryError, match="Empty"):
            core.search(text_pdf, "   ")

    def test_max_hits_cap(self, text_pdf):
        assert len(core.search(text_pdf, "e", max_hits=3)) == 3

    def test_context_length(self, text_pdf):
        hits = core.search(text_pdf, "page 2", context=5)
        assert len(hits[0].before) <= 5
        assert len(hits[0].after) <= 5

    def test_no_match_is_empty_not_error(self, text_pdf):
        assert core.search(text_pdf, "zebra quantum") == []

    def test_no_match_on_blank_page(self, blank_pdf):
        assert core.search(blank_pdf, "anything") == []

    def test_kerned_pdf_phrase_found(self, kerned_pdf):
        # issue #1: with pypdf extraction this text was "quickreference"
        hits = core.search(kerned_pdf, "quick reference")
        assert len(hits) == 1
        assert core.search(kerned_pdf, "quick reference", engine="pypdf") == []


class TestSearchCli:
    def test_json_output(self, text_pdf):
        result = run_cli("search", text_pdf, "Chapter Two")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data[0]["physical_page"] == 2
        assert data[0]["match"] == "Chapter Two"

    def test_plain_output(self, labeled_pdf):
        result = run_cli("search", labeled_pdf, "Physical page 8", "--plain")
        assert result.returncode == 0
        assert result.stdout.startswith("page 1 (pp 8): ")
        assert "[Physical page 8]" in result.stdout

    def test_cap_notice_on_stderr(self, text_pdf):
        result = run_cli("search", text_pdf, "e", "--max", "2")
        assert result.returncode == 0
        assert len(json.loads(result.stdout)) == 2
        assert "capped" in result.stderr

    def test_no_match_empty_json(self, text_pdf):
        result = run_cli("search", text_pdf, "zebra quantum")
        assert result.returncode == 0
        assert json.loads(result.stdout) == []

    def test_invalid_regex_error(self, text_pdf):
        result = run_cli("search", text_pdf, "(unclosed", "--regex")
        assert result.returncode == 1
        assert "Invalid regular expression" in json.loads(result.stdout)["error"]

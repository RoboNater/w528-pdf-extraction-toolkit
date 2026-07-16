from conftest import TABLE_DATA

from pdfx import core


def test_extracts_table(table_pdf):
    tables = core.get_tables(table_pdf, "all")
    assert len(tables) == 1
    table = tables[0]
    assert table.physical_page == 1
    assert table.labeled_page is None
    assert table.index == 0
    assert table.rows == TABLE_DATA


def test_labeled_table(labeled_table_pdf):
    tables = core.get_tables(labeled_table_pdf, "all")
    assert tables[0].physical_page == 1
    assert tables[0].labeled_page == "30"


def test_page_without_tables(text_pdf):
    assert core.get_tables(text_pdf, "all") == []

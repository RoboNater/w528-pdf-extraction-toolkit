from conftest import TABLE_DATA

from pdfx import core


def test_extracts_table(table_pdf):
    tables = core.get_tables(table_pdf, "all")
    assert len(tables) == 1
    table = tables[0]
    assert table.page == 1
    assert table.index == 0
    assert table.rows == TABLE_DATA


def test_page_without_tables(text_pdf):
    assert core.get_tables(text_pdf, "all") == []

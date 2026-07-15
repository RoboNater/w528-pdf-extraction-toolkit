from pdfx import core


def test_all_pages(text_pdf):
    result = core.get_text(text_pdf, "all")
    assert [t.page for t in result] == [1, 2, 3]
    assert "This is page 2 of the test document." in result[1].text
    assert all(t.has_text for t in result)


def test_single_page(text_pdf):
    result = core.get_text(text_pdf, "2")
    assert len(result) == 1
    assert result[0].page == 2
    assert "Chapter Two" in result[0].text


def test_page_range(text_pdf):
    result = core.get_text(text_pdf, "2-3")
    assert [t.page for t in result] == [2, 3]


def test_layout_mode(text_pdf):
    result = core.get_text(text_pdf, "1", layout=True)
    assert result[0].page == 1
    assert "Chapter One" in result[0].text
    assert result[0].has_text is True


def test_blank_page_is_empty_not_error(blank_pdf):
    result = core.get_text(blank_pdf, "all")
    assert len(result) == 1
    assert result[0].text.strip() == ""
    assert result[0].has_text is False

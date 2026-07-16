from pdfx import core


def test_all_pages(text_pdf):
    result = core.get_text(text_pdf, "all")
    assert [t.physical_page for t in result] == [1, 2, 3]
    assert "This is page 2 of the test document." in result[1].text
    assert all(t.has_text for t in result)


def test_single_page(text_pdf):
    result = core.get_text(text_pdf, "2")
    assert len(result) == 1
    assert result[0].physical_page == 2
    assert "Chapter Two" in result[0].text


def test_page_range(text_pdf):
    result = core.get_text(text_pdf, "2-3")
    assert [t.physical_page for t in result] == [2, 3]


def test_layout_mode(text_pdf):
    result = core.get_text(text_pdf, "1", layout=True)
    assert result[0].physical_page == 1
    assert "Chapter One" in result[0].text
    assert result[0].has_text is True


def test_labels_used_by_default(labeled_pdf):
    result = core.get_text(labeled_pdf, "1")
    assert len(result) == 1
    assert result[0].physical_page == 8  # physical position of the page labeled "1"
    assert result[0].labeled_page == "1"
    assert "Physical page 8" in result[0].text


def test_physical_opt_out(labeled_pdf):
    result = core.get_text(labeled_pdf, "1", physical=True)
    assert result[0].physical_page == 1
    assert result[0].labeled_page == "cover"  # labels still reported with physical=True
    assert "Physical page 1" in result[0].text


def test_unlabeled_pdf_labeled_page_is_none(text_pdf):
    assert core.get_text(text_pdf, "2")[0].labeled_page is None


def test_label_range(labeled_pdf):
    result = core.get_text(labeled_pdf, "i-iii")
    assert [t.physical_page for t in result] == [5, 6, 7]


def test_label_not_found(labeled_pdf):
    import pytest

    from pdfx import PageSpecError

    with pytest.raises(PageSpecError, match="No page labeled"):
        core.get_text(labeled_pdf, "42")


def test_unlabeled_pdf_uses_physical_numbers(text_pdf):
    # no labels table: "2" means physical page 2, with or without physical=True
    assert core.get_text(text_pdf, "2")[0].physical_page == 2
    assert core.get_text(text_pdf, "2", physical=True)[0].physical_page == 2


def test_blank_page_is_empty_not_error(blank_pdf):
    result = core.get_text(blank_pdf, "all")
    assert len(result) == 1
    assert result[0].text.strip() == ""
    assert result[0].has_text is False

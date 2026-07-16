from pdfx import core


def test_page_count_and_metadata(text_pdf):
    index = core.get_index(text_pdf)
    assert index.page_count == 3
    assert index.metadata.title == "Test Document"
    assert index.metadata.author == "pdfx tests"


def test_page_summaries(text_pdf):
    index = core.get_index(text_pdf)
    assert [p.page for p in index.pages] == [1, 2, 3]
    first = index.pages[0]
    assert round(first.width) == 612  # letter size in points
    assert round(first.height) == 792
    assert first.rotation == 0
    assert all(p.has_text for p in index.pages)


def test_outline(text_pdf):
    index = core.get_index(text_pdf)
    titles = [item.title for item in index.outline]
    assert titles == ["Chapter One", "Chapter Two", "Chapter Three"]
    assert [item.page for item in index.outline] == [1, 2, 3]
    chapter_two = index.outline[1]
    assert [c.title for c in chapter_two.children] == ["Section 2.1"]
    assert chapter_two.children[0].page == 2


def test_blank_page_has_no_text(blank_pdf):
    index = core.get_index(blank_pdf)
    assert index.page_count == 1
    assert index.pages[0].has_text is False


def test_no_outline(blank_pdf):
    index = core.get_index(blank_pdf)
    assert index.outline == []


def test_page_labels_in_index(labeled_pdf):
    from conftest import LABELED_PDF_LABELS

    index = core.get_index(labeled_pdf)
    assert index.has_page_labels is True
    assert [p.label for p in index.pages] == LABELED_PDF_LABELS


def test_unlabeled_pdf_has_no_labels(text_pdf):
    index = core.get_index(text_pdf)
    assert index.has_page_labels is False
    assert all(p.label is None for p in index.pages)


def test_get_page_labels(labeled_pdf, text_pdf):
    from conftest import LABELED_PDF_LABELS

    assert core.get_page_labels(labeled_pdf) == LABELED_PDF_LABELS
    assert core.get_page_labels(text_pdf) is None

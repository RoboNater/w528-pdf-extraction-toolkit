from pathlib import Path

from conftest import requires_poppler

from pdfx import core

pytestmark = requires_poppler


def test_render_range(text_pdf, tmp_path):
    result = core.render_pages(text_pdf, "1-2", tmp_path, dpi=72)
    assert [r.page for r in result] == [1, 2]
    for rendered in result:
        path = Path(rendered.path)
        assert path.exists()
        assert path.suffix == ".png"
        # letter is 612x792 points; at 72 dpi that is 612x792 pixels
        assert abs(rendered.width - 612) <= 2
        assert abs(rendered.height - 792) <= 2
        assert rendered.dpi == 72


def test_render_non_contiguous(text_pdf, tmp_path):
    result = core.render_pages(text_pdf, "1,3", tmp_path, dpi=72)
    assert [r.page for r in result] == [1, 3]


def test_render_dpi_scales(text_pdf, tmp_path):
    result = core.render_pages(text_pdf, "1", tmp_path, dpi=144)
    assert abs(result[0].width - 1224) <= 4


def test_render_jpeg(text_pdf, tmp_path):
    result = core.render_pages(text_pdf, "1", tmp_path, dpi=72, fmt="jpeg")
    assert Path(result[0].path).suffix == ".jpg"
    assert Path(result[0].path).exists()

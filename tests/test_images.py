from pathlib import Path

from conftest import IMAGE_SIZE

from pdfx import core


def test_metadata_only(image_pdf):
    images = core.get_images(image_pdf, "all", out_dir=None)
    assert len(images) == 1
    info = images[0]
    assert info.page == 1
    assert info.index == 0
    assert (info.width, info.height) == IMAGE_SIZE
    assert info.saved_path is None


def test_save_to_dir(image_pdf, tmp_path):
    out = tmp_path / "imgs"
    images = core.get_images(image_pdf, "all", out_dir=out)
    assert len(images) == 1
    saved = Path(images[0].saved_path)
    assert saved.exists()
    assert saved.stat().st_size > 0
    assert saved.parent == out


def test_page_without_images(text_pdf):
    assert core.get_images(text_pdf, "all", out_dir=None) == []

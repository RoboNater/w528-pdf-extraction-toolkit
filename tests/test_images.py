from pathlib import Path

from conftest import IMAGE_SIZE

from pdfx import core


def test_metadata_only(image_pdf):
    images = core.get_images(image_pdf, "all", out_dir=None)
    assert len(images) == 1
    info = images[0]
    assert info.physical_page == 1
    assert info.labeled_page is None
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


def test_labeled_image_filenames(labeled_image_pdf, tmp_path):
    images = core.get_images(labeled_image_pdf, "all", out_dir=tmp_path)
    assert images[0].labeled_page == "30"
    assert Path(images[0].saved_path).name.startswith("page0030_pp0001_img00")


def test_page_stem():
    assert core.page_stem(7) == "page0007"
    assert core.page_stem(7, "30") == "page0030_pp0007"
    assert core.page_stem(5, "iv") == "pageiv_pp0005"
    assert core.page_stem(1, "cover") == "pagecover_pp0001"
    assert core.page_stem(2, "A/B:1") == "pageA_B_1_pp0002"  # unsafe chars sanitized

import pytest
from conftest import ENCRYPTED_PASSWORD

from pdfx import PageSpecError, core


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        core.get_index(tmp_path / "nope.pdf")


def test_not_a_pdf(not_a_pdf):
    with pytest.raises(core.InvalidPdfError):
        core.get_index(not_a_pdf)


def test_encrypted_requires_password(encrypted_pdf):
    with pytest.raises(core.PasswordError, match="password"):
        core.get_index(encrypted_pdf)


def test_encrypted_wrong_password(encrypted_pdf):
    with pytest.raises(core.PasswordError):
        core.get_index(encrypted_pdf, password="wrong")


def test_encrypted_correct_password(encrypted_pdf):
    result = core.get_text(encrypted_pdf, "1", password=ENCRYPTED_PASSWORD)
    assert "Chapter One" in result[0].text


def test_page_out_of_range(text_pdf):
    with pytest.raises(PageSpecError, match="1-3"):
        core.get_text(text_pdf, "9")


def test_bad_page_spec(text_pdf):
    with pytest.raises(PageSpecError):
        core.get_text(text_pdf, "one")

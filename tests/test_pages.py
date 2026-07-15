import pytest

from pdfx.pages import PageSpecError, parse_pages


class TestParsePages:
    def test_all(self):
        assert parse_pages("all", 4) == [1, 2, 3, 4]

    def test_all_case_insensitive(self):
        assert parse_pages("ALL", 2) == [1, 2]

    def test_single_page(self):
        assert parse_pages("5", 10) == [5]

    def test_range(self):
        assert parse_pages("3-7", 10) == [3, 4, 5, 6, 7]

    def test_mixed_list(self):
        assert parse_pages("1,3-5,9", 10) == [1, 3, 4, 5, 9]

    def test_whitespace_tolerated(self):
        assert parse_pages(" 1 , 3 - 5 ", 10) == [1, 3, 4, 5]

    def test_duplicates_removed_and_sorted(self):
        assert parse_pages("9,1,3,1-3", 10) == [1, 2, 3, 9]

    def test_single_page_range(self):
        assert parse_pages("4-4", 10) == [4]

    def test_last_page(self):
        assert parse_pages("10", 10) == [10]


class TestParsePagesErrors:
    def test_zero_page(self):
        with pytest.raises(PageSpecError, match="1-10"):
            parse_pages("0", 10)

    def test_page_beyond_end(self):
        with pytest.raises(PageSpecError, match="1-10"):
            parse_pages("11", 10)

    def test_range_beyond_end(self):
        with pytest.raises(PageSpecError, match="1-10"):
            parse_pages("8-12", 10)

    def test_reversed_range(self):
        with pytest.raises(PageSpecError):
            parse_pages("7-3", 10)

    def test_not_a_number(self):
        with pytest.raises(PageSpecError):
            parse_pages("abc", 10)

    def test_empty_spec(self):
        with pytest.raises(PageSpecError):
            parse_pages("", 10)

    def test_empty_list_item(self):
        with pytest.raises(PageSpecError):
            parse_pages("1,,3", 10)

    def test_malformed_range(self):
        with pytest.raises(PageSpecError):
            parse_pages("1-2-3", 10)

    def test_negative_page(self):
        with pytest.raises(PageSpecError):
            parse_pages("-2", 10)

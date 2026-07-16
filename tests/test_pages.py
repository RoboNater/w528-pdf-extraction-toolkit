import pytest

from pdfx.pages import PageSpecError, parse_page_labels, parse_pages

# physical pages 1-10: cover, FM1-FM3, i-iii, then content pages 1-3
LABELS = ["cover", "FM1", "FM2", "FM3", "i", "ii", "iii", "1", "2", "3"]
HYPHEN_LABELS = ["A-1", "A-2", "B-1"]


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


class TestParsePageLabels:
    def test_all(self):
        assert parse_page_labels("all", LABELS) == list(range(1, 11))

    def test_single_label(self):
        assert parse_page_labels("FM2", LABELS) == [3]

    def test_numeric_label_resolves_to_labeled_page(self):
        assert parse_page_labels("1", LABELS) == [8]

    def test_roman_range(self):
        assert parse_page_labels("i-iii", LABELS) == [5, 6, 7]

    def test_decimal_range(self):
        assert parse_page_labels("1-3", LABELS) == [8, 9, 10]

    def test_range_across_schemes(self):
        assert parse_page_labels("FM3-ii", LABELS) == [4, 5, 6]

    def test_mixed_list(self):
        assert parse_page_labels("cover,FM2,2", LABELS) == [1, 3, 9]

    def test_case_insensitive_fallback(self):
        assert parse_page_labels("fm2", LABELS) == [3]

    def test_whitespace_tolerated(self):
        assert parse_page_labels(" cover , 1 - 2 ", LABELS) == [1, 8, 9]

    def test_exact_label_wins_over_range(self):
        assert parse_page_labels("A-1", HYPHEN_LABELS) == [1]

    def test_range_of_hyphenated_labels(self):
        assert parse_page_labels("A-1-B-1", HYPHEN_LABELS) == [1, 2, 3]

    def test_unknown_label(self):
        with pytest.raises(PageSpecError, match="No page labeled"):
            parse_page_labels("xyz", LABELS)

    def test_reversed_label_range(self):
        with pytest.raises(PageSpecError, match="Reversed"):
            parse_page_labels("iii-i", LABELS)

    def test_empty_spec(self):
        with pytest.raises(PageSpecError):
            parse_page_labels("", LABELS)

    def test_empty_list_item(self):
        with pytest.raises(PageSpecError):
            parse_page_labels("cover,,1", LABELS)


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

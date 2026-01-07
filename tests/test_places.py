"""Tests for places API endpoints and helper functions."""

import pytest

from api.routers.places import (
    _format_label_value,
    _extract_numeric_value,
    _sort_items,
)
from api.models import PlaceItemResponse


class TestFormatLabelValue:
    """Tests for _format_label_value function."""

    def test_float_whole_number_converts_to_int(self):
        """Float values that are whole numbers should display as integers."""
        assert _format_label_value(1.0) == "1"
        assert _format_label_value(10.0) == "10"
        assert _format_label_value(100.0) == "100"

    def test_float_with_decimal_stays_float(self):
        """Float values with decimals should stay as floats."""
        assert _format_label_value(1.5) == "1.5"
        assert _format_label_value(10.25) == "10.25"

    def test_integer_stays_integer(self):
        """Integer values should display as integers."""
        assert _format_label_value(1) == "1"
        assert _format_label_value(10) == "10"

    def test_string_stays_string(self):
        """String values should pass through unchanged."""
        assert _format_label_value("Ward 1") == "Ward 1"
        assert _format_label_value("District A") == "District A"

    def test_zero_handling(self):
        """Zero should be handled correctly in both int and float forms."""
        assert _format_label_value(0) == "0"
        assert _format_label_value(0.0) == "0"

    def test_negative_numbers(self):
        """Negative numbers should be handled correctly."""
        assert _format_label_value(-1.0) == "-1"
        assert _format_label_value(-1.5) == "-1.5"


class TestExtractNumericValue:
    """Tests for _extract_numeric_value function."""

    def test_pure_number_string(self):
        """Pure number strings should extract correctly."""
        assert _extract_numeric_value("5") == 5.0
        assert _extract_numeric_value("10") == 10.0
        assert _extract_numeric_value("100") == 100.0

    def test_number_with_prefix(self):
        """Numbers with text prefixes should extract the number."""
        assert _extract_numeric_value("Ward 5") == 5.0
        assert _extract_numeric_value("District 10") == 10.0

    def test_number_with_suffix(self):
        """Numbers with text suffixes should extract the number."""
        assert _extract_numeric_value("5th Ward") == 5.0

    def test_padded_number(self):
        """Zero-padded numbers should extract correctly."""
        assert _extract_numeric_value("05") == 5.0
        assert _extract_numeric_value("001") == 1.0

    def test_no_number_returns_none(self):
        """Strings without numbers should return None."""
        assert _extract_numeric_value("Downtown") is None
        assert _extract_numeric_value("Lincoln Park") is None

    def test_first_number_extracted(self):
        """When multiple numbers exist, the first should be extracted."""
        assert _extract_numeric_value("Area 5 Zone 10") == 5.0


class TestSortItems:
    """Tests for _sort_items function."""

    def _make_items(self, names: list[str]) -> list[PlaceItemResponse]:
        """Helper to create PlaceItemResponse objects."""
        return [
            PlaceItemResponse(id=str(i), name=name, display_name=name)
            for i, name in enumerate(names)
        ]

    def test_alphabetic_sort(self):
        """Alphabetic sort should order case-insensitively."""
        items = self._make_items(["Zebra", "apple", "Banana"])
        sorted_items = _sort_items(items, "alphabetic")
        assert [i.name for i in sorted_items] == ["apple", "Banana", "Zebra"]

    def test_numeric_sort_pure_numbers(self):
        """Numeric sort should order numbers correctly."""
        items = self._make_items(["10", "2", "1", "20"])
        sorted_items = _sort_items(items, "numeric")
        assert [i.name for i in sorted_items] == ["1", "2", "10", "20"]

    def test_numeric_sort_with_prefix(self):
        """Numeric sort should handle prefixed numbers."""
        items = self._make_items(["Ward 10", "Ward 2", "Ward 1"])
        sorted_items = _sort_items(items, "numeric")
        assert [i.name for i in sorted_items] == ["Ward 1", "Ward 2", "Ward 10"]

    def test_numeric_sort_non_numeric_at_end(self):
        """Non-numeric items should sort to the end in numeric mode."""
        items = self._make_items(["Ward 2", "Downtown", "Ward 1"])
        sorted_items = _sort_items(items, "numeric")
        assert [i.name for i in sorted_items] == ["Ward 1", "Ward 2", "Downtown"]

    def test_natural_sort(self):
        """Natural sort should handle mixed alphanumeric strings."""
        items = self._make_items(["item10", "item2", "item1"])
        sorted_items = _sort_items(items, "natural")
        assert [i.name for i in sorted_items] == ["item1", "item2", "item10"]

    def test_default_is_alphabetic(self):
        """Unknown sort types should default to alphabetic."""
        items = self._make_items(["c", "a", "b"])
        sorted_items = _sort_items(items, "unknown")
        assert [i.name for i in sorted_items] == ["a", "b", "c"]

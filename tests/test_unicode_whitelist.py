"""Parsing and membership for rule C13's `unicodeWhitelist`."""
import pytest

from commentlint import unicode_whitelist


class TestParseEntry:
    def test_int_is_a_single_codepoint(self):
        assert unicode_whitelist.parse_entry(0x2014) == (0x2014, 0x2014)

    def test_bool_is_rejected(self):
        with pytest.raises(unicode_whitelist.WhitelistError):
            unicode_whitelist.parse_entry(True)

    def test_single_hex_codepoint(self):
        assert unicode_whitelist.parse_entry("U+2014") == (0x2014, 0x2014)

    def test_lowercase_hex_digits_are_accepted(self):
        assert unicode_whitelist.parse_entry("U+2a14") == (0x2A14, 0x2A14)

    def test_lowercase_u_prefix_is_accepted(self):
        assert unicode_whitelist.parse_entry("u+2014") == (0x2014, 0x2014)

    def test_range(self):
        assert unicode_whitelist.parse_entry("U+2010-U+2015") == (0x2010, 0x2015)

    def test_backwards_range_is_an_error(self):
        with pytest.raises(unicode_whitelist.WhitelistError, match="after its end"):
            unicode_whitelist.parse_entry("U+2015-U+2010")

    def test_garbage_string_is_an_error(self):
        with pytest.raises(unicode_whitelist.WhitelistError):
            unicode_whitelist.parse_entry("em dash")

    def test_float_is_an_error(self):
        with pytest.raises(unicode_whitelist.WhitelistError):
            unicode_whitelist.parse_entry(8212.0)

    def test_codepoint_past_the_unicode_range_is_an_error(self):
        with pytest.raises(unicode_whitelist.WhitelistError, match="outside the Unicode range"):
            unicode_whitelist.parse_entry("U+110000")

    def test_negative_int_is_an_error(self):
        with pytest.raises(unicode_whitelist.WhitelistError, match="outside the Unicode range"):
            unicode_whitelist.parse_entry(-1)

    def test_range_end_past_the_unicode_range_is_an_error(self):
        with pytest.raises(unicode_whitelist.WhitelistError, match="outside the Unicode range"):
            unicode_whitelist.parse_entry("U+2010-U+110000")


class TestContains:
    def test_single_codepoint_matches_only_itself(self):
        ranges = unicode_whitelist.parse(["U+2014"])
        assert unicode_whitelist.contains(ranges, 0x2014)
        assert not unicode_whitelist.contains(ranges, 0x2015)

    def test_range_is_inclusive_on_both_ends(self):
        ranges = unicode_whitelist.parse(["U+2010-U+2015"])
        assert unicode_whitelist.contains(ranges, 0x2010)
        assert unicode_whitelist.contains(ranges, 0x2015)
        assert not unicode_whitelist.contains(ranges, 0x2016)

    def test_empty_whitelist_matches_nothing(self):
        assert not unicode_whitelist.contains([], 0x2014)

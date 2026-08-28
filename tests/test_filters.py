"""Rule C13's character-level check: disallowed_codepoints."""
from commentlint.comments import filters


class TestDisallowedCodepoints:
    def test_plain_ascii_is_clean(self):
        assert filters.disallowed_codepoints("plain old ascii comment text", []) == []

    def test_latin1_accented_letters_are_allowed(self):
        assert filters.disallowed_codepoints("café naïve", []) == []

    def test_em_dash_is_flagged(self):
        assert filters.disallowed_codepoints("an em dash — here", []) == [0x2014]

    def test_distinct_codepoints_are_deduplicated_in_first_seen_order(self):
        text = "— twice — then ‘quoted’"
        assert filters.disallowed_codepoints(text, []) == [0x2014, 0x2018, 0x2019]

    def test_whitelisted_codepoint_is_not_flagged(self):
        whitelist = [(0x2014, 0x2014)]
        assert filters.disallowed_codepoints("an em dash — here", whitelist) == []

    def test_whitelisted_range_covers_only_its_span(self):
        whitelist = [(0x2018, 0x201F)]
        text = "‘quoted’ and an em dash —"
        assert filters.disallowed_codepoints(text, whitelist) == [0x2014]

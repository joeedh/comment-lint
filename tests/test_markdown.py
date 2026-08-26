"""Markdown extraction: what markdown-it-py hands back, verified rather than assumed."""
from commentlint.comments import markdown
from commentlint.comments.filters import classify_markdown


def by_line(comments):
    return {c.line: c for c in comments}


class TestExtraction:
    def test_paragraph(self):
        src = "A paragraph with real prose in it, long enough to matter here.\n"
        out = markdown.extract("x.md", src)
        assert len(out) == 1
        assert out[0].line == 1
        assert out[0].kind == "prose"
        assert out[0].text == src.strip()

    def test_heading_markers_are_already_gone(self):
        src = "## Closed heading text ##\n"
        out = markdown.extract("x.md", src)
        assert out[0].text == "Closed heading text"

    def test_list_item_tight_and_loose(self):
        src = (
            "- a loose item with a lot of text so it is a real prose paragraph here\n"
            "\n"
            "- another loose item with a lot of text so it is a real prose paragraph here\n"
        )
        out = markdown.extract("x.md", src)
        lines = by_line(out)
        assert lines[1].text.startswith("a loose item")
        assert lines[3].text.startswith("another loose item")

    def test_blockquote_marker_is_already_gone(self):
        src = "> quoted line one that is long enough to be worth checking here\n> continued\n"
        out = markdown.extract("x.md", src)
        assert out[0].text == "quoted line one that is long enough to be worth checking here continued"
        assert out[0].line == 1

    def test_inline_code_span_survives(self):
        src = "A paragraph mentioning `some_code()` inline, long enough to matter.\n"
        out = markdown.extract("x.md", src)
        assert "`some_code()`" in out[0].text


class TestExclusions:
    def test_fenced_code_produces_no_chunk(self):
        src = "```\nfenced code block contents here\n```\n"
        assert markdown.extract("x.md", src) == []

    def test_indented_code_produces_no_chunk(self):
        src = "    indented code block contents here\n"
        assert markdown.extract("x.md", src) == []

    def test_raw_html_block_produces_no_chunk(self):
        src = "<div>\nraw html block contents here\n</div>\n"
        assert markdown.extract("x.md", src) == []


class TestFrontMatter:
    def test_leading_front_matter_is_skipped(self):
        src = "---\ntitle: Foo\n---\n\nBody paragraph long enough to be worth checking here.\n"
        out = markdown.extract("x.md", src)
        assert len(out) == 1
        assert "title" not in out[0].text
        assert out[0].text == "Body paragraph long enough to be worth checking here."

    def test_later_thematic_break_is_not_mistaken_for_the_closing_delimiter(self):
        src = (
            "---\n"
            "title: Foo\n"
            "---\n"
            "\n"
            "Body paragraph long enough to be worth checking here.\n"
            "\n"
            "---\n"
            "\n"
            "Another paragraph long enough to be worth checking after the break.\n"
        )
        out = markdown.extract("x.md", src)
        texts = [c.text for c in out]
        assert "Body paragraph long enough to be worth checking here." in texts
        assert "Another paragraph long enough to be worth checking after the break." in texts

    def test_non_front_matter_leading_rule_is_left_alone(self):
        """A leading thematic break with no closing delimiter is not front matter."""
        src = "---\n\nA paragraph after a plain leading rule, long enough to matter here.\n"
        out = markdown.extract("x.md", src)
        assert len(out) == 1
        assert out[0].text.startswith("A paragraph after")


class TestClassifyMarkdown:
    def test_short_text_is_skipped(self):
        assert classify_markdown("short") == "skip"

    def test_long_text_is_prose(self):
        assert classify_markdown("x" * 41) == "prose"

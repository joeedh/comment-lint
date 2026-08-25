"""Extractor tests, weighted toward the cases a regex would get wrong."""
import pytest

from commentlint.comments import extract
from commentlint.comments.normalize import normalize
from commentlint.comments.pysrc import UnparseableSource


def texts(src, path="t.ts"):
    return [c.text for c in extract(path, src)]


def kinds(src, path="t.ts"):
    return [c.kind for c in extract(path, src)]


class TestSlashDisambiguation:
    def test_division_is_not_a_regex(self):
        assert texts("const a = b / c / d; // real") == ["real"]

    def test_regex_literal_hides_its_slashes(self):
        assert texts("const a = /foo/.test(x); // real") == ["real"]

    def test_regex_char_class_can_hold_a_comment_opener(self):
        assert texts("const r = /[/*]/g; // real") == ["real"]

    def test_regex_after_return(self):
        assert texts("function f() { return /a//b/; } // real") == ["real"]

    def test_division_after_paren(self):
        assert texts("const a = (b) / c; // real") == ["real"]

    def test_escaped_slash_in_regex(self):
        assert texts(r"const r = /a\/b/; // real") == ["real"]


class TestStrings:
    def test_url_in_a_string_is_not_a_comment(self):
        assert texts('const u = "http://x.com//y"; // real') == ["real"]

    def test_comment_opener_in_single_quotes(self):
        assert texts("const s = '/* not a comment */'; // real") == ["real"]

    def test_escaped_quote(self):
        assert texts(r'const s = "a\"//b"; // real') == ["real"]

    def test_unterminated_string_damages_only_its_line(self):
        src = 'const s = "oops;\nconst ok = 1; // found\n'
        assert texts(src) == ["found"]


class TestTemplates:
    def test_no_comment_inside_a_template(self):
        assert texts("const t = `text // not a comment`;") == []

    def test_comment_inside_an_interpolation(self):
        assert texts("const t = `a ${ b /* inner */ } c`; // outer") == ["inner", "outer"]

    def test_nested_template_interpolation(self):
        assert texts("const t = `${ `${ x /* deep */ }` }`;") == ["deep"]

    def test_template_spanning_lines_keeps_line_numbers(self):
        src = "const t = `a\nb\nc`;\n// after"
        got = extract("t.ts", src)
        assert [(c.line, c.text) for c in got] == [(4, "after")]


class TestBlocks:
    def test_doc_versus_block(self):
        assert kinds("/** d */\n/* b */") == ["doc", "block"]

    def test_empty_block_comment(self):
        assert texts("/**/") == [""]

    def test_unterminated_block_runs_to_eof(self):
        assert texts("/* open\nstill open") == ["open\nstill open"]

    def test_continuation_stars_are_stripped(self):
        assert texts("/*\n * one\n * two\n */") == ["one\ntwo"]

    def test_interior_asterisks_survive(self):
        # *emphasis* is 774:10 violation-to-clean in the corpus, the P10 signal
        assert texts("/* the *emph* stays */") == ["the *emph* stays"]

    def test_backticks_survive(self):
        assert texts("/* the `keys/` dir */") == ["the `keys/` dir"]


class TestRuns:
    """A run of `//` lines is one comment, not one comment per line."""

    def test_consecutive_line_comments_merge(self):
        assert texts("// first part,\n// and the rest.") == ["first part,\nand the rest."]

    def test_a_gap_breaks_the_run(self):
        assert texts("// one\n\n// two") == ["one", "two"]

    def test_different_indentation_breaks_the_run(self):
        assert texts("// one\n  // two") == ["one", "two"]

    def test_a_trailing_comment_does_not_join_a_run(self):
        assert texts("let x = 1; // trailing\n// standalone") == ["trailing", "standalone"]

    def test_a_run_longer_than_two_lines_stays_one_comment(self):
        # a merged comment keeps its first line number, so the adjacency test
        # has to measure from the run's end or the third line splits off
        assert texts("// one\n// two\n// three") == ["one\ntwo\nthree"]

    def test_merged_run_keeps_the_first_line_number(self):
        got = extract("t.ts", "\n// a\n// b")
        assert [(c.line, c.col) for c in got] == [(2, 1)]

    def test_block_comments_do_not_merge(self):
        assert texts("/* one */\n/* two */") == ["one", "two"]


class TestKinds:
    def test_trailing_versus_standalone(self):
        assert kinds("let x = 1; // trailing\n// standalone") == ["trailing", "line"]

    def test_indented_line_comment_is_standalone(self):
        assert kinds("if (a) {\n  // standalone\n}") == ["line"]


class TestPositions:
    def test_line_and_column_are_one_based(self):
        c = extract("t.ts", "\n\n  // here")[0]
        assert (c.line, c.col) == (3, 3)

    def test_crlf_does_not_shift_columns(self):
        c = extract("t.ts", "let x = 1;\r\n// here")[0]
        assert (c.line, c.col, c.text) == (2, 1, "here")


class TestNormalize:
    def test_tags_truncate(self):
        assert normalize("/**\n * prose here\n * @param x the x\n */") == "prose here"

    def test_tag_only_docblock_is_empty(self):
        assert normalize("/**\n * @returns nothing\n */") == ""

    def test_trailing_close_marker_is_removed(self):
        # the corpus leaves this on 10.9% of texts; it is worth +0.09..0.19 of
        # spurious gate score, so live text must not carry it
        assert normalize("/* prose here */") == "prose here"

    def test_internal_spacing_and_newlines_survive(self):
        assert normalize("/*\n * a  b\n *\n * c\n */") == "a  b\n\nc"


class TestPython:
    def test_hash_comments_merge_into_a_run(self):
        assert texts("# one\n# two\nx = 1\n", "t.py") == ["one\ntwo"]

    def test_a_blank_line_breaks_the_run(self):
        assert texts("# one\n\n# two\n", "t.py") == ["one", "two"]

    def test_trailing_hash_comment(self):
        assert kinds("x = 1  # trailing\n", "t.py") == ["trailing"]

    def test_hash_in_a_string_is_not_a_comment(self):
        assert texts('s = "# not a comment"\n', "t.py") == []

    def test_docstrings_are_extracted(self):
        assert texts('def f():\n    """The doc."""\n', "t.py") == ["The doc."]

    def test_fstring_with_nested_quotes(self):
        assert texts("s = f'{d[\"k\"]}'  # real\n", "t.py") == ["real"]

    def test_broken_python_is_reported_not_guessed(self):
        with pytest.raises(UnparseableSource):
            extract("t.py", "def (:\n")


class TestEncoding:
    def test_bom_is_stripped_by_the_reader(self, tmp_path):
        from commentlint.comments import extract_file

        p = tmp_path / "t.ts"
        p.write_bytes(b"\xef\xbb\xbf// after a bom")
        assert [c.text for c in extract_file(str(p))] == ["after a bom"]

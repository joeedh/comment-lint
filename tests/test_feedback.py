"""The false-negative ledger: what one report writes, and what the CLI accepts."""
import json

import pytest

from commentlint import feedback
from commentlint.cli import EXIT_CLEAN, EXIT_USAGE, main

MISSED = "// The leak scan is the refusal, and the refusal is what the caller reads back."


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path / feedback.LEDGER_NAME


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestLedger:
    def test_a_missing_file_reads_as_no_entries(self, tmp_path):
        assert feedback.load(str(tmp_path / "nope.json")) == []

    def test_an_empty_file_reads_as_no_entries(self, tmp_path):
        p = tmp_path / feedback.LEDGER_NAME
        p.write_text("", encoding="utf-8")
        assert feedback.load(str(p)) == []

    def test_malformed_json_is_an_error(self, tmp_path):
        p = tmp_path / feedback.LEDGER_NAME
        p.write_text("{oops", encoding="utf-8")
        with pytest.raises(feedback.LedgerError):
            feedback.load(str(p))

    def test_a_json_object_is_an_error(self, tmp_path):
        p = tmp_path / feedback.LEDGER_NAME
        p.write_text('{"a": 1}', encoding="utf-8")
        with pytest.raises(feedback.LedgerError, match="array"):
            feedback.load(str(p))

    def test_append_keeps_earlier_entries(self, tmp_path):
        p = str(tmp_path / feedback.LEDGER_NAME)
        feedback.append(p, feedback.entry("first"))
        assert feedback.append(p, feedback.entry("second")) == 2
        assert [e["text"] for e in feedback.load(p)] == ["first", "second"]

    def test_absent_optional_fields_are_left_out(self):
        assert set(feedback.entry("t")) == {"kind", "recorded", "version", "text"}

    def test_notes_and_revisions_are_kept(self):
        e = feedback.entry("t", note="reads as an epigram", revision="Refuses on a known name.")
        assert e["note"] == "reads as an epigram"
        assert e["revision"] == "Refuses on a known name."


class TestCli:
    def test_a_report_exits_clean_and_writes_the_ledger(self, ledger, capsys):
        assert main(["--false-negative", MISSED]) == EXIT_CLEAN
        entries = read(ledger)
        assert len(entries) == 1
        assert entries[0]["text"] == MISSED
        assert entries[0]["kind"] == feedback.FALSE_NEGATIVE

    def test_the_optional_arguments_reach_the_entry(self, ledger, capsys):
        main(["--false-negative", MISSED, "--note", "metaphor", "--revision", "// Refuses."])
        e = read(ledger)[0]
        assert e["note"] == "metaphor" and e["revision"] == "// Refuses."

    def test_reports_accumulate(self, ledger, capsys):
        main(["--false-negative", "one"])
        main(["--false-negative", "two"])
        assert len(read(ledger)) == 2

    def test_the_ledger_flag_chooses_the_file(self, tmp_path, capsys):
        p = tmp_path / "sub" / "ledger.json"
        main(["--false-negative", MISSED, "--ledger", str(p)])
        assert read(p)[0]["text"] == MISSED

    def test_stdin_carries_a_multiline_comment(self, ledger, capsys, monkeypatch):
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO("/* line one\n   line two */\n"))
        main(["--false-negative", "-"])
        assert read(ledger)[0]["text"].startswith("/* line one")

    def test_empty_text_is_a_usage_error(self, ledger, capsys):
        assert main(["--false-negative", "   "]) == EXIT_USAGE
        assert not ledger.exists()

    def test_a_note_without_a_report_is_a_usage_error(self, ledger, capsys):
        assert main(["--note", "orphan", "--no-cache"]) == EXIT_USAGE
        assert "--false-negative" in capsys.readouterr().err

    def test_a_corrupt_ledger_exits_two_rather_than_overwriting_it(self, ledger, capsys):
        ledger.write_text("{oops", encoding="utf-8")
        assert main(["--false-negative", MISSED]) == EXIT_USAGE
        assert ledger.read_text(encoding="utf-8") == "{oops"

    def test_json_output_names_the_ledger(self, ledger, capsys):
        main(["--false-negative", MISSED, "--json"])
        out = json.loads(capsys.readouterr().out)
        assert out["entries"] == 1 and out["recorded"]["text"] == MISSED

    def test_reporting_never_loads_the_model(self, ledger, capsys, monkeypatch):
        import sys

        monkeypatch.delitem(sys.modules, "commentlint.backends", raising=False)
        main(["--false-negative", MISSED])
        assert "commentlint.backends" not in sys.modules

"""Config resolution, argument disambiguation, output shapes and exit codes."""
import json

import pytest

from commentlint import ENCODER_DIR, LINEAR_DIR
from commentlint import config as config_mod
from commentlint.cli import EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, build_parser, looks_like_path, main

BAD = "// The leak scan is the refusal, and the refusal is what the caller reads back.\n"
PLAIN = "// increment the counter by one before the next loop iteration runs here\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "a.ts").write_text(BAD, encoding="utf-8")
    (tmp_path / "b.ts").write_text(PLAIN, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(argv, capsys):
    code = main(argv + ["--no-cache"])
    return code, capsys.readouterr().out


class TestConfig:
    def test_nearest_config_wins(self, tmp_path):
        (tmp_path / ".commentlintrc.json").write_text('{"threshold": 0.1}', encoding="utf-8")
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        (tmp_path / "a" / ".commentlintrc.json").write_text('{"threshold": 0.9}', encoding="utf-8")
        assert config_mod.load(config_mod.find(str(deep)))["threshold"] == 0.9

    def test_search_stops_at_the_root(self, tmp_path):
        assert config_mod.find(str(tmp_path)) is None

    def test_unknown_key_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"thresold": 0.5}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="thresold"):
            config_mod.load(str(p))

    def test_wrong_type_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"threshold": "high"}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="threshold"):
            config_mod.load(str(p))

    def test_malformed_json_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text("{oops", encoding="utf-8")
        with pytest.raises(config_mod.ConfigError):
            config_mod.load(str(p))

    def test_model_path_resolves_against_the_config(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"model": "m"}', encoding="utf-8")
        assert config_mod.load(str(p))["model"].endswith("m")

    def test_cli_overrides_config(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.01}', encoding="utf-8")
        _, out = run([".", "--threshold", "0.99"], capsys)
        assert "cut 0.99" in out

    def test_config_applies_when_the_cli_is_silent(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.42}', encoding="utf-8")
        _, out = run(["."], capsys)
        assert "cut 0.42" in out

    def test_no_config_ignores_the_file(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.42}', encoding="utf-8")
        _, out = run([".", "--no-config"], capsys)
        assert "cut 0.70" in out

    def test_bad_config_exits_two(self, project, capsys):
        (project / ".commentlintrc.json").write_text("{oops", encoding="utf-8")
        assert main([".", "--no-cache"]) == EXIT_USAGE


class TestArgumentDisambiguation:
    def test_a_path_that_exists_is_a_path(self, project):
        assert looks_like_path("a.ts")

    def test_a_glob_is_a_path(self):
        assert looks_like_path("**/*.ts")

    def test_a_sentence_is_not_a_path(self):
        assert not looks_like_path("the leak scan is the refusal")

    def test_a_bare_word_is_a_path_so_typos_report_themselves(self):
        assert looks_like_path("nope")

    def test_bare_text_still_scores_one_comment(self, project, capsys):
        code, out = run(["the leak scan is the refusal"], capsys)
        assert "VIOLATION" in out or "clean" in out
        assert code in (EXIT_CLEAN, EXIT_FINDINGS)

    def test_text_flag_forces_the_literal_reading(self, project, capsys):
        _, out = run(["--text", "a.ts"], capsys)
        assert "VIOLATION" in out or "clean" in out


class TestScanOutput:
    def test_findings_exit_one(self, project, capsys):
        code, _ = run([".", "--threshold", "0.01"], capsys)
        assert code == EXIT_FINDINGS

    def test_clean_exits_zero(self, project, capsys):
        code, _ = run([".", "--threshold", "0.999"], capsys)
        assert code == EXIT_CLEAN

    def test_missing_path_exits_two(self, project, capsys):
        assert main(["nope", "--no-cache"]) == EXIT_USAGE

    def test_quiet_prints_only_the_summary(self, project, capsys):
        _, out = run([".", "--quiet", "--threshold", "0.01"], capsys)
        assert "files" in out and ":" not in out.split("\n")[0]

    def test_json_is_valid_and_carries_a_summary(self, project, capsys):
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert data["summary"]["filesScanned"] == 2
        assert {"path", "findings"} <= set(data["files"][0])

    def test_json_findings_carry_provenance(self, project, capsys):
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        for f in [f for fl in json.loads(out)["files"] for f in fl["findings"]]:
            assert f["source"] in ("model", "heuristic")
            assert {"line", "col", "rule", "score", "ranked", "text"} <= set(f)

    def test_limit_says_what_it_hid(self, project, capsys):
        _, out = run([".", "--threshold", "0.01", "--limit", "1"], capsys)
        assert "more not shown" in out

    def test_min_length_skips_short_comments(self, project, capsys):
        (project / "c.ts").write_text("// short\n", encoding="utf-8")
        _, out = run([".", "--threshold", "0.01", "--min-length", "500"], capsys)
        assert ", 0 findings" in out


class TestBackendSelection:
    """`--model` is an override, not a default, or it shadows the encoder dir."""

    def opts(self, argv):
        from commentlint.cli import Options, build_parser

        return Options(build_parser().parse_args(argv), {})

    def test_unset_model_stays_none_so_each_backend_picks_its_own(self):
        assert self.opts(["--backend", "encoder"]).model is None

    def test_encoder_fingerprints_the_encoder_dir(self):
        assert self.opts(["--backend", "encoder"]).fingerprint_dir == ENCODER_DIR

    def test_linear_fingerprints_the_linear_dir(self):
        assert self.opts([]).fingerprint_dir == LINEAR_DIR

    def test_explicit_model_wins_over_both(self):
        o = self.opts(["--backend", "encoder", "--model", "m"])
        assert o.model == "m" and o.fingerprint_dir == "m"

    def test_a_gateless_backend_refuses_to_scan(self, project, capsys, monkeypatch):
        import commentlint.backends as backends

        class Gateless:
            name, has_gate, labels = "encoder", False, ["P1"]

        monkeypatch.setattr(backends, "load", lambda *a, **k: (Gateless(), {}, {}))
        assert main([".", "--backend", "encoder", "--no-cache"]) == EXIT_USAGE
        assert "cannot scan" in capsys.readouterr().err


class TestParser:
    def test_repeatable_flags(self):
        args = build_parser().parse_args(["--exclude", "a/", "--exclude", "b/"])
        assert args.exclude == ["a/", "b/"]

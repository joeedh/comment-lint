"""Config resolution, argument disambiguation, output shapes and exit codes."""
import json

import pytest

from commentlint import ENCODER_DIR, LINEAR_DIR
from commentlint import config as config_mod
from commentlint import rules as rules_mod
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

    def test_no_config_falls_back_to_the_models_own_cut(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.42}', encoding="utf-8")
        _, out = run([".", "--no-config"], capsys)
        assert f"cut {rules_mod.scan_threshold(LINEAR_DIR):.2f}" in out

    def test_bad_config_exits_two(self, project, capsys):
        (project / ".commentlintrc.json").write_text("{oops", encoding="utf-8")
        assert main([".", "--no-cache"]) == EXIT_USAGE

    def test_npm_key_is_accepted_but_opaque(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"npm": {"preferSystem": true}}', encoding="utf-8")
        assert config_mod.load(str(p))["npm"] == {"preferSystem": True}

    def test_local_override_merges_over_the_base_config(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.01}', encoding="utf-8")
        (project / ".commentlintrc.local.json").write_text('{"threshold": 0.99}', encoding="utf-8")
        _, out = run(["."], capsys)
        assert "cut 0.99" in out

    def test_local_override_is_only_looked_up_next_to_a_found_config(self, tmp_path):
        (tmp_path / ".commentlintrc.local.json").write_text('{"threshold": 0.99}', encoding="utf-8")
        assert config_mod.find(str(tmp_path)) is None


class TestScanThreshold:
    """The scan cut travels with the model, because it is a per-model quantity.

    At one false-alarm budget the linear gate cuts at 0.71 and the encoder gate at
    0.99; a constant shared between them flagged 2.5% of one tree and 9.1% of the
    same tree.
    """

    def test_the_shipped_model_carries_a_cut(self):
        assert rules_mod.SCAN_KEY in rules_mod.thresholds(LINEAR_DIR)

    def test_a_model_without_the_key_falls_back(self, tmp_path):
        (tmp_path / "thresholds.json").write_text('{"__gate__": 0.5}', encoding="utf-8")
        assert rules_mod.scan_threshold(str(tmp_path)) == rules_mod.SCAN_THRESHOLD

    def test_a_missing_thresholds_file_falls_back(self, tmp_path):
        assert rules_mod.scan_threshold(str(tmp_path)) == rules_mod.SCAN_THRESHOLD

    def test_the_scan_reads_the_cut_from_the_model_directory(self, tmp_path, capsys):
        model = tmp_path / "m"
        model.mkdir()
        (model / "thresholds.json").write_text('{"__scan__": 0.33}', encoding="utf-8")
        empty = tmp_path / "src"
        empty.mkdir()
        # nothing to score, so the cut is resolved without loading a model at all
        main([str(empty), "--no-cache", "--model", str(model)])
        assert "cut 0.33" in capsys.readouterr().out

    def test_the_cli_still_overrides_the_models_cut(self, project, capsys):
        _, out = run([".", "--threshold", "0.55"], capsys)
        assert "cut 0.55" in out


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

    def test_entire_file_flag_scores_the_whole_file_as_one_comment(self, project, capsys):
        _, out = run(["--entire-file", str(project / "a.ts")], capsys)
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
            assert f["source"] in ("model", "model-markdown", "heuristic")
            assert {"line", "col", "rule", "score", "ranked", "text"} <= set(f)

    def test_limit_says_what_it_hid(self, project, capsys):
        _, out = run([".", "--threshold", "0.01", "--limit", "1"], capsys)
        assert "more not shown" in out

    def test_min_length_skips_short_comments(self, project, capsys):
        (project / "c.ts").write_text("// short\n", encoding="utf-8")
        _, out = run([".", "--threshold", "0.01", "--min-length", "500"], capsys)
        assert ", 0 findings" in out

    def test_findings_show_rule_ids_prefixed_with_rule(self, project, capsys):
        _, out = run([".", "--threshold", "0.01"], capsys)
        assert "ruleP" in out or "ruleC" in out
        assert " P" not in out and " C" not in out

    def test_no_limit_by_default_shows_every_finding(self, project, capsys):
        (project / "many.ts").write_text(BAD * 60, encoding="utf-8")
        _, out = run([".", "--threshold", "0.01"], capsys)
        assert "more not shown" not in out


class TestListRules:
    def test_lists_every_rule_with_a_prefixed_id(self, capsys):
        code = main(["--list-rules"])
        out = capsys.readouterr().out
        assert code == EXIT_CLEAN
        assert "ruleP1" in out and "ruleC1" in out
        assert "no-epigrams" in out

    def test_json_lists_bare_rule_ids(self, capsys):
        main(["--list-rules", "--json"])
        data = json.loads(capsys.readouterr().out)
        ids = {r["id"] for r in data["rules"]}
        assert "P1" in ids and "C1" in ids
        assert "ruleP1" not in ids


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


class TestMarkdown:
    PROSE = "A paragraph long enough to be worth scoring, written as ordinary prose here.\n"

    def test_bare_md_on_argv_needs_no_flag(self, project, capsys):
        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run(["notes.md", "--threshold", "0.01"], capsys)
        assert "notes.md" in out or "0 findings" not in out

    def test_directory_walk_ignores_md_by_default(self, project, capsys):
        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert not any(f["path"].endswith("notes.md") for f in data["files"])

    def test_markdown_flag_enables_the_directory_walk(self, project, capsys):
        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run([".", "--markdown", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert any(f["path"].endswith("notes.md") for f in data["files"])

    def test_markdown_files_overrides_the_directory_walk_enabler(self, project, capsys):
        (project / "docs").mkdir()
        (project / "docs" / "other.md").write_text(self.PROSE, encoding="utf-8")
        (project / "wanted.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run([
            ".", "--markdown", "--markdown-file", "wanted.md",
            "--json", "--threshold", "0.01",
        ], capsys)
        data = json.loads(out)
        paths = {f["path"] for f in data["files"]}
        assert any(p.endswith("wanted.md") for p in paths)
        assert not any(p.endswith("other.md") for p in paths)

    def test_missing_markdown_file_is_a_skip_not_a_crash(self, project, capsys):
        code, out = run(["--markdown-file", "nope.md", "--threshold", "0.01"], capsys)
        assert code != EXIT_USAGE
        assert "nope.md" in out

    def test_markdown_findings_are_tagged_and_experimental(self, project, capsys):
        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run(["notes.md", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        findings = [f for fl in data["files"] for f in fl["findings"]]
        assert findings
        for f in findings:
            assert f["source"] == "model-markdown"
            assert f["experimental"] is True
        assert data["summary"]["experimentalFindings"] == len(findings)

    def test_markdown_findings_land_in_the_default_shown_bucket(self, project, capsys):
        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run(["notes.md", "--threshold", "0.01"], capsys)
        assert "notes.md" in out

    def test_banner_prints_only_when_a_markdown_finding_exists(self, project, capsys):
        _, clean_out = run([".", "--threshold", "0.01"], capsys)
        assert "experimental" not in clean_out

        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, md_out = run(["notes.md", "--threshold", "0.01"], capsys)
        assert "experimental" in md_out


class TestParser:
    def test_repeatable_flags(self):
        args = build_parser().parse_args(["--exclude", "a/", "--exclude", "b/"])
        assert args.exclude == ["a/", "b/"]


class TestDisableRules:
    CODE = "// const value = computeSomethingUsefulHereForNoReason(input, arg);\n"

    def test_unknown_rule_id_in_config_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"disableRules": ["C999"]}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="C999"):
            config_mod.load(str(p))

    def test_known_rule_id_in_config_loads_cleanly(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"disableRules": ["C10"]}', encoding="utf-8")
        assert config_mod.load(str(p))["disableRules"] == ["C10"]

    def test_unknown_cli_rule_id_exits_usage(self, project, capsys):
        assert main([".", "--no-cache", "--disable-rule", "C999"]) == EXIT_USAGE
        assert "C999" in capsys.readouterr().err

    def test_disabled_rule_is_never_named_in_text_mode(self, capsys):
        code, out = run(["--text", BAD, "--all", "--json"], capsys)
        top = json.loads(out)["ranked"][0]["rule"]

        code, out = run(["--text", BAD, "--all", "--json", "--disable-rule", top], capsys)
        ids = {r["rule"] for r in json.loads(out)["ranked"]}
        assert top not in ids

    def test_disabling_c2_drops_commented_out_code_from_the_scan(self, project, capsys):
        (project / "c.ts").write_text(self.CODE, encoding="utf-8")
        _, out = run([".", "--threshold", "0.01"], capsys)
        assert "commented-out code" in out

        _, out = run([".", "--threshold", "0.01", "--disable-rule", "C2"], capsys)
        assert "commented-out code" not in out

    def test_disabling_c2_via_config_also_works(self, project, capsys):
        (project / "c.ts").write_text(self.CODE, encoding="utf-8")
        (project / ".commentlintrc.json").write_text('{"disableRules": ["C2"]}', encoding="utf-8")
        _, out = run([".", "--threshold", "0.01"], capsys)
        assert "commented-out code" not in out

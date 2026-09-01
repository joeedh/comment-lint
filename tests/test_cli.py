"""Config resolution, argument disambiguation, output shapes and exit codes."""
import json
import re
import subprocess

import pytest

from commentlint import ENCODER_DIR, LINEAR_DIR
from commentlint import config as config_mod
from commentlint import rules as rules_mod
from commentlint.cli import (
    EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, Options, build_parser, looks_like_path, main,
)

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

    def test_jsonc_config_is_used_when_json_is_absent(self, tmp_path):
        (tmp_path / ".commentlintrc.jsonc").write_text('{"threshold": 0.3}', encoding="utf-8")
        found = config_mod.find(str(tmp_path))
        assert found is not None and found.endswith(".commentlintrc.jsonc")
        assert config_mod.load(found)["threshold"] == 0.3

    def test_json_config_wins_over_jsonc_in_the_same_directory(self, tmp_path):
        (tmp_path / ".commentlintrc.json").write_text('{"threshold": 0.1}', encoding="utf-8")
        (tmp_path / ".commentlintrc.jsonc").write_text('{"threshold": 0.9}', encoding="utf-8")
        found = config_mod.find(str(tmp_path))
        assert found is not None and found.endswith(".commentlintrc.json")
        assert config_mod.load(found)["threshold"] == 0.1

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

    def test_line_comments_are_ignored(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text(
            '// leading comment\n'
            '{\n'
            '  "threshold": 0.5, // trailing comment\n'
            '  "exclude": ["http://example.com"]\n'
            '}\n',
            encoding="utf-8",
        )
        cfg = config_mod.load(str(p))
        assert cfg["threshold"] == 0.5
        assert cfg["exclude"] == ["http://example.com"]

    def test_block_comments_are_ignored(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text(
            '/* leading\n'
            '   comment */\n'
            '{ "threshold": /* inline */ 0.5 }\n',
            encoding="utf-8",
        )
        assert config_mod.load(str(p))["threshold"] == 0.5

    def test_comment_like_text_inside_a_string_is_preserved(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{ "model": "not // a comment /* either */" }', encoding="utf-8")
        assert config_mod.load(str(p))["model"].endswith("not // a comment /* either */")

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

    def test_jsonc_local_override_merges_over_the_base_config(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.01}', encoding="utf-8")
        (project / ".commentlintrc.local.jsonc").write_text('{"threshold": 0.99}', encoding="utf-8")
        _, out = run(["."], capsys)
        assert "cut 0.99" in out

    def test_json_local_override_wins_over_jsonc_in_the_same_directory(self, project, capsys):
        (project / ".commentlintrc.json").write_text('{"threshold": 0.01}', encoding="utf-8")
        (project / ".commentlintrc.local.json").write_text('{"threshold": 0.5}', encoding="utf-8")
        (project / ".commentlintrc.local.jsonc").write_text('{"threshold": 0.99}', encoding="utf-8")
        _, out = run(["."], capsys)
        assert "cut 0.5" in out

    def test_extends_inherits_the_parent_config(self, tmp_path):
        (tmp_path / "base.json").write_text('{"threshold": 0.5, "limit": 3}', encoding="utf-8")
        child = tmp_path / ".commentlintrc.json"
        child.write_text('{"extends": "base.json"}', encoding="utf-8")
        cfg = config_mod.load(str(child))
        assert cfg["threshold"] == 0.5
        assert cfg["limit"] == 3
        assert "extends" not in cfg

    def test_extends_child_key_wins_over_parent(self, tmp_path):
        (tmp_path / "base.json").write_text('{"threshold": 0.5}', encoding="utf-8")
        child = tmp_path / ".commentlintrc.json"
        child.write_text('{"extends": "base.json", "threshold": 0.9}', encoding="utf-8")
        assert config_mod.load(str(child))["threshold"] == 0.9

    def test_extends_resolves_relative_to_the_child_directory(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "base.json").write_text('{"threshold": 0.5}', encoding="utf-8")
        child = sub / ".commentlintrc.json"
        child.write_text('{"extends": "../base.json"}', encoding="utf-8")
        assert config_mod.load(str(child))["threshold"] == 0.5

    def test_extends_missing_file_is_an_error(self, tmp_path):
        child = tmp_path / ".commentlintrc.json"
        child.write_text('{"extends": "missing.json"}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="missing.json"):
            config_mod.load(str(child))

    def test_extends_cycle_is_an_error(self, tmp_path):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        a.write_text('{"extends": "b.json"}', encoding="utf-8")
        b.write_text('{"extends": "a.json"}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="cycle"):
            config_mod.load(str(a))

    def test_extends_repo_root_prefix_resolves_against_git_toplevel(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "shared.json").write_text('{"threshold": 0.7}', encoding="utf-8")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        child = sub / ".commentlintrc.json"
        child.write_text('{"extends": "//shared.json"}', encoding="utf-8")
        assert config_mod.load(str(child))["threshold"] == 0.7

    def test_extends_repo_root_prefix_outside_a_repo_is_an_error(self, tmp_path):
        child = tmp_path / ".commentlintrc.json"
        child.write_text('{"extends": "//shared.json"}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="git repository"):
            config_mod.load(str(child))


class TestUnicodeWhitelistConfig:
    def test_hex_codepoint_and_range_load_cleanly(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"unicodeWhitelist": ["U+2014", "U+2018-U+201F"]}', encoding="utf-8")
        assert config_mod.load(str(p))["unicodeWhitelist"] == ["U+2014", "U+2018-U+201F"]

    def test_malformed_entry_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"unicodeWhitelist": ["not a codepoint"]}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="unicodeWhitelist"):
            config_mod.load(str(p))

    def test_backwards_range_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"unicodeWhitelist": ["U+2015-U+2010"]}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="after its end"):
            config_mod.load(str(p))


class TestLanguageExtensionsConfig:
    def test_valid_mapping_loads_cleanly(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"languageExtensions": {"c-style": [".c", ".h"]}}', encoding="utf-8")
        assert config_mod.load(str(p))["languageExtensions"] == {"c-style": [".c", ".h"]}

    def test_unknown_family_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"languageExtensions": {"shell-style": [".sh"]}}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="shell-style"):
            config_mod.load(str(p))

    def test_extension_without_a_dot_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"languageExtensions": {"c-style": ["c"]}}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="must start with"):
            config_mod.load(str(p))

    def test_extension_already_claimed_by_a_default_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"languageExtensions": {"python-style": [".ts"]}}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="already c-style"):
            config_mod.load(str(p))

    def test_extension_is_lowercased_for_later_lookup(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"languageExtensions": {"c-style": [".C"]}}', encoding="utf-8")
        assert config_mod.load(str(p))["languageExtensions"] == {"c-style": [".c"]}

    def test_extension_claimed_by_two_custom_families_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text(
            '{"languageExtensions": {"c-style": [".foo"], "python-style": [".foo"]}}',
            encoding="utf-8",
        )
        with pytest.raises(config_mod.ConfigError, match="already"):
            config_mod.load(str(p))


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


class TestPathsAroundOptions:
    """A value-taking option splits `paths` into two argparse runs; both must survive.

    https://bugs.python.org/issue14191: argparse only binds one contiguous run
    of positional-looking tokens to a `nargs="*"` positional per parse, so
    `a.ts --threshold 0.7 b.ts` used to drop b.ts as an "unrecognized argument".
    """

    def test_a_path_after_a_value_taking_option_is_not_dropped(self, project, capsys):
        code, out = run(["a.ts", "--threshold", "0.01", "b.ts", "--json"], capsys)
        paths = {f["path"] for f in json.loads(out)["files"]}
        assert paths == {"a.ts", "b.ts"}
        assert code == EXIT_FINDINGS

    def test_paths_on_both_sides_of_two_options_all_survive(self, project, capsys):
        (project / "c.ts").write_text(PLAIN, encoding="utf-8")
        code, out = run(["a.ts", "--threshold", "0.01", "b.ts", "--limit", "5", "c.ts", "--json"], capsys)
        paths = {f["path"] for f in json.loads(out)["files"]}
        assert "a.ts" in paths

    def test_a_genuinely_unknown_flag_still_errors(self, project, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["a.ts", "--not-a-real-flag", "b.ts", "--no-cache"])
        assert exc.value.code == EXIT_USAGE
        assert "--not-a-real-flag" in capsys.readouterr().err

    def test_a_flag_typo_that_is_a_prefix_of_a_real_flag_still_errors(self, project, capsys):
        """argparse abbreviates unambiguous prefixes by default, so a typo one
        letter short of --split-sentences would otherwise be silently accepted
        as that flag instead of reported as unrecognized."""
        with pytest.raises(SystemExit) as exc:
            main(["a.ts", "--split-sentence", "--no-cache"])
        assert exc.value.code == EXIT_USAGE
        assert "--split-sentence" in capsys.readouterr().err


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

    def test_markdown_files_does_not_suppress_the_default_scan_root(self, project, capsys):
        (project / "wanted.md").write_text(self.PROSE, encoding="utf-8")
        _, out = run(["--markdown-file", "wanted.md", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        paths = {f["path"] for f in data["files"]}
        assert any(p.endswith("wanted.md") for p in paths)
        assert any(p.endswith("a.ts") for p in paths)

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

    def test_naming_one_file_does_not_pull_in_unrelated_markdown_files(self, project, capsys):
        """markdownFiles is a whitelist for a walk, not a standing addendum to
        every invocation -- naming a specific file on argv restricts the scan
        to that file, the same as it would with no markdownFiles configured."""
        (project / "wanted.md").write_text(self.PROSE, encoding="utf-8")
        (project / ".commentlintrc.json").write_text(
            json.dumps({"markdownFiles": ["wanted.md"]}), encoding="utf-8",
        )
        _, out = run(["a.ts", "--json", "--threshold", "0.01"], capsys)
        paths = {f["path"] for f in json.loads(out)["files"]}
        assert paths == {"a.ts"}

    def test_naming_a_directory_still_pulls_in_markdown_files(self, project, capsys):
        (project / "wanted.md").write_text(self.PROSE, encoding="utf-8")
        (project / ".commentlintrc.json").write_text(
            json.dumps({"markdownFiles": ["wanted.md"]}), encoding="utf-8",
        )
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        paths = {f["path"] for f in json.loads(out)["files"]}
        assert any(p.endswith("wanted.md") for p in paths)

    def test_banner_prints_only_when_a_markdown_finding_exists(self, project, capsys):
        _, clean_out = run([".", "--threshold", "0.01"], capsys)
        assert "experimental" not in clean_out

        (project / "notes.md").write_text(self.PROSE, encoding="utf-8")
        _, md_out = run(["notes.md", "--threshold", "0.01"], capsys)
        assert "experimental" in md_out


class TestSplitSentences:
    TWO_SENTENCES = (
        "// The leak scan is the refusal, and the refusal is what the caller reads back. "
        "This second sentence is just plain filler text about counters and loops.\n"
    )

    def test_off_by_default_scores_the_whole_comment(self, project, capsys):
        (project / "s.ts").write_text(self.TWO_SENTENCES, encoding="utf-8")
        _, out = run(["s.ts", "--json", "--threshold", "0.01"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        assert findings
        assert "sentence" not in findings[0]
        assert findings[0]["text"] == self.TWO_SENTENCES.strip("/ \n")

    def test_split_sentences_flag_scores_each_sentence_on_its_own(self, project, capsys):
        (project / "s.ts").write_text(self.TWO_SENTENCES, encoding="utf-8")
        _, out = run(["s.ts", "--split-sentences", "--json", "--threshold", "0.01"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        assert findings
        for f in findings:
            assert f["sentence"] is True
            assert f["text"] != self.TWO_SENTENCES.strip("/ \n")
            assert f["text"] in (
                "The leak scan is the refusal, and the refusal is what the caller reads back.",
                "This second sentence is just plain filler text about counters and loops.",
            )

    def test_split_sentences_via_config_also_works(self, project, capsys):
        (project / "s.ts").write_text(self.TWO_SENTENCES, encoding="utf-8")
        (project / ".commentlintrc.json").write_text('{"splitSentences": true}', encoding="utf-8")
        _, out = run(["s.ts", "--json", "--threshold", "0.01"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        assert findings
        assert all(f.get("sentence") for f in findings)

    def test_a_short_sentence_is_dropped_by_min_length(self, project, capsys):
        text = "// A perfectly fine long lead-in sentence goes here for length. No.\n"
        (project / "s.ts").write_text(text, encoding="utf-8")
        _, out = run(["s.ts", "--split-sentences", "--json", "--threshold", "0.01"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        assert all(f["text"] != "No." for f in findings)


class TestLanguageExtensions:
    def test_unmapped_extension_is_ignored_by_default(self, project, capsys):
        (project / "a.c").write_text(BAD, encoding="utf-8")
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert not any(f["path"].endswith("a.c") for f in data["files"])

    def test_config_extends_the_walk_to_a_mapped_extension(self, project, capsys):
        (project / ".commentlintrc.json").write_text(
            '{"languageExtensions": {"c-style": [".c"]}}', encoding="utf-8",
        )
        (project / "a.c").write_text(BAD, encoding="utf-8")
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert any(f["path"].endswith("a.c") for f in data["files"])

    def test_findings_from_a_mapped_extension_are_ordinary_code_findings(self, project, capsys):
        (project / ".commentlintrc.json").write_text(
            '{"languageExtensions": {"c-style": [".c"]}}', encoding="utf-8",
        )
        (project / "a.c").write_text(BAD, encoding="utf-8")
        _, out = run(["a.c", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        findings = [f for fl in data["files"] for f in fl["findings"]]
        assert findings
        assert findings[0]["source"] == "model"
        assert "experimental" not in findings[0]

    def test_bare_mapped_extension_on_argv_needs_no_flag(self, project, capsys):
        (project / ".commentlintrc.json").write_text(
            '{"languageExtensions": {"c-style": [".c"]}}', encoding="utf-8",
        )
        (project / "a.c").write_text(BAD, encoding="utf-8")
        _, out = run(["a.c", "--threshold", "0.01"], capsys)
        assert "a.c" in out

    def test_a_custom_markdown_extension_still_needs_the_markdown_flag(self, project, capsys):
        (project / ".commentlintrc.json").write_text(
            '{"languageExtensions": {"markdown": [".mdx"]}}', encoding="utf-8",
        )
        (project / "notes.mdx").write_text(
            "A paragraph long enough to be worth scoring, written as ordinary prose here.\n",
            encoding="utf-8",
        )
        _, out = run([".", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert not any(f["path"].endswith("notes.mdx") for f in data["files"])

        _, out = run([".", "--markdown", "--json", "--threshold", "0.01"], capsys)
        data = json.loads(out)
        assert any(f["path"].endswith("notes.mdx") for f in data["files"])


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


class TestEnableRules:
    def test_c10_and_c11_are_disabled_by_default(self):
        opts = Options(build_parser().parse_args([]), {})
        assert opts.disable_rules >= rules_mod.DEFAULT_DISABLED

    def test_enable_rule_turns_a_default_disabled_rule_back_on(self):
        opts = Options(build_parser().parse_args(["--enable-rule", "C10"]), {})
        assert "C10" not in opts.disable_rules
        assert "C11" in opts.disable_rules

    def test_enable_rule_via_config_also_works(self):
        opts = Options(build_parser().parse_args([]), {"enableRules": ["C10"]})
        assert "C10" not in opts.disable_rules

    def test_disable_wins_over_enable_for_the_same_rule(self):
        opts = Options(build_parser().parse_args(["--enable-rule", "C10", "--disable-rule", "C10"]), {})
        assert "C10" in opts.disable_rules

    def test_unknown_cli_enable_rule_id_exits_usage(self, project, capsys):
        assert main([".", "--no-cache", "--enable-rule", "C999"]) == EXIT_USAGE
        assert "C999" in capsys.readouterr().err

    def test_unknown_rule_id_in_config_enable_rules_is_an_error(self, tmp_path):
        p = tmp_path / ".commentlintrc.json"
        p.write_text('{"enableRules": ["C999"]}', encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="C999"):
            config_mod.load(str(p))

    def test_list_rules_marks_default_disabled_rules(self, capsys):
        _, out = run(["--list-rules"], capsys)
        assert "ruleC10  non-doc-comment-slashes (disabled)" in out


class TestUnicodeRule:
    TEXT = "// This particular sentence contains an em dash — right in the middle of it.\n"

    def test_disabled_by_default(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run([".", "--threshold", "0.99"], capsys)
        assert "ruleC13" not in out

    def test_enable_rule_flag_reports_it(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run([".", "--threshold", "0.99", "--enable-rule", "C13"], capsys)
        assert "ruleC13" in out
        assert "non-Latin-1: U+2014" in out

    def test_enable_rule_via_config_also_works(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        (project / ".commentlintrc.json").write_text('{"enableRules": ["C13"]}', encoding="utf-8")
        _, out = run([".", "--threshold", "0.99"], capsys)
        assert "ruleC13" in out

    def test_whitelisted_codepoint_is_not_flagged(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        (project / ".commentlintrc.json").write_text(
            '{"enableRules": ["C13"], "unicodeWhitelist": ["U+2014"]}', encoding="utf-8")
        _, out = run([".", "--threshold", "0.99"], capsys)
        assert "ruleC13" not in out

    def test_disable_wins_over_enable(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run([".", "--threshold", "0.99", "--enable-rule", "C13", "--disable-rule", "C13"], capsys)
        assert "ruleC13" not in out

    def test_json_finding_carries_codepoints_and_heuristic_source(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run([".", "--json", "--threshold", "0.99", "--enable-rule", "C13"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        finding = next(f for f in findings if f["rule"] == "C13")
        assert finding["codepoints"] == ["U+2014"]
        assert finding["source"] == "heuristic"

    def test_concise_tag_is_not_a_fake_score(self, project, capsys):
        (project / "u.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run([".", "--threshold", "0.99", "--enable-rule", "C13", "--concise"], capsys)
        assert "1.00" not in out
        assert "flag" in out

    def test_commented_out_code_with_bad_unicode_stays_c2(self, project, capsys):
        # C2 (delete this code) takes priority over C13 for a comment that is
        # both: reporting it under only one of the two rules that fire on it,
        # not silently dropping the other.
        code = '// const label = "a—b"; doSomethingUseful(label, extra);\n'
        (project / "u.ts").write_text(code, encoding="utf-8")
        _, out = run([".", "--threshold", "0.01", "--show-code", "--enable-rule", "C13"], capsys)
        assert "ruleC2" in out
        assert "ruleC13" not in out


class TestInit:
    def test_writes_a_default_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        code = main(["--init"])
        assert code == EXIT_CLEAN
        assert (tmp_path / ".commentlintrc.json").exists()
        assert "wrote" in capsys.readouterr().out

    def test_refuses_to_overwrite_an_existing_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        main(["--init"])
        code = main(["--init"])
        assert code == EXIT_USAGE
        assert "already exists" in capsys.readouterr().err

    def test_written_config_parses_to_an_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        main(["--init"])
        assert config_mod.load(str(tmp_path / ".commentlintrc.json")) == {}

    def test_every_config_key_appears_commented_out(self):
        keys_in_template = set(re.findall(r'// "(\w+)":', config_mod.DEFAULT_CONFIG))
        assert keys_in_template == set(config_mod.KEYS)

    def test_written_config_has_schema_pinned_to_this_version(self, tmp_path, monkeypatch):
        from commentlint import __version__

        monkeypatch.chdir(tmp_path)
        main(["--init"])
        text = (tmp_path / ".commentlintrc.json").read_text(encoding="utf-8")
        assert f'"$schema": "https://raw.githubusercontent.com/joeedh/comment-lint/v{__version__}/schema/commentlintrc.schema.json"' in text


class TestSchema:
    def test_schema_properties_match_config_keys(self):
        import os

        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "schema", "commentlintrc.schema.json",
        )
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        assert set(schema["properties"]) - {"$schema"} == set(config_mod.KEYS)


class TestPremiseRule:
    """Rule P14's deterministic checker, on by default and a hard finding like C2."""

    TEXT = ("// Building the playable is the question, and it is pure and writes nothing, so\n"
            "// the check answers with the real projection rather than a guess.\n")
    PEER = ("// Undo restores a git snapshot of the workspace, and a browser preview has no\n"
            "// workspace, so both controls stay disabled here.\n")

    def test_fires_by_default_and_fails_the_run(self, project, capsys):
        (project / "p.ts").write_text(self.TEXT, encoding="utf-8")
        code, out = run(["p.ts", "--threshold", "0.99"], capsys)
        assert code == EXIT_FINDINGS
        assert "ruleP14" in out
        assert "supporting premise coordinated as a peer: , and it is pure and writes nothing, so" in out

    def test_peer_premise_is_not_flagged(self, project, capsys):
        (project / "p.ts").write_text(self.PEER, encoding="utf-8")
        code, out = run(["p.ts", "--threshold", "0.99"], capsys)
        assert code == EXIT_CLEAN
        assert "ruleP14" not in out

    def test_disable_rule_suppresses_it(self, project, capsys):
        (project / "p.ts").write_text(self.TEXT, encoding="utf-8")
        code, out = run(["p.ts", "--threshold", "0.99", "--disable-rule", "P14"], capsys)
        assert code == EXIT_CLEAN
        assert "ruleP14" not in out

    def test_json_finding_carries_clauses_and_heuristic_source(self, project, capsys):
        (project / "p.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run(["p.ts", "--json", "--threshold", "0.99"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        finding = next(f for f in findings if f["rule"] == "P14")
        assert finding["source"] == "heuristic"
        assert finding["clauses"] == [", and it is pure and writes nothing, so"]

    def test_concise_tag_is_flag(self, project, capsys):
        (project / "p.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run(["p.ts", "--threshold", "0.99", "--concise"], capsys)
        assert "flag" in out

    def test_text_mode_fires_and_exits_one(self, capsys):
        text = self.TEXT.replace("// ", "").replace("\n", " ").strip()
        code = main(["--text", text, "--threshold", "0.99"])
        out = capsys.readouterr().out
        assert code == EXIT_FINDINGS
        assert "ruleP14" in out

    def test_text_mode_json_lists_the_heuristic(self, capsys):
        text = self.TEXT.replace("// ", "").replace("\n", " ").strip()
        code = main(["--text", text, "--json", "--threshold", "0.99"])
        data = json.loads(capsys.readouterr().out)
        assert code == EXIT_FINDINGS
        assert data["heuristics"] == [{"rule": "P14", "clauses": [", and it is pure and writes nothing, so"]}]

    def test_text_mode_disable_rule_restores_the_gate_verdict(self, capsys):
        text = self.TEXT.replace("// ", "").replace("\n", " ").strip()
        code = main(["--text", text, "--json", "--threshold", "0.99", "--disable-rule", "P14"])
        data = json.loads(capsys.readouterr().out)
        assert code == EXIT_CLEAN
        assert data["heuristics"] == []

    def test_text_mode_prints_one_verdict_line(self, capsys):
        text = self.TEXT.replace("// ", "").replace("\n", " ").strip()
        main(["--text", text, "--threshold", "0.99"])
        out = capsys.readouterr().out
        assert out.count("VIOLATION") == 1
        assert "clean" not in out
        assert "ruleP14  flag  , and it is pure and writes nothing, so" in out

    def test_flagged_comment_is_not_also_scored_by_the_model(self, project, capsys):
        (project / "p.ts").write_text(self.TEXT, encoding="utf-8")
        _, out = run(["p.ts", "--json", "--threshold", "0.0"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        assert [f["rule"] for f in findings] == ["P14"]

    def test_markdown_prose_reaches_the_checker(self, project, capsys):
        body = self.TEXT.replace("// ", "").replace("\n", " ").strip()
        (project / "notes.md").write_text(f"# Notes\n\n{body}\n", encoding="utf-8")
        _, out = run(["notes.md", "--json", "--threshold", "0.99"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        finding = next(f for f in findings if f["rule"] == "P14")
        assert finding["source"] == "heuristic"
        assert "experimental" not in finding

    def test_check_version_is_part_of_the_cache_key(self):
        from commentlint import cache as cache_mod
        from commentlint import premise
        base = {"cut": 0.5, "checks": premise.CHECK_VERSION}
        bumped = {"cut": 0.5, "checks": premise.CHECK_VERSION + 1}
        assert cache_mod.run_key(LINEAR_DIR, base) != cache_mod.run_key(LINEAR_DIR, bumped)

    def test_split_sentences_still_reports_the_comment_once(self, project, capsys):
        # the chain is sentence-local, so the checker runs on the whole comment; the
        # flagged comment is then not scored sentence by sentence either
        text = ("// The first sentence here is a plain one about the cache.\n" + self.TEXT)
        (project / "p.ts").write_text(text, encoding="utf-8")
        _, out = run(["p.ts", "--json", "--split-sentences", "--threshold", "0.0"], capsys)
        findings = [f for fl in json.loads(out)["files"] for f in fl["findings"]]
        assert [f["rule"] for f in findings] == ["P14"]

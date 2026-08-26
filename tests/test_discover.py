"""Discovery tests, checked against git rather than against expectations.

Hand-written expectations are exactly the thing at issue here -- the whole
reason for the pruning walker is that the obvious reading of the ignore rules
is wrong in a case pathspec also gets wrong -- so the oracle is `git
check-ignore` on a real repository.
"""
import os
import shutil
import subprocess

import pytest

from commentlint.discover import Ignores, discover, split_glob, load_ignore_files

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

TREE = {
    ".gitignore": "build/\n!build/keep/\n*.log\n",
    "src/.gitignore": "*.ts\n",
    "src/sub/.gitignore": "!keep.ts\n",
}
FILES = [
    "build/a.ts", "build/keep/x.ts", "src/a.ts", "src/sub/keep.ts",
    "src/sub/other.ts", "node_modules/p/i.ts", "vendor/v.ts", "vendor/n.py",
]


@pytest.fixture
def repo(tmp_path):
    for name, body in TREE.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for rel in FILES:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// a comment long enough to be worth scoring here\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def git_ignored(repo, rel):
    r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo)
    return r.returncode == 0


def test_matches_git_on_every_file(repo, monkeypatch):
    monkeypatch.chdir(repo)
    found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["."])}
    for rel in FILES:
        if rel.startswith("node_modules/"):
            continue
        assert (rel in found) is not git_ignored(repo, rel), rel


def test_excluded_directory_is_not_re_included_by_a_negation(repo, monkeypatch):
    """pathspec says build/keep/x.ts is fine; git and the walker disagree."""
    monkeypatch.chdir(repo)
    found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["."])}
    assert "build/keep/x.ts" not in found
    assert git_ignored(repo, "build/keep/x.ts")


def test_innermost_gitignore_negation_wins(repo, monkeypatch):
    monkeypatch.chdir(repo)
    found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["."])}
    assert "src/sub/keep.ts" in found  # !keep.ts beats the *.ts above it
    assert "src/a.ts" not in found


def test_node_modules_is_skipped_but_escapable(repo, monkeypatch):
    monkeypatch.chdir(repo)
    assert not any("node_modules" in p for p in discover(["."]))
    assert any("node_modules" in p for p in discover(["."], with_node_modules=True))


def test_exclude_patterns_apply(repo, monkeypatch):
    monkeypatch.chdir(repo)
    found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["."], exclude=["vendor/"])}
    assert not any(f.startswith("vendor/") for f in found)


def test_exclude_applies_to_a_root_outside_the_cwd(repo, tmp_path, monkeypatch):
    """Anchored at the scan root, not the cwd, or it silently excludes nothing."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    found = discover([str(repo)], exclude=["vendor/"])
    assert found and not any("vendor" in p for p in found)


def test_named_file_beats_the_ignore_rules(repo, monkeypatch):
    """The user naming a path outright has already made the decision."""
    monkeypatch.chdir(repo)
    assert discover(["src/a.ts"]) == ["src/a.ts"]


def test_missing_path_is_an_error(repo, monkeypatch):
    monkeypatch.chdir(repo)
    with pytest.raises(FileNotFoundError):
        discover(["nope"])


class TestGlobs:
    def test_recursive_glob(self, repo, monkeypatch):
        monkeypatch.chdir(repo)
        found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["**/*.ts"])}
        assert "src/sub/keep.ts" in found
        assert "vendor/n.py" not in found

    def test_glob_still_prunes_ignored_directories(self, repo, monkeypatch):
        monkeypatch.chdir(repo)
        found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["**/*.ts"])}
        assert "build/a.ts" not in found

    def test_scoped_glob(self, repo, monkeypatch):
        monkeypatch.chdir(repo)
        found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["vendor/*.py"])}
        assert found == {"vendor/n.py"}

    def test_split_glob(self):
        assert split_glob("src/**/*.ts") == ("src", "**/*.ts")
        assert split_glob("**/*.ts") == (".", "**/*.ts")
        assert split_glob("src/a.ts") == ("src/a.ts", None)


class TestMarkdownExtraExtensions:
    """`.md` stays out of an ordinary walk; `extra_extensions` is the opt-in."""

    def test_md_is_invisible_to_an_ordinary_walk(self, repo, monkeypatch):
        (repo / "docs.md").write_text("# doc\n", encoding="utf-8")
        monkeypatch.chdir(repo)
        found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["."])}
        assert "docs.md" not in found

    def test_extra_extensions_picks_up_markdown_during_a_walk(self, repo, monkeypatch):
        (repo / "docs.md").write_text("# doc\n", encoding="utf-8")
        monkeypatch.chdir(repo)
        found = {
            os.path.relpath(p, repo).replace("\\", "/")
            for p in discover([".", ], extra_extensions=frozenset({".md"}))
        }
        assert "docs.md" in found

    def test_bare_md_named_on_argv_needs_no_enabler(self, repo, monkeypatch):
        (repo / "README.md").write_text("# doc\n", encoding="utf-8")
        monkeypatch.chdir(repo)
        assert discover(["README.md"]) == ["README.md"]

    def test_glob_is_not_scanned_without_the_enabler(self, repo, monkeypatch):
        (repo / "README.md").write_text("# doc\n", encoding="utf-8")
        monkeypatch.chdir(repo)
        found = {os.path.relpath(p, repo).replace("\\", "/") for p in discover(["**/*.md"])}
        assert found == set()

    def test_glob_is_scanned_with_the_enabler(self, repo, monkeypatch):
        (repo / "README.md").write_text("# doc\n", encoding="utf-8")
        monkeypatch.chdir(repo)
        found = {
            os.path.relpath(p, repo).replace("\\", "/")
            for p in discover(["**/*.md"], extra_extensions=frozenset({".md"}))
        }
        assert "README.md" in found

    def test_with_node_modules_and_markdown_together_reach_vendored_md(self, repo, monkeypatch):
        (repo / "node_modules" / "p" / "README.md").write_text("# doc\n", encoding="utf-8")
        monkeypatch.chdir(repo)
        found = {
            os.path.relpath(p, repo).replace("\\", "/")
            for p in discover(
                ["."], with_node_modules=True, extra_extensions=frozenset({".md"})
            )
        }
        assert "node_modules/p/README.md" in found


class TestPathspecTrap:
    """A dir-only pattern only matches a query that carries its trailing slash."""

    def test_directory_needs_its_trailing_slash(self, tmp_path):
        spec = load_ignore_files(str(tmp_path)) or None
        (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
        spec = load_ignore_files(str(tmp_path))
        ig = Ignores([(str(tmp_path), spec)])
        assert ig.ignored(str(tmp_path / "build"), True)
        assert not ig.ignored(str(tmp_path / "build"), False)

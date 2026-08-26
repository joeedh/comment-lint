"""Cache tests, including the staleness case prettier's design cannot catch."""
import json
import os
import subprocess
import sys

import pytest

from commentlint import cache as cache_mod

SRC = "// A comment that is long enough to be worth scoring, and reads oddly.\n"


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "a.ts").write_text(SRC, encoding="utf-8")
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.joblib").write_bytes(b"\x00" * 1024)
    (tmp_path / "model" / "labels.json").write_text('["C1"]', encoding="utf-8")
    return tmp_path


def make(tmp_path, model_dir, **kw):
    return cache_mod.Cache(
        str(tmp_path / "c" / "findings.json"),
        cache_mod.run_key(str(model_dir), {"cut": 0.7}),
        **kw,
    )


def test_round_trip(tree):
    c = make(tree, tree / "model")
    c.put(str(tree / "a.ts"), [{"rule": "C1"}], 3)
    c.save()

    again = make(tree, tree / "model")
    assert again.get(str(tree / "a.ts")) == ([{"rule": "C1"}], 3)


def test_edit_invalidates_the_entry(tree):
    c = make(tree, tree / "model")
    c.put(str(tree / "a.ts"), [{"rule": "C1"}], 3)
    c.save()
    (tree / "a.ts").write_text(SRC + "// and more.\n", encoding="utf-8")
    assert make(tree, tree / "model").get(str(tree / "a.ts")) is None


def test_changed_model_bytes_drop_the_whole_cache(tree):
    """The blind spot prettier documents: same name and version, new behaviour."""
    c = make(tree, tree / "model")
    c.put(str(tree / "a.ts"), [{"rule": "C1"}], 3)
    c.save()
    (tree / "model" / "model.joblib").write_bytes(b"\x01" * 1024)
    assert make(tree, tree / "model").get(str(tree / "a.ts")) is None


def test_changed_options_drop_the_whole_cache(tree):
    c = make(tree, tree / "model")
    c.put(str(tree / "a.ts"), [], 1)
    c.save()
    other = cache_mod.Cache(c.path, cache_mod.run_key(str(tree / "model"), {"cut": 0.9}))
    assert other.get(str(tree / "a.ts")) is None


def test_content_strategy_ignores_mtime(tree):
    c = make(tree, tree / "model", strategy="content")
    path = str(tree / "a.ts")
    c.put(path, [], 1)
    c.save()
    os.utime(path, (0, 0))
    assert make(tree, tree / "model", strategy="content").get(path) == ([], 1)


def test_metadata_strategy_notices_mtime(tree):
    c = make(tree, tree / "model")
    path = str(tree / "a.ts")
    c.put(path, [], 1)
    c.save()
    os.utime(path, (0, 0))
    assert make(tree, tree / "model").get(path) is None


def test_vanished_files_are_pruned(tree):
    c = make(tree, tree / "model")
    gone, kept = str(tree / "gone.ts"), str(tree / "a.ts")
    (tree / "gone.ts").write_text(SRC, encoding="utf-8")
    c.put(gone, [], 1)
    c.put(kept, [], 1)
    c.save(seen=[kept])
    with open(c.path, encoding="utf-8") as f:
        assert len(json.load(f)["files"]) == 1


def test_disabled_cache_reads_and_writes_nothing(tree):
    c = make(tree, tree / "model")
    c.put(str(tree / "a.ts"), [], 1)
    c.save()
    off = make(tree, tree / "model", enabled=False)
    assert off.get(str(tree / "a.ts")) is None
    off.put(str(tree / "a.ts"), [], 1)
    off.save()
    assert os.path.exists(c.path)  # and did not delete what was there


def test_corrupt_cache_is_ignored_not_fatal(tree):
    c = make(tree, tree / "model")
    os.makedirs(os.path.dirname(c.path), exist_ok=True)
    with open(c.path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert make(tree, tree / "model").get(str(tree / "a.ts")) is None


def test_markdown_flag_changes_the_run_key(tree):
    """A stale zero-comments cache entry for a .md file must not survive turning markdown on."""
    a = cache_mod.run_key(str(tree / "model"), {"cut": 0.7, "markdown": False, "markdown_files": ()})
    b = cache_mod.run_key(str(tree / "model"), {"cut": 0.7, "markdown": True, "markdown_files": ()})
    assert a != b


def test_markdown_files_order_does_not_change_the_run_key(tree):
    a = cache_mod.run_key(str(tree / "model"), {"cut": 0.7, "markdown_files": tuple(sorted(["b.md", "a.md"]))})
    b = cache_mod.run_key(str(tree / "model"), {"cut": 0.7, "markdown_files": tuple(sorted(["a.md", "b.md"]))})
    assert a == b


def test_markdown_files_contents_still_change_the_run_key(tree):
    a = cache_mod.run_key(str(tree / "model"), {"cut": 0.7, "markdown_files": ("a.md",)})
    b = cache_mod.run_key(str(tree / "model"), {"cut": 0.7, "markdown_files": ("a.md", "b.md")})
    assert a != b


def test_cached_run_never_imports_sklearn(tmp_path):
    """The invariant the fast path rests on: sklearn's import alone is 2.41s.

    No ordinary test catches this -- a refactor that pulls backends into the
    module-level import graph leaves every other test green.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "a.ts").write_text(SRC, encoding="utf-8")
    code = (
        "import sys; from commentlint.cli import main;"
        f" main([{str(tmp_path)!r}, '--quiet']);"
        " print('HEAVY', [m for m in ('sklearn','torch','joblib','scipy') if m in sys.modules])"
    )
    subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    second = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert "HEAVY []" in second.stdout, second.stdout + second.stderr

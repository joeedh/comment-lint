"""Pins what the P13 and P15 checkers fire on and what they stay silent on.

P13's positives are the four clean-corpus defects plus constructed sentences in the
same shape; each negative names the filter that keeps it silent. P15 is the shape
itself, so its tests are about what counts as a fence and what does not. The corpus
tests assert exact firing sets so a widened predicate has to re-earn its numbers on
known data, and the self-scan test keeps the repository's own prose clean under all
three checkers.
"""
import glob
import hashlib
import json
import os

import pytest

from commentlint import interpolation as interp
from commentlint import premise
from commentlint.comments import extract_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN = os.path.join(ROOT, "data", "clean_comments.jsonl")
PAIRS = os.path.join(ROOT, "data", "violation_pairs.jsonl")

COMMA_DEFECTS = [
    (", or one carrying the mock marker a real backend refuses,",
     "A file that is not an image, or one carrying the mock marker a real backend refuses, "
     "fails at upload with a sentence naming the file."),
    (", and where the line falls,",
     "commands: which pane, and where the line falls, are answers only a pointer can give."),
    (", and the tests that exercise validation over a whole story,",
     "a caller holding one string, and the tests that exercise validation over a whole "
     "story, do not have to write chunks to disk first."),
    (", and so the task hash,",
     "Nothing moves: the prompt, and so the task hash, is unchanged until an author "
     "describes the shot."),
    (", or a nonsense wait,",
     "Nothing said, or a nonsense wait, is treated as a refusal."),
    # a coordinated gerund subject: the commas are the fault whichever repair is chosen
    (", and importing this module lazily,",
     "Keeping that import here, and importing this module lazily, is what makes a fully "
     "cached run fast."),
    # a plural subject after a determiner is a noun, not a verb
    (", and the fixtures they rely on,",
     "The tests, and the fixtures they rely on, are slow."),
    (", and everything under it,",
     "The list, and everything under it, needs sorting."),
    (", rather than the raw response body,",
     "The result, rather than the raw response body, is returned."),
]

# Correct prose, or a match the regex reaches by accident. The comment names the
# filter that keeps it silent.
COMMA_NOT_DEFECTS = [
    # the "subject" is a clause: more finite verbs than relativizers
    "It takes groups rather than a subject: a host that knows how to find the art for the "
    "thing it is showing supplies them, and this file knows nothing about characters, scenes "
    "or the manifest.",
    "The bar carries the act this asset actually has, and the body carries the rest, the "
    "prompt box, its hint, and Promote.",
    # the "subject" is a sentence adverbial, and the word after the closing comma is
    # the real subject
    "By default, with no config file present, findings are printed ranked.",
    "In practice, for most of the callers here, results are cached.",
    "Here, as in the scan path, findings are reported once.",
    "Otherwise, as with the other heuristics, findings are shown by default.",
    "Today, as on every other platform, tests run under node.",
    "If missing, or when the parse fails, callers see an empty list.",
    "On Windows, for reasons covered in the README, paths differ.",
    # subordinators and prepositions do not open a fence: these are ordinary
    # adverbial clauses that English punctuates with commas
    "The handler, if one is registered, runs first.",
    "The gate, when it is saturated, puts the same false-alarm rate elsewhere.",
    "The cache, once the model bytes change, drops every entry.",
    "The wrapper, as shipped in the release zip, pins its dependencies.",
    "Prose under another scene's heading, for the one frame between the click and the "
    "read, is what the reader sees.",
    # an imperative first clause: the word after the closing comma is not a verb
    "Open the list, or close it when it is already open, so the key toggles.",
    # a coordinated clause followed by a connective, not a verb
    "Undo restores a git snapshot of the workspace, and a browser preview has no workspace, "
    "so both controls stay disabled here.",
    # a short adverbial, which English fences with commas as a matter of course
    "Reordering shots inside a scene means, in this app, moving the lines they cover.",
    "`resolveScene`, when given, drops `characterId` entries the scene no longer has.",
    # a list comma read as the closer: the word after it is a noun
    "It touches the ones it writes or removes, plus whichever scene owns each id it renames, "
    "retires or retypes.",
    # words the -s test would read as verbs
    "The walk, plus every node_modules directory, regardless of depth, is fast.",
    "The scan, plus the cache it writes, Windows included, is fast.",
    # a dash inside the fenced span
    "A café with two variants, and Aiko in a second outfit — so plates, sheets and refs all "
    "fan out, is the worst case.",
    # the fence sits inside a code span or a quoted string
    "The call is `pick(a, or b when a is missing, c)`, is documented below.",
    'The message reads "saved, or not, depending on the flag", is shown once.',
    # no verb after the closing comma: a fragment
    "The remembered projects, and the one that is open, as `workspace.recent` last answered.",
    # the two repairs
    "A file that is not an image (or one carrying the mock marker a real backend refuses) "
    "fails at upload.",
    "The prompt (and so the task hash) is unchanged until an author describes the shot.",
]

# Defects the checker knowingly misses, each the cost of a filter.
COMMA_KNOWN_MISSES = [
    # `answers` has no determiner and reads as a finite verb, so the subject looks like
    # a clause
    "Synthesizing missing answers here, and the ones the user typed, is what lets an "
    "already-damaged thread carry on.",
    # `is` with no relativizer reads as a clause
    "Which pane the author is in, and which pane may be covered, are answers only the "
    "pointer can give.",
]

DASH_DEFECTS = [
    ("— looping to a hub scene is normal structure —",
     "Cycles are legal in a VN — looping to a hub scene is normal structure — so they are "
     "broken for ranking purposes only, never rejected."),
    ("— or `1,3` for a multi-pick —",
     "Turn `2` — or `1,3` for a multi-pick — into the options it names."),
    ("– the header's menu, the palette –",
     "Every mutating surface – the header's menu, the palette – goes through this."),
    # an unspaced em-dash pair, the form most LLMs emit
    ("—looping to a hub scene is normal structure—",
     "Cycles are legal in a VN—looping to a hub scene is normal structure—so they are broken."),
    # a sentence ended by a single-letter initial does not merge with the next one
    ("— a judgement call —",
     "Pick option A. The cut — a judgement call — is recorded."),
]

DASH_NOT_DEFECTS = [
    # one dash is an aside, not a fence
    "The cache is on by default — prettier's is not.",
    # two separate asides split by a semicolon or a colon
    "Foo is slow — it re-reads everything; bar is fast — it caches.",
    "First — a scan; second — a report.",
    "Two feeds — one for each direction: the first — a scan.",
    # a dash pair split across two sentences
    "A note — one line. The rest — later.",
    # a sequence, not an interpolation: the same word follows the second dash
    "Options are read from argv — then the config file — then the defaults.",
    # ranges and compounds
    "Values in the 3–5 range are clamped, and 10–20 is the slow path.",
    "Rows 3 – 5 and columns 7 – 9 are skipped.",
    "The Chicago–New York leg and the 2019–2020 season are excluded.",
    # ` -- ` is not a fence: neither corpus uses it and there is no evidence about it
    "Pass the flag -- or not -- and the CLI does the same thing.",
    "Arguments after -- are passed through, and -- alone ends parsing.",
    # a hyphen with spaces, a command-line flag
    "Pass --markdown to scan .md files - the walk skips them otherwise.",
    # the dashes sit inside a code span or a quoted string
    "The separator is `a — b — c` in the rendered title.",
    'The window shows "Saved — 3 files — 2s" after a write.',
    # a table row
    "| -- | -- |",
    # term-gloss lines, with or without list markers
    "- json — machine-readable output\n- concise — one line per finding",
    "Modes:\n  fast — no scoring\n  full — everything is scored",
    "foo — the first thing\nbar — the second thing",
    # the repair
    "Cycles are legal in a VN (looping to a hub scene is normal structure), so they are "
    "broken for ranking purposes only.",
]


@pytest.mark.parametrize("clause,text", COMMA_DEFECTS)
def test_comma_fence_fires(clause, text):
    spans = interp.comma_fenced(text)
    assert [s.clause for s in spans] == [clause]
    assert text[spans[0].start : spans[0].end] == clause


@pytest.mark.parametrize("text", COMMA_NOT_DEFECTS + COMMA_KNOWN_MISSES)
def test_comma_fence_is_silent(text):
    assert interp.comma_fenced(text) == []


def test_comma_fence_survives_a_line_break_inside_the_span():
    text = ("A file that is not an image, or one carrying the\n   mock marker a real backend "
            "refuses, fails at upload.")
    spans = interp.comma_fenced(text)
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == spans[0].clause


@pytest.mark.parametrize("clause,text", DASH_DEFECTS)
def test_dash_fence_fires(clause, text):
    spans = interp.dash_fenced(text)
    assert [s.clause for s in spans] == [clause]
    assert text[spans[0].start : spans[0].end] == clause


@pytest.mark.parametrize("text", DASH_NOT_DEFECTS)
def test_dash_fence_is_silent(text):
    assert interp.dash_fenced(text) == []


@pytest.mark.parametrize("text", [
    "Cycles are legal in a VN — looping to a hub\n   scene is normal structure — so fine.",
    # a short closing line is a wrapped fence when a whole clause precedes the opener
    "Every mutating surface — the header's menu,\n   the palette — goes through this.",
    # the clause before the opener is measured from the line start, not the sentence start
    "The one sentence a\nrefused grab has to say. Retyping itself — what a draft is, how a\n"
    "precondition reads — is shared.",
])
def test_dash_fence_survives_a_line_break_inside_the_span(text):
    spans = interp.dash_fenced(text)
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == spans[0].clause


def test_two_fences_in_one_sentence_are_two_spans():
    text = "A — one — and B — two — are both fenced."
    assert [s.clause for s in interp.dash_fenced(text)] == ["— one —", "— two —"]


def test_a_stray_backtick_does_not_silence_the_checkers():
    # a code span may wrap lines, but not across a sentence end
    text = ("Call `foo\nThe lock is a listening socket, and it is held by exactly one process, "
            "so there is no stale-pid bookkeeping.\nand `bar` after.")
    assert [s.pronoun for s in premise.supporting_premise(text)] == ["it"]
    text = "Use `a\nb` here. The lock is a socket, and it is held once, so nothing leaks."
    assert [s.pronoun for s in premise.supporting_premise(text)] == ["it"]


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="corpus not present")
def test_clean_corpus_firing_sets_are_the_measured_ones():
    with open(CLEAN, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    comma = [i for i, r in enumerate(rows) if interp.comma_fenced(r["comment"])]
    assert comma == [703, 3612, 4666, 4720]
    dashes = [i for i, r in enumerate(rows) if interp.dash_fenced(r["comment"])]
    # about one comment in thirty; the research report records why this is a style
    # call and why it ships on regardless. The digest pins the exact set, so one new
    # fire cannot trade silently against one new miss.
    assert len(dashes) == 189
    assert sum(len(interp.dash_fenced(r["comment"])) for r in rows) == 194
    assert hashlib.md5(",".join(map(str, dashes)).encode()).hexdigest()[:12] == "0b411f1ba1a5"


@pytest.mark.skipif(not os.path.exists(PAIRS), reason="corpus not present")
def test_revision_corpus_counts_are_the_measured_ones():
    with open(PAIRS, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert sum(1 for r in rows if interp.comma_fenced(r["before"])) == 2
    assert sum(1 for r in rows if interp.comma_fenced(r["after"])) == 3
    # the table the research report quotes: what a revision did with a dash fence
    kept = parens = rewritten = 0
    for r in rows:
        before, after = len(interp.dash_fenced(r["before"])), len(interp.dash_fenced(r["after"]))
        if not before:
            continue
        if after >= before:
            kept += 1
        elif r["after"].count("(") > r["before"].count("("):
            parens += 1
        else:
            rewritten += 1
    assert (kept, parens, rewritten) == (41, 87, 120)
    assert sum(1 for r in rows if interp.dash_fenced(r["after"])) == 47


def test_the_repository_does_not_flag_itself():
    """`python task.py scan` covers this tree, so the checkers' own prose has to pass them."""
    patterns = ("commentlint/**/*.py", "tests/*.py", "data/*.py", "*.py", "bin/*")
    files = sorted({p for pat in patterns for p in glob.glob(os.path.join(ROOT, pat), recursive=True)})
    fired = []
    for path in files:
        try:
            comments = extract_file(path, {})
        except Exception:  # a launcher script or a file with no recognised language
            continue
        for c in comments:
            for rule, check in (("P13", interp.comma_fenced), ("P14", premise.supporting_premise),
                                ("P15", interp.dash_fenced)):
                for s in check(c.text):
                    fired.append((rule, os.path.relpath(path, ROOT), c.line, " ".join(s.clause.split())))
    assert fired == []

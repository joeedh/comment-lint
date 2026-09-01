"""Pins what rule P14's checker fires on and, more importantly, what it stays silent on.

Three of the positives are the corpus sentences the predicate was measured against;
the rest are constructed in the same shape. Each negative names the filter that
exists because of it. The corpus tests at the end assert the exact firing set over
the committed corpora, so a widened predicate has to re-earn its precision on known
data before it ships. The corpora hold no expletive `it` chain at all, which is why
the constructed negatives here are the only thing standing between that class and a
false positive.
"""
import json
import os

import pytest

from commentlint import premise

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN = os.path.join(ROOT, "data", "clean_comments.jsonl")
PAIRS = os.path.join(ROOT, "data", "violation_pairs.jsonl")
AUTHORED = os.path.join(ROOT, "data", "p14_pairs.jsonl")

# A copular first clause followed by a bare pronoun continuing its subject. The first
# three are labelled defects in data/p14_checker_eval.py.
DEFECTS = [
    ("it", "Building the playable is the question, and it is pure and writes nothing, so "
           "the check answers with the real projection rather than a guess."),
    ("it", "A note is authored input, the one thing an author can say about how generated art "
           "should look, and it goes into the prompt, so setting one re-keys the tasks it reaches."),
    ("it", "The Gemini backend has no assembled conversation body — but its `contents`/`config` "
           "pair is still the thing a positional error indexes into, and it is built inside the "
           "backend rather than written out at the call site, so the check lives here."),
    ("they", "Art notes are the only thing an author says about how generated art should look, "
             "and they are authored input rather than a prompt override, so setting one re-keys "
             "the tasks."),
    ("neither", "A plan and its verdict are the decisive turns of a conversation, and neither is "
                "written to the loop's event stream, so both are recorded here."),
    ("it", "The worker is idle between runs, and it still holds the connection, so the pool "
           "never shrinks."),
    ("they", "The tokens are minted per request, and they never leave the process, so no store "
             "is needed."),
    ("both", "The two passes are cheap, and both are cached, so a rerun costs nothing."),
    ("each", "The handles are per-worker, and each has its own socket, so the pool is never "
             "shared."),
    # a propositional `it` after a copula is the rule's own case: "(which is logged)"
    ("it", "When the flag is set, the worker is idle, and it is logged, so the operator can see "
           "the pause."),
]

# Defects the checker knowingly misses. Each is silent because a filter that keeps a
# false positive out also covers it, and the filter wins.
KNOWN_MISSES = [
    # after `neither` only an auxiliary counts as the verb, since "neither pass is" would
    # otherwise read "pass" as one
    "A plan and its verdict are the decisive turns of a conversation, and neither reaches "
    "the loop's event stream as a transcript line, so both are recorded here.",
    # the first clause's verb is not a copula, so the pronoun could point at its object
    "Verification runs here because this is the earliest place both registries exist, and "
    "it runs at build time, so a bad name fails the bundle.",
]

# Each of these is a correctly coordinated peer premise, an object-anchored gloss the
# checker does not claim, or a match the regex reaches by accident. The comment names
# the filter that keeps it silent.
NOT_DEFECTS = [
    # the pronoun already occurs in the first clause, so it continues that referent
    "The layout graph carries ranking-only edges into and out of the barrier: every node "
    "above it points at it, and it points at every node it blocks, so blocked work sits "
    "beneath the line.",
    # the first clause has no verb, so its subject is unknown
    "Synchronous and pure, and it never touches the DOM, so the node-only jest project can "
    "test it.",
    # the first clause's verb is transitive: the pronoun may continue the object
    "Parses the header, and it is cached, so the second call is free.",
    "Emits the manifest for the bundle, and it is read by the loader on boot, so the field "
    "order matters.",
    "Every consumer reads the snapshot, and it is taken once at startup, so a hot edit is "
    "invisible.",
    "The loader reads the config file, and it is shared with the CLI, so a change there "
    "shows up here.",
    "The build takes ten minutes, and it shows, so the cache is warmed first.",
    "The retry fires twice, and it works, so nothing else is needed.",
    # a copula followed by a preposition names a second noun the pronoun could continue
    "The socket is in the pool, and it is closed on shutdown, so nothing leaks.",
    "The cursor is over the panel, and it is hidden, so clicks fall through.",
    # number disagrees, with a listed verb and with an unlisted one
    "All three drags read their verdict from `pathux/branch.ts`, and it asks the same "
    "`branchops` the command will run, so the refusal shown mid-drag is the real one.",
    "All three drags derive their verdict from the branch, and it asks the same branchops "
    "the command will run, so the refusal is real.",
    # the subject head is the noun before "of", not the one after it
    "The list of handlers is fixed at boot, and they run in order, so a failure here has "
    "already passed the cheap checks.",
    "The owner of the sockets is the pool, and they are closed on shutdown, so nothing leaks.",
    # a subordinate clause opening the sentence is not the first clause
    "When the flag is set, the workers stop, and it is logged, so the operator can see the "
    "pause.",
    # the first clause's own subject is a pronoun or an indefinite
    "This is the earliest place both registries exist, and it runs at build time, so a bad "
    "name fails the bundle.",
    "Everything below reads the snapshot, and it is taken once at startup, so a hot edit is "
    "invisible.",
    "Something upstream holds the lock, and it is released only on error, so the wait can "
    "be long.",
    "Nothing in this module is DOM-bound, and it is safe to import anywhere, so the tests "
    "run under node.",
    # expletive and cleft `it`
    "The loader is slow, and it is hard to know which key is stale, so every key is re-read.",
    "The check is cheap, and it is fine to run it every frame, so nothing caches its result.",
    "The pointer is null here, and it is safe to dereference only after init, so the guard "
    "is required.",
    "The frame is dropped, and it is not clear why, so the drop is logged with the full state.",
    "The frame is dropped, and it is not clear, so the drop is logged.",
    "The adapter is thin, and it turns out the handle is never closed, so the wrapper closes it.",
    "The queue is bounded, and it is the producer's job to back off, so the consumer never "
    "blocks.",
    "The queue is bounded, and it is the producer that backs off, so the consumer never blocks.",
    "The parser is stateless, and it is the caller who frees the buffer, so nothing here owns "
    "memory.",
    "The foo bar is baz, and it isn't clear which wins, so both are logged.",
    "The check is cheap, and it takes a millisecond, so it runs every frame.",
    "The build is deterministic, and it makes sense to cache it, so the hash is the key.",
    # `this`, `these` and `those` are deictic in comments and are not in the pronoun set
    "The migration is additive, and this is where the old name last appears, so the rename "
    "lands here.",
    "The config is immutable, and this is the only place it is read, so a change needs a "
    "restart.",
    "The validators are ordered, and these three run last, so a failure here has already "
    "passed the cheap checks.",
    # the pronoun is a determiner, not the whole subject
    "The handles are pooled, and neither the pool nor the handle is thread-safe, so a mutex "
    "wraps the pool.",
    "The results are scored, and none of the scores are calibrated, so the caller should "
    "not compare them.",
    "The workers are forked, and each process owns a socket, so the pool is per-worker.",
    "The handles are pooled, and both sides are locked, so a mutex is not needed.",
    "The two passes are cheap, and neither pass is cached, so a rerun costs nothing.",
    "The two passes are cheap, and both passes exit early, so a rerun costs nothing.",
    # a peer premise that shares a noun with the first clause: the object-anchored case
    # the checker does not claim
    "Undo restores a git snapshot of the workspace, and a browser preview has no workspace, "
    "so both controls stay disabled here.",
    # the second clause opens with an adjunct, not a pronoun
    "Everything down to the checkpoint spawns `git`, and on a machine without it the first "
    "call would throw before any window exists, so the app would never appear.",
    # the match sits inside a dash-fenced span, spaced or not
    "This app has two rules about that — the header is not a pane, and the last pane is "
    "kept — and they live in `panes.ts`, so the pick has to be made against them.",
    "The layout is stable—it is cached, and it is reused, so nothing recomputes.",
    # a colon or semicolon inside the span means the `so` closes a later clause
    "Art notes are the only thing an author says about how generated art should look, and "
    "they are authored input rather than a prompt override: they go into the prompt the "
    "builders derive, so setting one re-keys the tasks.",
    # the `and` sits inside a code span
    "The value is written by `emit(node, and it is read by flush)`, so the order matters.",
    # the two repair shapes
    "Building the playable is the question (which is pure and writes nothing), so the check "
    "answers with the real projection.",
    "Building the playable is the question, which is pure and writes nothing, so the check "
    "answers with the real projection.",
    # `and so on` and `and so` are not a chain
    "The walk covers scenes, shots, characters, and so on, so nothing is left unvisited.",
    # the chain spans a sentence boundary, including one whose period is protected as an
    # abbreviation or an initial
    "The cache is keyed on the model bytes, and it is on by default. Prettier's is not, so "
    "the two differ here.",
    "The parser is small, and it handles only C. The rest is delegated, so the file stays short.",
    "The tokenizer is shared, and it handles ints etc. The second pass is cheap, so nothing "
    "is cached.",
]


@pytest.mark.parametrize("pronoun,text", DEFECTS)
def test_fires_on_subject_continuation(pronoun, text):
    spans = premise.supporting_premise(text)
    assert [s.pronoun for s in spans] == [pronoun]
    assert text[spans[0].start : spans[0].end] == spans[0].clause
    assert spans[0].clause.startswith(", and ") and spans[0].clause.endswith(", so")


@pytest.mark.parametrize("text", NOT_DEFECTS + KNOWN_MISSES)
def test_silent_on_peers_artifacts_and_known_misses(text):
    assert premise.supporting_premise(text) == []


def test_line_breaks_inside_the_clause_do_not_matter():
    text = ("Building the playable is the question, and it\n   is pure and writes nothing, so "
            "the check answers with the real projection.")
    spans = premise.supporting_premise(text)
    assert [s.pronoun for s in spans] == ["it"]
    assert text[spans[0].start : spans[0].end] == spans[0].clause


def test_abbreviation_does_not_end_the_sentence():
    text = ("The loader is shared, e.g. by the tests, and it is built once, so a second "
            "call is free.")
    spans = premise.supporting_premise(text)
    assert [s.pronoun for s in spans] == ["it"]
    assert text[spans[0].start : spans[0].end] == spans[0].clause == ", and it is built once, so"


def test_two_sentences_each_with_a_chain_report_both():
    one = DEFECTS[0][1]
    two = DEFECTS[3][1]
    spans = premise.supporting_premise(one + " " + two)
    assert [s.pronoun for s in spans] == ["it", "they"]
    assert spans[1].start > spans[0].end


def test_paragraph_break_is_a_sentence_boundary():
    text = "The cache is keyed on the model bytes, and it is on by default\n\nPrettier's is not, so."
    assert premise.supporting_premise(text) == []


def test_only_the_nearest_clause_is_the_antecedent():
    # `, and` is a clause cut, so the pronoun is compared against "the layout", not "the files"
    text = "The files are listed, and the layout is stable, and it is cached, so nothing recomputes."
    assert [s.pronoun for s in premise.supporting_premise(text)] == ["it"]


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="corpus not present")
def test_clean_corpus_firing_set_is_exactly_the_measured_one():
    with open(CLEAN, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    fired = [i for i, r in enumerate(rows) if premise.supporting_premise(r["comment"])]
    # three of the twelve hand-labelled defects; every other row is a peer, an
    # artifact, a known miss or clean
    assert fired == [1744, 3245, 5108]


@pytest.mark.skipif(not os.path.exists(PAIRS), reason="corpus not present")
def test_revision_corpus_fires_only_on_the_known_defects():
    with open(PAIRS, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    # the one before-text with the shape has a colon inside the span and is excluded;
    # the two after-texts are clean-corpus defects carried through unrelated revisions
    assert sum(1 for r in rows if premise.supporting_premise(r["before"])) == 0
    after = [" ".join(s.clause.split()) for r in rows for s in premise.supporting_premise(r["after"])]
    assert sorted(after) == [", and it goes into the prompt, so", ", and it is pure and writes nothing, so"]


@pytest.mark.skipif(not os.path.exists(AUTHORED), reason="corpus not present")
def test_authored_pairs_are_object_anchored_and_silent_on_both_sides():
    with open(AUTHORED, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert len(rows) == 20
    assert not any(premise.supporting_premise(r["before"]) for r in rows)
    assert not any(premise.supporting_premise(r["after"]) for r in rows)

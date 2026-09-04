# Per-sentence heuristic findings under `--split-sentences`

## The problem

`--split-sentences` has no effect on the deterministic checkers. P13, P14 and P15 report
the same finding with the flag as without it: `text` is the whole comment, there is no
`sentence` or `comment` key, so the reporter cannot bracket or bold anything, and two
dash fences in two different sentences collapse into one finding's `clauses` list.

The cause is `commentlint/cli.py:528-534`. `_check()` runs on the whole comment before
the split, and a firing checker `continue`s, so the split loop is never reached:

```python
if _check(c, opts, per_file[path]):
    continue
if opts.split_sentences:
    for sentence in sentences_mod.split(c.text):
        ...
```

The behaviour is deliberate, not an accident: docs/plans/p14-deterministic-checker.md:88
specifies "Under `--split-sentences` this skips every sentence of the flagged comment",
and tests/test_cli.py:978 pins it. It reads as broken for P15, whose fence is a
per-sentence shape by construction. `dash_fenced` already splits sentences internally and
returns one span per fence.

Both consequences are wrong under a flag that reports per sentence:

- The offending sentence is not marked. Readme.MD:39-45 and docs/scanning.md:85-92
  promise the comment printed with the flagged sentence bolded or bracketed; a
  heuristic finding gets neither.
- One firing sentence suppresses model scoring of every other sentence in the comment.
  A ten-sentence docstring with one dash fence contributes exactly one finding.

## What it becomes

One heuristic finding per offending sentence, carrying `sentence: true` and `comment`
like a model finding under the same flag, with every sentence that no checker flagged
still queued for the model.

## Why the checkers keep seeing the whole comment

The obvious implementation runs each checker on each split sentence. It changes P15's
firing set, so it is rejected:

- `sentences.split()` collapses all whitespace (`" ".join(text.split())`), so newlines
  are gone by the time a sentence exists.
- `interpolation._is_fence` guards the "term / gloss" shape on `"\n" in mid`, and
  `DASH_FENCE` guards a list-item line on a lookahead for a newline plus a bullet. Both
  are dead against collapsed text, so wrapped gloss lines would start firing as
  interpolations.
- `dash_fenced` also reads `line_prefix`, the text from the last newline to the
  sentence start, which is empty for every collapsed sentence.

So the checkers keep running once on `c.text` with its newlines intact, and the spans
they return are mapped back onto sentences afterwards. No span appears or disappears,
because the checkers see the same text either way. Which rule id claims a span is decided
per sentence rather than per comment, so a comment breaking two shapes reports under both
ids where a run without the flag reports only the first.

Every checker returns offsets into the original comment text. `premise.Span` carries
`start` and `end` (premise.py:140-148), and both `comma_fenced` and `dash_fenced` build
their spans from `base + m.start()` (interpolation.py:153-200). The offsets index the
original text because `premise.masked` is length-preserving: `blank()` substitutes
`first + "x" * (n - 2) + last` and `sentences.protect` swaps each abbreviation period
for a same-length placeholder (premise.py:220-232, sentences.py:19-25). The docstring
at premise.py:222 states this, and it was checked over the repository's own 301
extracted comments with no length mismatch.

## The two splitters disagree, so a span can straddle a sentence boundary

The checkers split sentences with `premise.SENTENCE` over `masked(text)`;
`--split-sentences` splits with `sentences._BOUNDARY` over the raw text. They share
`sentences.protect` and its abbreviation list, so abbreviations are not the difference.
Three real divergences remain:

- `masked()` blanks code spans and quoted strings before protecting, so a `. ` inside
  backticks or quotes never ends a sentence for a checker but does for `split()`.
- `premise.SENTENCE` splits on any whitespace after `.!?` plus blank lines;
  `_BOUNDARY` additionally requires the next character to be `[A-Z0-9"'(]`.
- `_BOUNDARY` consumes an optional trailing `"')]`, so `See the note (below.) Then...`
  yields the sentence `See the note (below.` with the bracket dropped.

The first of these produces a span crossing a `split()` boundary. Measured:

```
'Cycles are legal in a VN - "one. Two" is the hub scene - so they are broken here.'
  dash_fenced: one span at (25, 56)
  split():     ['Cycles are legal in a VN - "one.',
                'Two" is the hub scene - so they are broken here.']
```

Assigning that span to the first sentence it touches would report a fragment, print a
`clauses` line running past the bracketed region, and still queue the second half of the
offending clause for the model, so one piece of prose gets reported twice.

A finding therefore covers every sentence its span overlaps, not just the first one it
touches. A span that overlaps two sentences reports both as one finding, and both are
consumed, so neither reaches the model.

## Implementation

### `commentlint/cli.py`

- Extend `_sentence_span(text, sentence, pos=0)` (cli.py:821) with a search offset. It
  already does the loose whitespace match this needs. The offset makes a sentence
  repeated inside one comment locate its own occurrence rather than the first.
- Add a `_check_sentences(c, opts)` helper:
  1. Run every enabled checker on `c.text`, all of them rather than the first that
     fires, because two sentences of one comment may break two different rules.
     `CHECKERS` order is kept for step 4.
  2. Walk `sentences_mod.split(c.text)`, locating each with `_sentence_span` from a
     running offset, giving `(sentence, start, end)` triples. A sentence that fails to
     locate is skipped for assignment, leaves the running offset where it was, and is
     still queued for the model.
  3. Map each span to the contiguous range of sentence indices it overlaps, then merge
     ranges that share a sentence. Each merged range is one finding unit.
  4. Within a unit, the first checker in `CHECKERS` order holding a span there names the
     finding. That is today's "most specific shape first" rule (cli.py:41-44) applied per
     unit instead of per comment, and the losing checkers' spans in that unit are dropped
     the same way `_check` drops them today.
- Each unit becomes one `_finding_spans` with:
  - `text`: the unit's sentences joined by a single space, matching the collapsed form a
    model split finding carries. `_finding_spans` takes `text` from `c.text` today
    (cli.py:596 via `_finding`), so the caller replaces it.
  - `clauses`: only the winning checker's spans inside that unit, not the whole
    comment's span list.
  - `sentence: True` and `comment: c.text`.
  - `sentence_start` and `sentence_end`: the unit's offsets into `c.text`.
- `_comment_lines` (cli.py:834) uses `sentence_start`/`sentence_end` when present and
  falls back to `_sentence_span` otherwise. The fallback search is why a comment
  containing the same sentence twice currently brackets the first occurrence whichever
  one was flagged; storing offsets avoids inheriting that for heuristic findings. Model
  split findings keep the search and keep the existing behaviour, which is a separate
  defect and is not fixed here.
- In the scan loop, under `opts.split_sentences` the checkers no longer `continue` past
  the split: flagged units are appended as findings, and every unlocated or unflagged
  sentence is queued for the model as it is now. Without the flag, nothing changes.
- Positions stay the whole comment's `line`, `col`, `end_line` and `end_col`, matching
  what a model finding does under the same flag, where `dataclasses.replace(c,
  text=sentence)` replaces the text alone.

### Orphan spans

A span overlapping no located sentence must not be dropped, because that would lose a
detection the non-split run reports. Those spans fall back to one whole-comment finding
with no `sentence` key, printed the way every heuristic finding is printed today. A
comment can therefore carry both kinds. The orphan path is a safety net for splitter
disagreement and is expected to stay empty.

### `min_length`

`min_length` filters whole comments before the checkers run (cli.py:508), and under
`--split-sentences` it also filters sentences bound for the model. It does not filter a
flagged unit. The floor exists to keep short comments away from the model, which scores
them poorly, and a checker span needs no such protection because it is exact. A comment
that reached a checker at all is already over the floor. The test for this has to keep
the whole comment above `filters.MIN_LEN`, which is 40, or it passes for the wrong
reason.

### Cache

There is no version bump.

- `cache.run_key` hashes `__version__` (cache.py:57) and the options dict carries
  `split_sentences` (cli.py:471), so a released version carrying this change cannot
  serve entries written by the version before it.
- `Cache.get` returns `entry.get("findings", [])` with no shape validation
  (cache.py:97-109) and `Finding` is `dict[str, Any]` (cache.py:28), so a stale entry
  would be served silently in the old shape rather than rejected. The exposure is an
  unreleased checkout scanning across the change, and `--no-cache` once clears it.
- Adding a key to `CHECK_VERSIONS` (cli.py:50) or a dedicated run-key option would
  invalidate without waiting for a release. Declined: `CHECK_VERSIONS` is documented as
  meaning a predicate changed (interpolation.py:38-39), no predicate changes here, and a
  key that stays forever to serve one dev-checkout upgrade is not worth carrying.

### Repeated comment bodies

A comment with three flagged sentences prints its body three times, once under each
finding's header. That is already what `--split-sentences` does for model findings
(`_print_ts`, cli.py:786-811, calls `_comment_lines` per finding), so heuristic findings
behave the same rather than introducing a new shape. Grouping findings that share a
comment under one printed body would improve both, and is out of scope here.

### Counting

Two summary effects, both accepted:

- The `... findings` count (cli.py:690) rises for a comment with several fences, and
  `--limit N` therefore covers fewer distinct comments.
- `report()` sorts `flagged` by `(path, line)` (cli.py:648-651) and `_print_ts` by
  `(line, col)` (cli.py:797). Every sentence finding on one comment shares both keys, so
  reading order rests on the sort being stable. It is, in CPython, and a test pins the
  order.

`experimentalFindings` (cli.py:655) is unaffected: heuristic findings never set
`experimental`, markdown chunks included (pinned by tests/test_cli.py:962-969). Markdown
prose chunks get the largest behavioural change of anything here, because a chunk is one
markdown-it inline token and so the most multi-sentence unit the tool produces, but the
new path applies to them unchanged.

`SPAN_LEGEND` needs no change: `_print_ts` gates it on `any(SPAN_OPEN in line for line in
out)` over the already-rendered lines (cli.py:815), so heuristic brackets turn it on.

## Tests

`tests/test_cli.py`:

- `TestInterpolationRules`: a comment with two dash-fenced sentences and one clean
  sentence, run with `--split-sentences --enable-rule P15`, yields two P15 findings,
  each `text` one sentence, each carrying `comment`, and the clean sentence reaches
  the model.
- The default (non-split) run over the same comment still yields exactly one P15
  finding with both clauses. That is the guard that this change is split-only.
- A single-sentence comment yields the same finding with and without the flag, which is
  the equivalence guard on the new code path.
- The heuristic split finding's `text` is the sentence rather than the whole comment.
- Default text output brackets the flagged sentence inside the printed comment for a
  heuristic finding, and the legend line appears. The run must not pass `--color`;
  `_comment_lines` writes brackets only when `not c.bold` (cli.py:868-869), which the
  capsys-captured runs already satisfy.
- P13 in one sentence and P15 in another of the same comment report under their own
  ids, rather than the first checker claiming both.
- A span straddling a `split()` boundary (the quoted-period case above) reports one
  finding whose text covers both sentences, and neither half reaches the model.
- Two findings on one comment print in sentence order.
- `--concise` with a split heuristic finding still tags `flag` and prints the sentence
  as `head`.
- A comment whose whole body is over `filters.MIN_LEN` but whose flagged sentence is
  under it still reports.
- Rewrite `test_split_sentences_still_reports_the_comment_once` (line 978) as the
  P14 case of the new behaviour: the plain first sentence is scored, the chain
  sentence reports P14 with `comment` set. Its current assertion is the specified
  behaviour being replaced. It is the only existing test that pins the old behaviour:
  `TestSplitSentences`' fixture text fires none of the three checkers, and the tests at
  956 and 1037 run without the flag.

`tests/test_interpolation.py` and `tests/test_premise.py` are untouched, because the
predicates do not change.

## Docs

- Readme.MD:39-45. Say the deterministic rules split too, so a long comment with one
  dash-fenced sentence is flagged on that sentence. The file is tracked as `Readme.MD`
  and task.py:112 renames it on release.
- docs/scanning.md:85-92. The same, in the paragraph that already describes the marking.
- docs/architecture.md:68 says "`cli.py` tries the three checkers in order and reports
  the first that fires", which becomes per sentence under the flag. Line 67 stays true.
- cli.py:41-44, the `CHECKERS` comment: "The first that fires names the finding and the
  comment is not scored."
- cli.py:525-527: "one hard finding per comment, and the model's suspicion would only be
  printed beside it."
- docs/plans/p14-deterministic-checker.md:88. Annotate the "skips every sentence" line as
  superseded, pointing here. The plan records what was decided then, so it is annotated
  rather than edited.
- todos.md.

## Known limitations left alone

- `_BOUNDARY` consumes a trailing `"')]`, so a sentence ending `(below.)` locates as
  `See the note (below.` and its bracket closes before the `)`. Cosmetic, and it
  predates this change.
- `--text` and `--entire-file` ignore `--split-sentences` entirely (`run_single`,
  cli.py:282). A separate gap, not addressed here.
- A comment containing the same sentence twice brackets the first occurrence for model
  findings, whichever one was flagged.

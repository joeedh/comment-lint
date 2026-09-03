# P13 and P15 as deterministic checkers

**Status: implemented.** Written 2026-08-31; pressure-tested, implemented and reviewed
the same day. The numbers below are the shipped predicates' and are reproduced by
`python data/p13_pairs_eval.py`.

## Context

- docs/research/p13-comma-and-dash-interpolation.md measures P13's labelled pairs and
  finds 13 of 21 are paired em dashes turned into parentheses, not the paired commas
  the rule text names. The revision corpus removes a paired-dash interpolation five
  times in six when it touches one (a third to parentheses, half rewritten away). The
  comma shape the rule text describes is rare (4 fires in 5,998 clean comments, all
  defects) but mechanical.
- Both shapes are decidable by structure, unlike P14's, so both ship as deterministic
  checkers alongside `commentlint/premise.py`. Both are on by default and both are hard
  findings, because the tool exists to inhibit these shapes rather than advise on them.
- The dash check gets its own rule id, P15, because it fires on about one comment in
  thirty of existing prose and a project that disagrees needs to turn off exactly that.

## The rules

**P13 `bracket-not-comma-alternative`** (existing id, text unchanged). The checker fires
on a plain noun phrase, a comma-fenced phrase opening with a coordinator or alternative
marker, then the noun phrase's verb. The repair brackets the phrase or drops the commas.

    defect  A file that is not an image, or one carrying the mock marker a real
            backend refuses, fails at upload.
    repair  A file that is not an image (or one carrying the mock marker a real
            backend refuses) fails at upload.

**P15 `bracket-not-dash-interpolation`** (new). The checker fires on two em dashes, or
two spaced en dashes, fencing text inside one sentence. The repair brackets the text or
makes it a sentence of its own.

    defect  Cycles are legal in a VN — looping to a hub scene is normal structure —
            so they are broken for ranking purposes only.
    repair  Cycles are legal in a VN (looping to a hub scene is normal structure),
            so they are broken for ranking purposes only.

## Predicates

Both run per sentence on a same-length copy with code spans and double-quoted strings
blanked and abbreviation periods protected, as P14's does.

P13, on `<subject>, <opener> <span>, <after>` where the match starts at the sentence
start, after `.;:!?`, or after `(`:

1. The subject has 3–80 characters and no `.;:()` or dash.
2. The opener is a coordinator or alternative marker (`or and nor as well as rather
   than not but not plus including such as like unlike especially particularly`); the
   span after it has no `,.;:()`, dash or backtick, and opener plus span run to at
   least four words. Subordinators and prepositions are not openers.
3. The word after the closing comma is a verb: an auxiliary, or a lower-case word of
   four or more letters ending in `-s` or `-ed` that does not end in `-ous`, `-less`,
   `-wards`, `-ness`, `-ies` or `-ss` and is not in a short list of non-verbs.
4. The subject is a plain noun phrase: its first word is not a verb, an opener, a
   preposition, a sentence adverb or an `-ly` word, and it holds at most one finite
   verb per relativizer (`that which who whose whom where when`, not counting the
   first word, where `Which` is interrogative). A word after a determiner is a noun
   whatever its ending, so `the tests` and `its needs` are not verbs.

P15: two dashes in one sentence, with text between them that contains no `;`, `:`,
`|`, protected period or other dash and does not cross a line that opens a list item.
An em dash counts spaced or unspaced; an en dash counts only spaced; a dash beside a
digit is a range. Two filters then drop shapes that match by accident:

- A wrapped span is two `term — gloss` lines, not a fence, when the opening dash
  follows at most two words from the start of its line and the closing dash follows
  at most three words on its own line. The opening line is measured from the line
  start, which may precede the sentence start.
- A span whose first word is also the first word after the closing dash is a sequence
  (`argv — then the config — then the defaults`).

` -- ` is not a fence.

## Changes

- `commentlint/interpolation.py`, new: `comma_fenced(text)` and `dash_fenced(text)`,
  each returning `premise.Span` objects with offsets into the original text.
- `commentlint/premise.py`: `masked()` is public and shared, and blanks double-quoted
  strings as well as code spans. A code span may wrap across lines, capped at 200
  characters, but not across a sentence end, so a stray backtick cannot blank the
  sentence after it.
- `commentlint/cli.py`
  - A `CHECKERS` table (P14, P13, P15) drives both the scan path and `--text`. The
    first checker that fires names the finding and the comment is not scored; the
    order only decides which id a comment matching two shapes is reported under. One
    `_finding_spans(c, rule, spans)` replaces `_finding_premise`; the `clauses` field
    stays and a `label` field carries the per-rule wording the ts printer also uses.
  - The run key's `checks` entry is the tuple of the two modules' `CHECK_VERSION`s, so
    a bump in either changes the key and no sum can collide.
- `data/rules.json`: P15 added. `CLAUDE.md` and docs/architecture.md say 27 rules.
- `data/p13_pairs_eval.py`, new: prints the research report's tables.
- `commentlint/backends.py`: its own module docstring had the P13 shape; the commas
  are dropped.
- `tests/test_interpolation.py`: positives from both corpora and constructed ones; the
  known misses; one negative per filter, including the adverbial-subject,
  subordinator, clause-subject, list-comma, `-ous` word, quoted-string, semicolon,
  digit-range, table-row, term-gloss, sequence and ` -- ` classes; the exact firing
  sets over both committed corpora (P15's clean set pinned by count and digest, and
  the revision outcome split pinned as 41 kept / 87 bracketed / 120 rewritten); two
  P14 regressions for the code-span mask; a self-scan of the repository under all
  three checkers.
- `tests/test_cli.py`: P13 and P15 default-on, exit 1, `--disable-rule`, JSON shape
  with `label`, one finding per comment when two checkers match and which id wins,
  `--text` reporting the same rule as a scan, `--list-rules` showing P15.
- Docs: README heuristic paragraph; docs/architecture.md module row and rule count;
  docs/scanning.md not-scored bullet; todos.md.

## Decisions

- **P15 default-on.** The repo's convention puts per-project style calls (C10, C11,
  C13) in `DEFAULT_DISABLED`, and the strongest case against default-on is that C13
  already covers `—` as a non-Latin-1 character and ships off. P15 ships on because
  the tool's stated purpose is a hard inhibition of LLM prose tics, the author's
  revisions remove the fence five times in six and bracket it a third of the time,
  and turning P15 off is one config line. The footprint (189 of 5,998 comments in the
  author's own corpus) makes this a breaking change for CI users and belongs in a
  minor version bump.
- **P13 is enforced by the rule text, not the data.** Three of the four clean defects
  survived a revision untouched. The CLAUDE.md prose section states the rule
  explicitly, so the checker enforces it.
- **Subordinators and prepositions are not openers.** They produced every constructed
  false positive and no corpus true positive. The cost is the one revision-confirmed
  comma defect, recorded as a known miss.
- **` -- ` is not a fence.** Neither corpus contains one, so there is no evidence
  either way, and it is the form this repository's own comments use.
- **Checkers are exclusive, in both modes.** One finding per comment keeps the output
  and the exit code simple, and `--text` gives the same verdict as a scan.

## Not in scope

- Retraining or relabelling P13's head. Its 21 labels are noisy, and the checker makes
  the head redundant for the two shapes it covers.
- A comma check for adverbial clauses, or for fragments with no verb after the closing
  comma. Both are recorded as known misses.
- Spaced hyphens as a fence (` - … - `). The labelled pairs hold one such case.

## Risks

- P15's footprint. 189 comments in the author's own untouched corpus fire. The
  revision data says five in six would change on review and one in six is prose the
  author accepted. A first scan after upgrading will show that. `--limit` truncates
  the ranked list from the end, and heuristic findings sort after the model's, so a
  long P15 tail is what a limit cuts first.
- The `-s` verb test. `answers` reads as a verb; the plain-noun-phrase filter and the
  verb-count test keep that to misses rather than fires on the corpora, and the
  fixtures pin the constructed cases.

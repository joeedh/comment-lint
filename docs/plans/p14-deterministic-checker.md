# P14 as a deterministic checker

**Status: implemented.** Written 2026-08-31; pressure-tested, implemented, reviewed and
revised the same day.

## Context

- docs/research/p14-bracket-supporting-premise.md records five failed routes to a P14
  head or general checker and concludes that no predicate over the `, and <clause>, so`
  shape beats 0.5 precision.
- That conclusion holds for the general defect but not for one sub-case. Measured
  against the same 92 hand-labelled chains (12 defects, 47 peer premises, 33 artifacts),
  the predicate below fires 3 times, all defects, 0 false positives. It never fires on
  either side of the 20 authored pairs, and on the 2,741-row revision corpus it fires
  only on two after-texts that are clean-corpus defects carried through unrelated
  revisions.
- The tool exists to hard-block prose regressions in LLM-written comments. Advice does
  not do that, so the checker ships on by default and counts toward exit code 1, like
  C2. Precision governs every design choice below; corpus recall is 3 of 12.
- A spaCy parse reaches 5 of 12 for 200 MB of dependencies and was rejected.

## The rule the checker enforces

When the first clause is a copular statement about its subject (`X is Y`) and the clause
coordinated with `and` before a `, so` conclusion opens with a bare pronoun, the pronoun
continues X whichever side of the copula it points at, and the second clause is a
supporting premise written as a peer assertion. Reattach it as a parenthesis or a
relative clause, or reduce the coordination.

    defect  Building the playable is the question, and it is pure and writes
            nothing, so the check answers with the real projection.
    defect  Art notes are the only thing an author says, and they are authored
            input rather than a prompt override, so setting one re-keys the tasks.

The object-anchored gloss (`…arranging the mesh, and a popup is not part of the mesh,
so…`) is the rest of P14 and stays undetectable: it is structurally identical to a
correctly coordinated peer premise (`…snapshot of the workspace, and a browser preview
has no workspace, so…`). The checker does not attempt it, and after a transitive verb
(`The loader reads the config file, and it is shared, so`) it stays silent for the same
reason: the pronoun may continue the object.

## Predicate

All of the following, evaluated per sentence after code spans are blanked and
abbreviation periods protected on a same-length copy, on the regex
`,\s+and\s+(mid),\s+so\b` where `mid` has 8–120 characters and no comma, colon,
semicolon, period or protected period:

1. `mid` contains no dash of any kind and no backtick.
2. The first word of `mid` is one of `it they each neither both none`, and a verb
   follows it directly or after one adverb (`it still runs`). After `each`, `neither`,
   `both` and `none`, which double as determiners, only an auxiliary counts as the verb,
   because `neither pass is` would otherwise read `pass` as one. `this`, `these` and
   `those` are excluded: in a code comment they are deictic far more often than
   anaphoric.
3. For `it`, the clause is not expletive or cleft: `it is safe to`, `it is not clear
   why`, `it turns out`, `it is the caller who`, `it takes`, `it makes sense`.
4. C1 is the text before the `, and` cut back to the last clause boundary (`:`, `;`, a
   dash, `, and`/`, but`/`, because`/`, which`/…, a bare `because`/`since`/`while`/
   `whereas`/`unless`/`although`), with a subordinate clause that opens the sentence
   (`When the flag is set, `) removed.
5. The pronoun does not already occur in C1.
6. C1's first verb, within its first eight words, is a copula (`is`, `are`, `was`,
   `were` and their negations). Any other listed verb, or none, keeps the checker
   silent. The copula is not followed by a preposition (`The socket is in the pool, and
   it …` names a second noun).
7. C1's subject is the words before the copula, cut at the first preposition so `The
   list of handlers` has the head `list`. Its first word is not a pronoun,
   demonstrative, `there`/`what`/`that`, or an indefinite (`nothing`, `everything`,
   `something`, `nobody`, …).
8. Number agrees: `it` needs a singular subject head; the plural pronouns need a
   plural one (`-s` head or an `and`-coordinated subject).

Each filter errs toward silence. That is deliberate.

## Changes

- `commentlint/premise.py`, new. Regex only. Exposes `supporting_premise(text) ->
  list[Span]`, each span carrying the offending `, and … , so` text, the pronoun and
  offsets into the original text, and `CHECK_VERSION`.
- `commentlint/comments/sentences.py`: `protect()` split out of `split()` so the
  checker can use the same abbreviation guard while keeping offsets.
- `commentlint/cli.py`
  - Scan path: after the C13 check, on every prose comment (code comments and
    markdown chunks alike), run the checker unless disabled; emit a finding with
    `source: "heuristic"`, rule `P14`, and a `clauses` list carrying the span texts,
    the way C13 carries `codepoints`. The comment is then not sent to the model, like
    C2 and C13: one hard finding per comment. Under `--split-sentences` this skips
    every sentence of the flagged comment. The ts printer shows each clause dimmed
    under the comment.
  - `--text` path: the checker runs too. One verdict line, `VIOLATION` when either the
    gate or the checker says so, then a `ruleP14 flag <clause>` line per span, then the
    ranked rules; exit 1 when it fires. JSON gains a `heuristics` list.
  - Run key: `"checks": premise.CHECK_VERSION`, so a predicate change invalidates
    cached findings without a release.
- `data/rules.json`: P14 keeps its id and name; the description names the checkable
  sub-case so `--list-rules` says what actually fires.
- `data/p14_checker_eval.py`: runs the shipped checker over each chain's comment as
  one more row so the report's table reproduces; the script puts the repo root on
  `sys.path` itself.
- `tests/test_premise.py`: ten positives; two known misses; one negative per filter,
  including the expletive, demonstrative, determiner, transitive-verb, indefinite,
  prepositional, `X of Y`, leading-subordinate, colon, unspaced-dash, code-span and
  protected-abbreviation classes the two reviews constructed; the exact firing set
  over all three committed corpora.
- `tests/test_cli.py`: default-on and exit 1; `--disable-rule P14`; JSON shape; concise
  `flag` tag; `--text` fires, exits 1, prints one verdict; a flagged comment yields no
  model finding, with and without `--split-sentences`; markdown prose reaches the
  checker; `CHECK_VERSION` changes the key.
- Docs: README heuristic paragraph; docs/architecture.md module row; the research
  report gains an "Attempt 6" section and a new title; `structure.py`'s docstring drops
  the "no predicate beats 0.5" sentence; todos.md.

## Decisions the reviews forced

- **Copula only.** The first implementation checked number agreement and nothing
  else, so `The loader reads the config file, and it is shared with the CLI, so` fired
  on the object while the docs claimed subject continuation. Requiring a copular first
  clause makes the claim true and costs one corpus positive (`Verification runs here
  …, and it runs at build time, so`).
- **Auxiliary only after determiner-like pronouns.** `each process owns`, `both sides
  are` and `neither pass is` passed the finite-verb test on the noun. The fix costs the
  corpus positive `and neither reaches the loop's event stream, so`.
- **Default-on, not `DEFAULT_DISABLED`.** The first reviewer proposed one release off
  by default. The tool's purpose is a hard inhibition, and the fix for each
  false-positive class found was a filter, not a softer finding. The risk is recorded
  below.
- **`continue` after a P14 finding.** Without it one comment produced two findings and
  was printed twice. C2 and C13 already skip the model; P14 now matches.
- **Colon inside the span excludes it.** The single revision-corpus candidate had one
  (`…, and they are authored input rather than a prompt override: they go into the
  prompt…, so`). The `so` closes the clause after the colon, and a hard finding should
  not depend on reading past it. The colon-free form is a positive fixture; the colon
  form is a negative one.

## Not in scope

- P13. Same logic applies (its shape is mechanical) but it is a separate decision
  about whether paired dashes are in the rule.
- A spaCy extra. Recorded in the research report as measured and declined.
- Any change to the trained model or its labels.

## Risks

- Three true positives on labelled data. The 1.00 is "no counterexample found"; the
  Wilson 95% lower bound on 3/3 is about 0.44. The corpora contain none of the
  false-positive classes the reviews constructed, so the fixtures in
  `tests/test_premise.py` are the only guard on them; the corpus tests keep known data
  honest and nothing more. A false positive found in the wild is a feedback ledger
  entry and a new negative fixture, and a class of them is a new filter plus a
  `CHECK_VERSION` bump.
- A propositional `it` after a copula fires (`the worker is idle, and it is logged,
  so`). That is treated as the rule's own case, since `(which is logged)` is the
  prescribed repair, but it is a judgement rather than a measurement.
- The subject cutter is a closed list. A first clause whose verb is unlisted goes
  silent, so widening the list widens recall and must re-run against the corpus tests.

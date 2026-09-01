# P14, bracket-supporting-premise: six attempts, one checker

Written 2026-08-31. Attempts 1 to 5 record why each route to a trained head or a
general checker was abandoned, so nobody walks them again. Attempt 6, added the
same day, found that one sub-case of the defect is decidable with no false positive
on the labelled data, and that sub-case ships as `commentlint/premise.py`. The rest
of P14 stays a taxonomy entry with no head and no checker.

## What the rule is

A clause that only supports a following `so` conclusion has to be bracketed or
attached as a relative clause, not coordinated with `and` as a peer assertion.

    defect  Everything else here is about arranging the mesh, and a popup is
            not part of the mesh, so splitting one is wrong.
    repair  Everything else here is about arranging the mesh (which the popup
            is not part of), so splitting one is wrong.

It is distinct from P13 `bracket-not-comma-alternative`, whose trigger is paired
commas fencing a subordinate alternative and whose fix is punctuation alone.
P14's trigger is a coordinating conjunction and its fix is syntactic.

The candidate shape is `, and <clause>, so` within one sentence.

## Attempt 1: mine it with a silver-label heuristic. Failed.

Every other trained rule gets its positives from a conservative regex comparing
a revision's `before` against its `after`. The shape matches 37 before-texts in
`data/violation_pairs.jsonl`, but hand-reading all 37 gives:

| | n |
|---|---|
| the regex spanned a sentence boundary and matched nothing real | 23 |
| a correctly coordinated peer premise, left alone by the revision | 10 |
| the defect, fixed by the revision | 4 |

No surface signature separates the four from the other 33. Every candidate
scored false positives against rewrites that merely gained a `which` or a
parenthesis somewhere else in the comment. The heuristic was written, measured
and removed; `data/label_heuristics.py` carries a note saying P14 has none on
purpose.

Noisy positives are worse than missing labels here, because a silver label
trains the gate as well as the head.

## Attempt 2: author the pairs by hand, then retrain. Failed.

`data/p14_pairs.py` writes 20 pairs, 5 with real defect text and 15 derived by
de-bracketing a premise the author had already bracketed. Merging them clears
`MIN_SUPPORT` and gives P14 a head. The head is noise. Pooling 33 held-out
positives over 12 reseeded splits of the linear model:

| | |
|---|---|
| P14 in the top 3 for a true P14 comment | 0% (median rank 10 of 17) |
| the gate called a P14 comment bad at all | 6 / 33 |
| P14 ranked top-1 on a comment that is not P14 | 78 / 13575 |

A single seeded split is worthless for this and misled the first reading of it.
One split put a single P14 positive in test and reported AUC 0.680 on n=1, and
adding rows reshuffles the split, so every other rule's numbers moved as well.
The multi-seed harness with P13 as a same-size control is what produced the
table above.

The attribution half of that failure is not specific to P14. P13 ships today
with 21 positives and also ranks its own comments 0% at top-1, median rank 10.
What separates P14 is the gate: 6 of 33 against P13's 15 of 30.

`data/labeled_all_v2.jsonl` was restored from backup afterwards and holds no P14
rows.

## Why: the repair barely moves the vector

Median cosine distance between the two sides of a pair, in the exact feature
space `train_linear.py` fits:

| rule | n | median distance |
|---|---|---|
| **P14** | 20 | **0.040** |
| P10 | 759 | 0.086 |
| P13 | 21 | 0.102 |
| P4 | 116 | 0.164 |
| P1 | 233 | 0.305 |
| C12 | 61 | 0.479 |

P14 is the smallest of every rule measured. The repair moves `and`, a comma, a
bracket and sometimes `which`, which are among the most common tokens in the
corpus, so idf drives their weight to near zero. P10 survives a comparable
distance because it has 759 positives and the token it moves (`*`) is rare.

## Attempt 3: features that can see clause structure. Half worked.

`commentlint/structure.py`, behind `CL_STRUCT=1`, adds two families computed
from a single comment so they are available at predict time:

- **A**, the sequence of connectives in a sentence as n-grams, so `, and …, so`
  is one feature rather than four unweighted unigrams.
- **B**, whether the second conjunct points back into the clause before it.

Over the same 12 reseeded splits this moves P14 attribution from 0% to 85%
top-1 and the pair distance from 0.040 to 0.357, and improves P13 as a side
effect, from 0% to 7% top-1 and median rank 10 to 6.

The gate does not move. It stays at 6 of 33, because the chain shape is not
evidence of a defect: correct prose coordinates two peer premises with exactly
the same punctuation. Solving the representation problem did not touch the
detection problem, and detection is what a linter needs.

`tests/test_structure.py` pins the shapes the features claim to separate.

## Attempt 4: feature family C, lexical and discourse context. Failed.

A lexical window either side of the connective, plus given/new over the whole
second conjunct, the definiteness of its subject, and where the back-reference
falls inside it.

| variant | precision (floor 0.50) |
|---|---|
| A and B alone | 0.07 |
| A, B and C | 0.10 |
| C's discourse features without the lexical window | 0.10 |
| A, B and C plus 19 peer-premise hard negatives | 0.03 |

Cosine distance and the gate were identical to A and B alone. The hard negatives
made it worse rather than better, which is the informative part: the features
cannot separate a gloss from an independent premise, so training against peer
premises suppresses the true positives along with them.

The plumbing was verified before the result was believed (712 kept features
against 331, symmetric difference 25 against 8), so this is a real negative
rather than a wiring fault. Family C was removed.

## Attempt 5: a deterministic checker instead of a head. Failed.

If the model cannot gate it, a regex plus a predicate over the second conjunct
might, reporting candidates rather than detections. Measured against
`data/clean_comments.jsonl`, 5998 untouched repo comments. The shape matches 92
times across 91 comments, 1.52% of the corpus. Hand-labelling all 92:

| class | n | share |
|---|---|---|
| **D** gloss coordinated as a peer, the defect | 12 | 13% |
| **P** genuine peer premise, correctly coordinated | 47 | 51% |
| **A** not a two-premise chain at all | 33 | 36% |

Class A repeats attempt 1's finding on a second corpus. A third of the matches
are a three-item list closing with `and`, two coordinated verb phrases sharing
one subject, or a span the regex crossed an em dash to reach:

    A  Reads the same way resolveKeys does, never throws, and returns no key
       values, so it is safe to send to a renderer.          (three-item list)
    A  Pure, and with no `pathux` import, so the node-only jest project can
       test the proxy's two rules.                        (no verb of its own)

Against a base rate of 0.13:

| predicate | fires | TP | FP | precision | recall |
|---|---|---|---|---|---|
| shape only | 92 | 12 | 80 | 0.13 | 100% |
| + binary-chain filter | 61 | 9 | 52 | 0.15 | 75% |
| given subject, any content word | 22 | 2 | 20 | 0.09 | 17% |
| given subject, head noun only | 9 | 1 | 8 | 0.11 | 8% |
| anaphoric subject | 11 | 5 | 6 | 0.45 | 42% |
| anaphoric or given | 31 | 7 | 24 | 0.23 | 58% |
| bare-pronoun subject | 6 | 4 | 2 | 0.67 | 33% |
| bare pronoun or short anaphoric | 10 | 5 | 5 | 0.50 | 42% |

Labels are one annotator's reading, not adjudicated ground truth. The criterion
for D: the second conjunct only makes sense as a rider on the first, and can be
reattached to it as a parenthesis or a relative clause without loss.

### The measurement that had to be retracted

Given/new was reported at 1.00 precision and 100% recall earlier in the same
investigation, and it is 0.09 here, below the base rate. Two things were wrong
with the earlier number:

- **The sample was enriched.** Those 15 cases came from
  `data/violation_pairs.jsonl`, comments that were actually revised, where the
  defect rate is about six times the rate in ordinary comments.
- **The refinement was tuned on the cases it was scored against.** Dropping
  `that` and `one` from the anaphor set was chosen because it removed the only
  false positive among those 15.

The failure generalises. A whole comment is about one topic, so nearly every
second conjunct shares a content word with the text before it, a peer premise as
readily as a gloss. Overlap separated the two only in a sample where the peer
premises happened to introduce new APIs by name.

An earlier count of 148 matches in this corpus was also wrong. It came from a
regex that was not scoped to a sentence, so it counted spans running from one
sentence's `and` to the next sentence's `so`.

### What survives is a different rule

A second conjunct whose subject is a bare pronoun is a reducible coordination,
and 4 of the 6 such cases are the defect:

    D  Verification runs here because this is the earliest place both
       registries exist, and it runs at build time, so ...
    D  A note is authored input, ..., and it goes into the prompt, so ...

Six firings across 5998 comments is one alert per thousand, and split-half
resampling puts the 5-95% interval at [0.00, 1.00]. That 0.67 is three coin
flips. The widest variant that clears the base rate by a useful margin,
`bare pronoun or short anaphoric`, fires ten times at precision 0.50 with an
interval of [0.20, 0.75].

`python data/p14_checker_eval.py` reproduces both tables from the hand labels.

## Attempt 6: the subject-continuation sub-case. Shipped.

The tool exists to hard-block prose regressions, so advice at 0.5 precision was
ruled out and the question became whether any predicate reaches a precision a hard
failure can stand on, at whatever recall is left.

Reading the `bare-pronoun subject` row's two false positives gave the start of the
answer. One was `[28]`, `every node above it points at it, and it points at every
node it blocks`, where the pronoun continues a referent the first clause already
names with the same pronoun. The other was `[72]`, `Synchronous and pure, and it
...`, where the first clause has no verb and so no subject to continue. Those two
filters, number agreement and a dash exclusion gave 4 of 12 with no false positive
on the corpus. Two review rounds then constructed false positives the corpus does
not contain (below), and the predicate that shipped adds one condition that makes
the docs' claim true: the first clause must be copular. In `X is Y, and it ...` the
pronoun continues X whichever side of the copula it points at, while after a
transitive verb (`The loader reads the config file, and it is shared, so`) it may
point at the object.

| predicate | fires | TP | FP | precision | recall |
|---|---|---|---|---|---|
| bare-pronoun subject | 6 | 4 | 2 | 0.67 | 33% |
| bare pronoun, strict filters, any verb | 4 | 4 | 0 | 1.00 | 33% |
| **shipped: copular subject continuation** | 3 | 3 | 0 | 1.00 | 25% |

The copula condition costs `[35]`, `Verification runs here ..., and it runs at build
time, so`. Treating `each`, `neither`, `both` and `none` as determiners unless an
auxiliary follows (`neither pass is` would otherwise read `pass` as the verb) costs
`[43]`, `and neither reaches the loop's event stream, so`. Both are recorded as
known misses in the tests.

Out of sample: 0 fires on the 20 authored repairs; 0 fires across the 2,741
before-texts of `data/violation_pairs.jsonl` (the one candidate, `Art notes are the
only thing ..., and they are authored input rather than a prompt override: they go
into the prompt ..., so`, is a defect but carries a colon inside the span, which the
shipped predicate excludes); 2 fires on after-texts, both the same clean-corpus
defects carried unchanged through a revision that edited something else. Three true
positives and no counterexample across the corpora. The Wilson 95% lower bound on
3/3 is about 0.44, so 1.00 means "none found" rather than a measured rate.

A pressure test of the plan then constructed false positives the corpora do not
contain: expletive and cleft `it` (`and it is safe to dereference ..., so`, `and it
turns out ..., so`, `and it is the caller who ..., so`), deictic `this` (`and this is
where the old name last appears, so`), determiner uses (`and neither the pool nor the
handle ..., so`), verb-initial doc comments whose "subject" the cutter read as the
verb phrase (`Parses the header, and it is cached, so`), and indefinite subjects
(`Everything below reads the snapshot, and it is taken once, so`). None of these
shapes is followed by `, so` anywhere in 10,281 distinct corpus texts, which is the
only reason the corpus numbers were clean. A review of the implementation then added
four more classes: a determiner pronoun before a plural noun (`and each process owns
a socket, so`), an object-anchored `it` whose number happened to agree with the
subject head (`Every consumer reads the snapshot, and it is taken once, so`), an `X
of Y` subject whose head was read from Y (`The list of handlers is fixed, and they
run in order, so`), and a subordinate clause opening the sentence being read as the
first clause. The shipped predicate has a filter per class, drops
`this`/`these`/`those` from the pronoun set, accepts only a copular first clause, and
stays silent whenever the first clause's subject cannot be found rather than
guessing it. `tests/test_premise.py` carries one negative fixture per class.

A spaCy dependency parse was measured on the same labels first. A real subject
boundary and a clausal-coordination test reach 5 of 12 with no false positive, one
more than the regex, by climbing from `this is the earliest place ...` to the
matrix clause `Verification runs ...`. It costs 200 MB of packages, a 1.4 s
import, and a numpy pin beside scikit-learn's, and was declined.

What the sub-case does not cover is the object-anchored gloss, which is most of
P14. The canonical example, `... arranging the mesh, and a popup is not part of the
mesh, so`, is structurally identical to the labelled peer premise `[0]`, `...
snapshot of the workspace, and a browser preview has no workspace, so`: same
shape, same shared noun, same position. The 20 authored pairs are all of this kind,
and the checker fires on none of them, on either side. That half of the rule has no
checker, as attempts 1 to 5 concluded.

`tests/test_premise.py` pins the positives, the two known misses, one negative per
filter, and the exact firing set over all three committed corpora, so a widened
predicate has to re-earn its precision on known data before it ships. The plan is
docs/plans/p14-deterministic-checker.md.

## Why the rest caps out

- **The defect is rare.** Twelve instances in 5998 comments, 0.2%. A perfect
  checker finds twelve things. That ceiling, rather than any precision number,
  is the reason to stop.
- **The shape is ambiguous by construction.** Correct prose uses the same
  punctuation for two peer premises. The difference is whether the second
  conjunct predicates about the first one's subject, which needs coreference
  resolution rather than a regex or a bag of n-grams.
- **A third of the matches are not chains.** Both corpora agree on this. The
  binary-chain filter that tries to remove them costs 3 of the 12 defects while
  still keeping 11 artifacts, so it buys 0.02 precision for 25% of the recall.

## What would change the answer

- **A real subject boundary.** The subject is currently cut at the first word in
  a hand-written verb list, which mis-splits on any conjunct opening with an
  adjunct, as in `on a machine without it the first call would throw`. A
  rule-based tagger over the closed classes is a precondition for any coreference
  test rather than an improvement on its own.
- **Coreference between the two conjuncts' subjects.** This is what separates a
  defect whose `it` repeats the first subject from a correct clause whose `it`
  points at a different noun. It is also the point where a regex stops being the
  right tool.
- **An order of magnitude more positives.** Twelve cannot support a threshold,
  and hand-authoring cannot supply the rest, as attempt 2 showed. The labelling
  would have to run over prose outside this repository.

## Where the code is

| | |
|---|---|
| the taxonomy entry | `data/rules.json`, id P14 |
| why there is no heuristic | `data/label_heuristics.py`, module docstring |
| the 20 authored pairs and the retrain result | `data/p14_pairs.py` |
| families A and B, behind `CL_STRUCT=1` | `commentlint/structure.py` |
| what those features pin | `tests/test_structure.py` |
| the checker evaluation and its hand labels | `data/p14_checker_eval.py` |
| the shipped checker | `commentlint/premise.py` |
| what it fires on and stays silent on | `tests/test_premise.py` |
| the plan | docs/plans/p14-deterministic-checker.md |

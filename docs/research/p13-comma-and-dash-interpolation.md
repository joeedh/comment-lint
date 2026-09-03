# P13, bracket-not-comma-alternative: what the data says the rule is

Written 2026-08-31, after the P14 checker shipped
(docs/research/p14-bracket-supporting-premise.md). P13 has a trained head with 21
positives that ranks its own comments top-1 0% of the time. This records what those
21 positives actually are, measures the two shapes they contain against both
corpora, and gives the numbers behind the two deterministic checkers that followed.
Every table below is printed by `python data/p13_pairs_eval.py`.

## The labelled P13 pairs are mostly a dash rule

`data/rules.json` describes P13 as paired commas fencing a subordinate alternative.
Classifying the 21 labelled pairs in `data/labeled_all_v2.jsonl` by what the
revision changed:

| before had | after | n |
|---|---|---|
| a paired-dash interpolation (`— … —`) | parentheses | 13 |
| a comma-fenced interpolation | parentheses | 2 |
| a comma-fenced phrase | the commas dropped | 3 |
| a spaced-hyphen interpolation (` - … - `) | parentheses | 1 |
| something else | | 2 |

The silver heuristic that produced them (`data/label_heuristics.py`) is
`[a-z],\s+[a-z ]{4,40},\s+[a-z]` in `before` plus a parenthesis anywhere in `after`,
which is loose enough to accept any comma-bearing comment that gained a bracket.
Dash interpolations carry commas nearby often enough that the heuristic labelled
them, and the head learned dashes. The head therefore ranks a dash shape, and the
rule text describes a comma shape.

## Dashes: the author's revisions remove them five times in six

Over the 2,741 rows of `data/violation_pairs.jsonl`, a before-text holds a paired
em- or en-dash interpolation in one sentence 248 times under the shipped predicate.
What the revision did with it:

| outcome | n | share |
|---|---|---|
| dashes replaced by parentheses | 87 | 35% |
| interpolation rewritten away | 120 | 48% |
| dashes kept | 41 | 17% |

The prescribed repair (parentheses) was applied a third of the time, the
interpolation disappeared for some other reason half the time, and the author
accepted the dashes a sixth of the time. The 41 kept cases read like the converted
ones (`a skill that degraded — no description, no body, a script naming a missing
file — reads as fine`), so there is no sub-class to carve out. The rule is a style
preference, but a consistent one, and paired em dashes are also the most
recognisable tic of LLM-written prose. 47 after-texts still hold a fence.

`data/clean_comments.jsonl`, the 5,998 untouched comments, holds 189 comments with
such a fence (194 fences, about one comment in thirty). A hard finding on the shape
therefore lands on existing prose at roughly sixty times P14's rate. That footprint
is why the dash check ships under its own rule id, P15, rather than inside P13: a
project that disagrees turns off one line without losing the comma check.

The shape is two dashes in one sentence with text between them. An em dash counts
spaced or unspaced, since unspaced pairs (`legal—looping to a hub—so`) are the form
most LLMs emit; an en dash counts only spaced, because unspaced it is a range or a
compound (`3–5`, `Chicago–New York`). A dash beside a digit is a range (`3 – 5`). The
span may wrap across lines but not across `;`, `:`, a table pipe, a protected
abbreviation period, another dash, or a line opening a list item; code spans and
double-quoted strings are blanked first. Two further filters came out of the
implementation review, and both describe shapes neither corpus contains:

- A wrapped span whose opening dash follows at most two words at the start of its
  line, and whose closing dash follows at most three words on its own line, is two
  `term — gloss` lines (`fast — no scoring` over `full — everything is scored`), not a
  fence. The term is measured from the start of the line rather than the start of the
  sentence, because a fence whose sentence begins mid-line (`… has to say. Retyping
  itself — what a draft is … — is`) otherwise reads as a gloss.
- A span whose first word is also the first word after the closing dash is a
  sequence (`argv — then the config file — then the defaults`), not a fence.

` -- ` is left out: neither corpus contains a single ` -- … -- ` fence, so there is
no evidence about it, and it is the form this repository's own comments use. The one
spaced-hyphen fence in the labelled pairs is the same situation with one data point.

## Commas: the rule as written, measured

The shape the rule text describes is a plain noun phrase, then a comma-fenced phrase
opening with a coordinator or alternative marker, then the noun phrase's verb:

    A file that is not an image, or one carrying the mock marker a real backend
    refuses, fails at upload ...
    the prompt, and so the task hash, is unchanged until ...

A loose regex for `<subject>, <opener …>, <word>` with prepositions and subordinators
among the openers finds 13 candidates in the clean corpus. Hand-labelled:

| class | n | examples |
|---|---|---|
| the defect | 8 | the two above; `which pane, and where the line falls, are answers` |
| regex artifact | 3 | a dash inside the span; a list comma read as the closer |
| a short adverbial | 2 | `which, in this app, means`; `` `x`, when given, drops `` |

Four filters separate them, and each is a property of the shape rather than of
these sentences:

- **Only coordinators and alternative markers open a fence** (`or and nor as well as
  rather than not but not plus including such as like unlike especially
  particularly`). Subordinators and prepositions fence ordinary adverbial clauses
  that English punctuates with commas (`The handler, if one is registered, runs
  first`), and on the corpora they contributed no true positive. This costs the one
  revision-confirmed comma defect (`Prose under another scene's heading, for the one
  frame between the click and the read, is`), which the revision bracketed.
- **The subject is a plain noun phrase, not a clause or an adverbial.** The artifact
  `a host that knows how to find the art … supplies them, and this file knows nothing
  about characters, scenes …` has a whole clause before the first comma; a noun
  phrase carries at most one finite verb per relativizer (`A file that is not an
  image` has one `is` and one `that`). A word after a determiner is a noun whatever
  its ending (`The tests, and the fixtures they rely on, are slow` is a defect, not a
  clause). `By default, with no config file present, findings are printed` has a
  sentence adverbial there, and the word after the closing comma is the real subject.
- **The fenced span is at least four words.** `in this app` and `when given` are the
  adverbials English fences with commas as a matter of course.
- **The word after the closing comma is a verb.** After a genuine interpolation the
  subject's predicate resumes (`, is`, `, are`, `, fails`, `, do`, `, needs`); after a
  list comma a noun follows (`, scenes`). Capitalised words, `-ous`/`-less`/`-ness`
  words and a short list (`regardless`, `status`, `canvas`, …) are not read as verbs.

| corpus | fires | defect | notes |
|---|---|---|---|
| clean, 5,998 comments | 4 | 4 | |
| revision before-texts | 2 | 2 | 1 rewritten, 1 kept |
| revision after-texts | 3 | 3 | the shape kept through a revision that changed something else |

Known misses, each the cost of a filter: the bracketed `for the one frame` case above;
`Synthesizing the missing answers here, …, is …` (`answers` has no determiner, so it
reads as a finite verb to the `-s` test); `Which pane the author is in, and which pane
may be covered, are …` (`is` with no relativizer reads as a clause); the fragments
`The remembered projects, and the one that is open, as …` where no verb follows the
closing comma.

The revealed preference here is weaker than for dashes: of the four clean defects,
three were carried through a revision unchanged. The comma check is enforced because
the CLAUDE.md prose section states it in so many words, not because the revisions
prove it.

A pressure test of the plan constructed the adverbial-subject and subordinator
classes above, plus for P15 two asides split by a semicolon, spaced digit ranges,
quoted strings, table delimiter rows and term-gloss lists; the implementation review
added the coordinated-gerund subject (`Keeping that import here, and importing this
module lazily, is`, which is the P13 shape and was in the repository's own prose),
plural subjects after a determiner, gloss lines without list markers, sequences, and
unspaced em dashes. None of these occurs in either corpus, so the corpus tests could
not have caught them. Each has a fixture in `tests/test_interpolation.py`, and a
self-scan test keeps the repository's own prose silent under all three checkers.

## What ships

| | rule | default | shape |
|---|---|---|---|
| comma-fenced interpolation | P13 | on | plain NP `, <coordinator …>, <verb>` |
| dash-fenced interpolation | P15 | on | two em dashes, or two spaced en dashes, in one sentence |

Both are deterministic checkers alongside P14's, in `commentlint/interpolation.py`.
P13's model head is unchanged; a checker firing is reported as `heuristic` and the
comment is not also scored. The plan is docs/plans/p13-p15-interpolation-checkers.md.

## Where the code is

| | |
|---|---|
| the checkers | `commentlint/interpolation.py` |
| what they fire on and stay silent on | `tests/test_interpolation.py` |
| the tables above | `data/p13_pairs_eval.py` |
| the P13 silver heuristic that mislabelled dashes | `data/label_heuristics.py` |
| the plan | docs/plans/p13-p15-interpolation-checkers.md |

## Conventions
* Docs go in docs/
* Research reports go in docs/research
* Plans go in docs/plans 
  - Always write plans into the repo
  - When a plan is completed it should be pressure tested with an agent, and the 
    results folded back in.

## Orientation
* docs/architecture.md describes how the tool is put together and why. Read it before
  moving anything across a module boundary.
* The taxonomy is data/rules.json: 25 rules, of which 16 have enough examples to train.
* Scoring has two stages. A gate decides whether a comment breaks some rule, then the
  per-rule heads are ranked against each other. A ranked rule is a suspicion, not a
  detection, and anything that presents it as a detection overstates what the model knows.

## Running things
* `python task.py` lists every task. `python task.py check` runs the tests and mypy
  together and is the gate before a commit.
* Prefer `python task.py typecheck` over calling mypy directly. mypy.ini excludes tests/
  and data/, so naming either on the command line checks nothing while looking like it
  did; task.py carries the file list that is actually correct.

## Invariants
* `cli.py` must not import `backends.py` at module scope. Importing scikit-learn costs
  2.4s and a cached run has to reach its answer without it. tests/test_cache.py fails if
  the import graph regresses, and no other test will.
* Calibrated cuts belong in the model directory's thresholds.json, never in a shared
  constant. A cut describes one model's score distribution and does not transfer.
* `comments/normalize.py` has to match the miner that produced the training data, and
  that miner was never committed. tests/test_extract.py checks the module byte for byte
  against the corpus, so change it only with that test's verdict in hand.
* Model directories are gitignored apart from `model/` and `model_linear/`, which keeps a
  new experiment out of the repository until someone decides to add it.

## Comments 
* Temporary non-doc comments must start with CLAUDENODE: for later stripping.
  - A 'doc' comment is a jsdox or doxygen type comment that explains a specific
    function/property/etc and is meant to be picked up by doc generators.
* Permanent comments cannot exceed 4 lines except:
 - Every 500 lines 
 - Is explaining math

### Prose

These rules govern every piece of prose in the repository. They apply to code comments, to
this file, and to everything under `docs/`.

- **Write plain declarative prose — no epigrams.** State the constraint or decision
  directly: "An empty answer is deliberate and is passed to the model as-is", not "Empty is an
  answer — silence, said out loud." If a sentence needs a second read to parse, rewrite it.
  Specific patterns to catch:
  - **Inverted syntax and personification** — the sentence performs rather than informs.
  - **Metaphorical equations** — "The leak scan is the refusal", "what ships is identity",
    "the project as commands". The connector word varies — do not get hung up on "is"
    versus "as". Say what happens instead: "Refuses if the leak scan finds a known name
    still in the body."
  - **Fragment openers that defer the subject — never use this pattern.** Naming a placeholder
    and then withholding the real content behind a colon or a dash is always wrong: "The
    redactor to scan a report with: the one that wrote it, else one built from the project as it
    stands." Lead with a complete sentence and name each case as you reach it. A doc comment is
    not an exception, and deleting the label is not the fix, because the apposition left behind
    is still headless. Supply a predicate instead. Write "Draws the links beneath the node
    frames in screen space." rather than "The link underlay: a screen-space canvas beneath the
    node frames." or the bare "Screen-space canvas beneath the node frames."
  - **Double negatives** — "the palette cannot be relied on not to". State the positive claim.
  - **Pronouns and ellipses that point outside the sentence** — "the second case", "asking
    twice is how…" — each sentence should carry its own referents.
  - **"Clause A, else B" constructions** — "Resolve a push's destination: the named window
    when it still exists, else the focused window falling back to the most recently focused
    one." Spell out the cases as ordinary sentences instead: "Pushes to the named window if it
    still exists. Otherwise pushes to the focused window, or the most recently focused window
    if none is focused."
  - **Adverbs hung off the end of a noun phrase** — "the next pointerdown anywhere", "the
    handler above". The adverb postmodifies the noun, but the reader cannot tell on first pass
    whether it attaches to the noun or to the clause's verb, and an event or API name coined
    from a verb ("pointerdown") re-parses as a clause when an adverb follows it. Attach the
    qualification to a verb, or state it as its own fact: "the listener is on `window`".
  - **Non-assertive words under a definite** — "any", "anywhere", "ever" range over
    alternatives, so they fight a definite description that names exactly one thing. "A press
    anywhere dismisses it" reads fine; "the next pointerdown anywhere" does not.
  - **Rhetorical emphasis** — bold and italics inside a sentence mark the clause the author
    found most interesting, not the one the reader needs first. Put the load-bearing claim in
    the first sentence and drop the markup. A bolded lead-in that labels a Markdown bullet is
    structure rather than emphasis, and is fine.
  - **A head noun that is not what the thing is** — a module of commands documented as "The
    prompt an asset is generated from, as commands" asserts that the module is a prompt, then
    retracts it through a preposition. Lead with the head noun that names the thing —
    "Commands for the prompt an asset is generated from" — and demote the rest to a
    complement. A trailing ", as X" or ", in the form of X" is the same metaphorical equation
    above smuggled in through an adjunct.
- **Reserve backticks for code symbols.** Backticks belong on identifiers, types, commands,
  and file globs the reader will type. A file path cited mid-sentence as a reference —
  documentation/NodeEditor.md §3 — takes none, because marking it up gives it the same weight
  as the identifiers around it and dilutes them. Markdown link text is the one exception and
  keeps its backticks, where the marking separates a path from the prose around it rather than
  competing with nearby identifiers.
- **Bracket a subordinate alternative rather than fencing it with commas.** Parentheses mark the
  material as skippable, so the reader gets a complete sentence either way; paired commas leave
  it unclear whether the second comma closes an interpolation or opens a new clause. Write
  "Dropping onto itself (or onto a neighbor it would split against) is not a rip". Drop any comma
  that would follow the closing bracket — it separates the subject from its verb.

# Labeling spec: code-comment rule violations

You are labeling real before/after code-comment edits against a fixed rule taxonomy,
to build training data for a comment linter.

Your batch file is a JSON array of objects with keys `i` (an integer id), `before`
(a code comment as originally written), and `after` (the same comment after a human
rewrote it).

For each object, decide which rules the `before` text violates AND the `after` text
fixes. The edit itself is your evidence: a rule applies only if you can see the
change addressing it.

## Taxonomy

- **C1**: A comment placed above an if/branch must describe that branch, not the opposite case; misplacement is a correctness bug.
- **C2**: Commented-out code (a call, import, or block) must be deleted, not kept as commentary.
- **C3**: A comment must not restate what the code already says; it must give a reason, constraint, or consequence.
- **C4**: A comment should cite a named constant's identifier rather than hardcoding its value in prose.
- **C5**: If a comment exists only to translate a bad identifier's meaning, rename the identifier instead of commenting it.
- **C6**: A comment on a call site should say what the call does to the surroundings, not restate arguments already visible on screen.
- **C7**: A comment should state facts a reader could not derive (ordering constraint, platform quirk, live alternative), not defend or justify the design ("why this is the good version").
- **C8**: A doc comment continues its declaration grammatically; it must not re-supply the subject or narrate the signature.
- **C9**: An inline `//` note is an unpunctuated fragment; a `/** */` doc comment is a punctuated sentence. Don't mix the conventions.
- **C10**: Non-doc comments use `//`, not `/* */`.
- **C11**: Non-doc comments are at most 3 lines except rare, genuinely load-bearing context.
- **C12**: Doc comments say what the thing is and any non-obvious contract; they don't restate the signature or narrate the implementation.
- **P1**: Prose must be plain and declarative, not an epigram or aphorism that needs a second read to parse.
- **P2**: The sentence must inform, not perform; avoid inverted syntax and personification.
- **P3**: Avoid "X is Y" / "X as Y" metaphorical equations ("the leak scan is the refusal"); say what happens instead.
- **P4**: Do not name a placeholder and then withhold the real content behind a colon or dash ("The redactor to scan a report with: ..."). Lead with a complete sentence.
- **P5**: State the positive claim instead of a double negative ("cannot be relied on not to").
- **P6**: Avoid pronouns/ellipses that point outside the sentence ("the second case", "asking twice is how..."); each sentence should carry its own referents.
- **P7**: Avoid "Resolve X: the named case when it exists, else the other case" constructions; spell out each case as its own ordinary sentence.
- **P8**: Avoid an adverb hung off the end of a noun phrase ("the next pointerdown anywhere"); attach the qualification to a verb or state it as its own fact.
- **P9**: Avoid "any/anywhere/ever" modifying a definite description that names exactly one thing.
- **P10**: Avoid bold/italic markup inside a sentence to mark emphasis; put the load-bearing claim first as plain text.
- **P11**: The sentence's head noun must be what the thing actually is; don't assert it's an X and then retract that through a preposition ("as commands").
- **P12**: Backticks are reserved for code symbols (identifiers, types, commands, file globs), not for a path or reference cited in prose.
- **P13**: A subordinate alternative should be parenthesized, not fenced with paired commas which create ambiguity about clause boundaries.

## Constraints

- These are comment texts only; the surrounding code was not captured. Rules that
  require seeing the code (C1, C3, C4, C5, C6) usually cannot be judged. Do not
  guess them. C11 (length) and C2 (commented-out code) may be judgeable from text alone.
- Assign multiple rules when more than one clearly applies.
- Assign an empty list when the edit is only copy-editing (typo, tense, rewording
  with no rule behind it), or when you cannot tell. An empty list is a correct and
  common answer. Do not force a label.
- Be strict. A missing label is much cheaper than a wrong one: this is training
  data, and false positives teach the classifier to fire on clean comments.
- P1, P2, and P3 overlap. When a sentence is both an epigram and a metaphorical
  equation, assign both rather than picking one.

## Output

Write a JSON array to the output path you were given: one object per input item,
each `{"i": <the same integer>, "labels": [<rule ids>]}`. Include every input item,
in the same order. Write nothing else to that file.

Your final message should be only: the number of items labeled, and a count per
rule id assigned.

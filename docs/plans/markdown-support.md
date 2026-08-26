# Markdown support for commentlint

**Status: implemented.**

## Context

commentlint today has no way to check a markdown file against anything, because `.md` is not in `comments.EXTENSIONS`: a directory walk never finds it, and even a markdown
file named directly on the command line silently produces zero comments, since
`language_of()` returns `None` for it and `extract()` returns `[]`.

This matters because Claude models infer a 'house prose style' from CLAUDE.md.
While Claude models do infer prose style from surrounding examples they ultimately
fall back to this house model; over time prose errors in CLAUDE.md can spread 
into code comments and documentation.

This plan adds simple markdown support to commentlint.

## Notes:

- Markdown must be opt-in. A tree full of `docs/` and `README.md` files scored
  the same way as a `.ts` file would flood a first run and would run against
  content nobody asked to have checked.
- **The shipped model was not trained for this.** `model_linear`'s 25-rule
  taxonomy (`data/rules.json`) describes why a *code comment* is bad -- stale,
  redundant with the code, missing the why -- not why a piece of *prose*
  violates CLAUDE.md's style rules (epigrams, fragment openers, rhetorical
  emphasis). Feeding markdown paragraphs through the existing gate answers a
  different question than "does this match CLAUDE.md's Prose section," and nobody
  should mistake a gate score on a markdown paragraph for that. This plan builds
  the extraction and plumbing only; a taxonomy and training data for the actual
  prose rules is a separate, later effort and is called out below rather than
  folded in silently.

## Decisions

**Three independent ways in, per the request:**

1. A bare `.md`/`.markdown` file named directly on argv is always extracted and
   scored, config or no config -- the same way `discover()` already adds any
   explicitly-named file outright regardless of extension. This needs no new
   flag; it falls out of how `discover()` already treats named files.
2. `"markdown": true` in `.commentlintrc.json` (or `--markdown` on the CLI) is
   the global enabler: directory walks pick up `.md`/`.markdown` files the same
   way they already pick up `.ts`/`.py`.
3. `"markdownFiles": [...]` in config (or repeated `--markdown-file PATH`) names
   specific markdown files to always check. **Its presence overrides the global
   enabler's directory-scan behaviour**: when `markdownFiles` is non-empty, a
   directory walk does not pick up arbitrary `.md` files even if `markdown` is
   also `true` -- only the listed files (plus anything named on argv, per (1))
   get checked. This is for a repo that wants CLAUDE.md and a couple of style
   guides checked without opting the whole `docs/` tree in.

A glob pattern such as `**/*.md` on the command line is scan-shaped, not a
direct file naming, so it is subject to (2)/(3) like a directory walk would
be -- it does not bypass the enabler the way a bare filename does.

## 1. Extraction (`commentlint/comments/markdown.py`)

Use `markdown-it-py` -- **a new runtime dependency**, not a transitive freebie;
this repo's own `requirements.txt`/`requirements-runtime.txt` pull in nothing
that depends on it (it only showed up in ad-hoc testing via unrelated tools
sharing the Python install). Add it explicitly to `requirements-runtime.txt`.
It is MIT-licensed, actively maintained, and its API is stable, so the
dependency itself is a reasonable bet -- just not a free one. Imported lazily
inside `extract()`, the same way `tsjs`/`pysrc` are, so a run that never
touches a markdown file never pays for the import.

`MarkdownIt("commonmark").parse(src)` produces a flat token stream. Every
prose-bearing block -- a paragraph, a heading, a list item, a blockquote line --
emits exactly one token of type `"inline"`, carrying `.content` (the block's
text, markdown markup like `` ` `` and `**` left in place) and `.map` (its
0-based line span). Fenced code, indented code, and raw HTML blocks never emit
an `"inline"` token, so collecting every `"inline"` token from the flat stream
already excludes them -- no manual open/close tracking needed. Verified
directly against `markdown-it-py` 4.0.0: a blockquote's continuation line comes
back as `.content` with its leading `> ` already gone, and a closed ATX heading
(`## Heading ##`) comes back with both the opening and closing `#`s already
gone. **Do not write block-marker-stripping logic before checking, against the
installed version, whether it has anything left to do** -- list bullets,
blockquote markers, and ATX hashes may already be absent from `.content`, and
the plan's earlier draft assumed stripping was needed without checking. If
nothing survives to strip, normalization here is only whitespace collapse.

- Do not run this through `comments/normalize.py`. That normalizer's stripping
  rules are calibrated against the code-comment corpus (drop `//`/`*`
  delimiters, truncate at a line-initial `@tag`); none of that applies to
  markdown, and CLAUDE.md's own prose rules are partly *about* markdown markup
  (backtick usage, bold/italic), so the markup must survive untouched.
- **Front matter needs a real algorithm, not "strip between the first two
  `---` lines."** That naive form is unsafe: a doc that also uses `---` as an
  ordinary thematic break later on (this repo has several) would have every
  line between the front-matter delimiter and that later `---` silently
  deleted, shifting every subsequent line number with no error. Confirmed
  directly against `markdown-it-py`: leaving a front-matter block unstripped
  does *not* parse as "a thematic break plus paragraphs" as an earlier draft of
  this plan claimed -- the second `---` is consumed as a **setext heading
  underline** for the line above it (`hr` + `heading_open(h2)` + inline +
  `heading_close`), which is the actual reason it must be stripped before
  parsing, not the stated one. The real rule: treat a block as front matter
  only when it starts at byte 0 of the file, opens with a line that is exactly
  `---`, and closes at the next line that is exactly `---` or `...` -- per the
  common YAML front-matter convention -- not at an arbitrary later `---`
  found by scanning past it.
- Emit `Comment(path, line, col=1, kind="prose", raw=<source lines>, text=<content>)`.
  `kind="prose"` is a new value. `base.py`'s `Comment.kind` docstring
  (`"doc | line | block | trailing | docstring"`) needs updating to list it;
  the dataclass needs no new field. `col=1` is always correct and usually
  imprecise -- markdown-it gives no column data, only line spans, so a list
  item's real text start (after `- `) is lost. Accepted as a minor loss
  relative to code-comment extraction, which does track real columns.

## 2. Filtering

`filters.classify()` is code-comment-specific (`is_directive`, `is_license`,
`looks_like_code` all describe things that only happen in source comments) and
does not apply. Add `filters.classify_markdown(text) -> Literal["skip", "prose"]`
that only checks length against `MIN_LEN` (reusing the existing 40-char floor,
which also has the effect of skipping short headings and one-line list items --
desired, since those are not sentences to critique). No heuristic-`"code"`
outcome exists for markdown; a fenced block is already excluded at extraction.

## 3. Discovery (`commentlint/discover.py`)

`comments/__init__.py` gets `MD_EXT = {".md", ".markdown"}` and `language_of()`
dispatches those extensions to `"markdown"`. `EXTENSIONS` (the constant
`discover.walk()` filters directory entries against) stays `TSJS_EXT | PY_EXT`
by default, so an ordinary scan is unaffected.

`walk()` and `discover()` take a new `extra_extensions: frozenset[str] = frozenset()`
parameter, unioned with `EXTENSIONS` for the entry filter at `discover.py:115`.
`cli.py` passes `MD_EXT` here only when `opts.markdown` is set **and**
`opts.markdown_files` is empty (the override from Decisions). Explicitly-named
files bypass this filter already, since `discover()` adds a named file outright
before any extension check runs -- so cases (1) and (3) need no changes here,
only (2) does.

## 4. Config (`commentlint/config.py`)

Add two keys:

- `"markdown": bool` -- default `false`.
- `"markdownFiles": list` -- default `[]`. Each entry resolves relative to the
  config file's directory. **This needs actual code, not just a `KEYS` entry**:
  `config.load()` only special-cases the `"model"` key today
  (`config.py:65-66`, a single `os.path.join`); `markdownFiles` is a list, so
  resolution means mapping that join over every entry, added as its own branch
  in `load()`.

CLI mirrors: `--markdown` (store_true) and `--markdown-file PATH` (repeatable,
`append`). In `Options`, `markdown_files` unions CLI and config entries the same
way `exclude`/`ignore_path` already do (additive, not override-one-wins);
`markdown` follows the existing `pick()` boolean pattern used by
`with_node_modules`.

A path in `markdownFiles` that does not exist must be reported as a skip, not
raised. `discover()` today raises `FileNotFoundError` for any non-glob argument
that is neither a file nor a directory (`discover.py:180-181`), which is the
right behaviour for a typo'd path the user typed on argv but the wrong one for
a stale entry in a list the user is not looking at when they run the scan --
that should not abort the whole run. `run_scan` needs to check
`opts.markdown_files` entries for existence itself and route a miss into
`skipped` before handing the rest to `discover()`, rather than passing them
through and letting the exception propagate.

## 5. `cli.py` wiring

- `run_scan` builds the path list as `args.paths + opts.markdown_files` before
  calling `discover()` (after the existence check above), and passes
  `extra_extensions=MD_EXT if (opts.markdown and not opts.markdown_files) else
  frozenset()`. `--with-node-modules` combined with `--markdown` pulls in every
  vendored `README.md` under `node_modules` -- the existing gate handles it
  correctly (same extension check as anything else), but it is exactly the
  flooding scenario this plan already worries about, so it needs a line in the
  README/help text rather than silent surprise.
- **Cache-key change, not optional.** Before this feature, an explicitly-named
  `.md` file could already reach `extract_file()`, silently get zero comments
  back, and be cached that way under the current `runKey`. If `markdown`/`
  markdownFiles` is turned on later without the `runKey` changing, that stale
  "zero comments" entry would keep being served for an unchanged file and hide
  every real finding. Fold `opts.markdown` and `tuple(sorted(opts.markdown_files))`
  into the options dict already passed to `cache_mod.run_key()` alongside `cut`,
  `min_length`, `backend`, `top` -- **sorted**, since `run_key` hashes with
  `json.dumps(..., sort_keys=True)`, which sorts dict keys but not list
  contents; an unsorted list would churn the cache key across two runs with
  the same files in a different order (e.g. CLI order vs. config order).
- Findings from markdown text are tagged with a distinct `"source"`, e.g.
  `"model-markdown"` rather than `"model"`. **`report()`'s bucketing must
  change to match, or this tag silently misfires.** `cli.py:366-373` today
  splits `flat` into a `prose` bucket (`source == "model"`, sorted by score,
  shown by default) and a `code` bucket (everything else, sorted by path/line,
  shown only under `--show-code`) -- a bare `== "model"` check, so
  `"model-markdown"` falls into the `code` bucket and would be sorted by
  path/line and hidden from the default report, the opposite of what this
  section originally claimed. The predicate needs to become a membership check
  (`source in ("model", "model-markdown")`) or equivalent before markdown
  findings actually reach the score-ranked, default-shown list. **This also
  breaks `tests/test_cli.py:178`**, which already hard-asserts
  `f["source"] in ("model", "heuristic")`; that assertion needs the new value
  added alongside the bucketing fix, not just new tests appended.
- Human output prints a one-line banner above any markdown findings -- "N
  markdown findings use the code-comment model and are unvalidated for prose
  style; treat as experimental" -- so nobody mistakes them for the calibrated
  code-comment findings sitting next to them.
- **A human banner is not enough, and treating it as sufficient is the wrong
  call.** The primary consumer this tool is built for is an agent parsing
  `--json`, not a person reading the printed report -- the banner only exists
  on the human-output path (section 5 above), and `--json` today has no
  per-finding or summary field that flags reduced confidence at all. An agent
  filtering findings on `source` containing `"model"` -- a natural filter --
  would treat a markdown finding as an equal-confidence code-comment violation
  with no runtime signal that it comes from an unvalidated taxonomy. Given
  Context's own worry that Claude agents infer house style from exactly this
  kind of tool output, `--json` must carry a machine-checkable signal, not only
  the human banner: add `"experimental": true` to every markdown finding
  (mirroring how `rules.py` reads calibrated cuts from JSON specifically so
  nothing overstates confidence) and an `"experimentalFindings"` count in the
  summary block, so a caller can filter markdown findings out programmatically
  without string-matching `source`.

## 6. Known gap, not closed by this plan

The taxonomy mismatch from Context is not solved here: this plan makes markdown
prose *reach* the existing gate and rule heads, it does not make their scores
mean "violates CLAUDE.md's Prose section." Closing that gap needs its own rule
taxonomy (an epigram detector, a fragment-opener detector, and so on, mirrored
off CLAUDE.md's actual bullet list) and training data mined from real
before/after prose edits, the same way `data/rules.json` and
`data/violation_pairs.jsonl` back the code-comment rules today. That is future
work; this plan's scope ends at correct, opt-in extraction, an honest label on
the output, and a machine-checkable signal a caller can actually act on (the
`"experimental"` field above), not a banner alone.

## Verification

New `tests/test_markdown.py`:

- Paragraph, heading, list item (tight and loose), and blockquote extraction,
  each with the right line number. Assert directly what survives in `.content`
  (marker-stripped or not) against the installed `markdown-it-py` version,
  rather than assuming -- the extraction/normalization split depends on it.
- Fenced code, indented code, and raw HTML blocks produce no chunks; inline
  code spans inside a paragraph survive in the chunk's text.
- A leading YAML front-matter block is skipped rather than mis-parsed. A
  document with a real front-matter block *and* an unrelated later `---`
  thematic break must keep everything after the front matter's closing
  delimiter -- the case the naive stripper gets wrong.
- `tests/test_discover.py`: `markdownFiles` non-empty suppresses directory-walk
  pickup of other `.md` files even with `markdown: true`; a bare `.md` named on
  argv is scanned with no config at all; a `**/*.md` glob is not scanned without
  the enabler; `--markdown --with-node-modules` does pick up a `.md` file under
  `node_modules`.
- A non-existent path in `markdownFiles` is reported as a skip, and the rest of
  the scan still runs -- not a `FileNotFoundError` that aborts everything.
- `tests/test_cache.py`: toggling `markdown`/`markdownFiles` changes the cache
  run key, and reordering `markdownFiles` between two otherwise-identical runs
  does not.
- `tests/test_cli.py`: markdown findings carry `source: "model-markdown"`,
  land in the score-ranked default-shown bucket (not the `--show-code`-only
  one), and carry `"experimental": true` in `--json`; the existing
  `f["source"] in ("model", "heuristic")` assertion at `test_cli.py:178` is
  updated to include the new value rather than left to fail; the experimental
  banner prints exactly when at least one such finding exists.
- End to end: run against this repo's own CLAUDE.md and docs/ with `--markdown`,
  confirm it does not crash, does not multiply the comment count unreasonably,
  and finishes in comparable time to a small code scan; read the output by hand
  to judge whether the scores are or are not noise before anyone plans phase 2.

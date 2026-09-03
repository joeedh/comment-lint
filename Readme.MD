# Comment Lint

This little tool uses a small machine learning model to detect AI 
slop prose in your codebase.  It was motivated by regressions in 
Anthropic's Claude Opus 5 model in 2026.

## Rules & Examples

## Installing

JS-project users can `npm install -g comment-lint` (or add it as a project dependency).
The npm package is a thin wrapper that manages its own Python venv under
`~/.commentlint/pylib/`. A postinstall hook runs `--install-deps` to build it as part of
`npm install`, so failures there don't fail the install itself; if no Python interpreter
is on the machine it's built on first run instead. `--print-dep-dir` prints where the venv
lives. A commentlint found in a project's own `node_modules` is used over a global install.

From a checkout, `bin/` holds two launchers that run the linter without naming an
interpreter. `commentlint` is the sh script and `commentlint.cmd` is its counterpart for
cmd and PowerShell. Put that one directory on PATH and each shell picks up the launcher it
can run.

```
export PATH="$PATH:/path/to/commentlint/bin"        # bash
$env:PATH += ';C:\path\to\commentlint\bin'          # PowerShell, this session only
```

Create a default configuration file with commentlint --init

## The commentlint command

```
commentlint src/            lint a tree
commentlint "some comment"  score one comment
commentlint --coverage      which rules the model can name
commentlint --init          write a default .commentlintrc.json, every option explained
```

`--split-sentences` scores each sentence of a comment separately instead of scoring the
comment as a whole, so a long comment with one bad sentence is flagged on that sentence.
The report still prints the whole comment around it, with the flagged sentence bolded when
color is on and wrapped in `[>` and `<]` when it is off, as on a redirected or piped
stdout. The brackets are explained on one line before the first finding. Under `--json` the
sentence is the finding's `text` and the comment it came from is added as `comment`. The
config key is `splitSentences`.

Report a comment the model should have flagged and did not, or one it flagged but
shouldn't have. The text, and any note, revision or rule given with it, are appended to
`.commentlint-feedback.json` in the working directory; `--ledger` writes somewhere else, and
`-` as the comment reads it from stdin.

```
commentlint --false-negative "// the comment that passed" \
            --note "why it should have been flagged" \
            --revision "// how it should read instead"

commentlint --false-positive "// the comment that was wrongly flagged" \
            --rule P1 \
            --note "why the verdict was wrong"
```

Arguments and exit codes pass straight through to predict.py, so 1 still means findings and
2 a bad argument. A `.venv` inside the checkout is used without being activated. Otherwise
the launchers take the first python they find on PATH, and exit 127 if there is none.

## Config

commentlint reads `.commentlintrc.json` the way prettier reads its config: it searches
upward from the working directory and the nearest file wins, so a subdirectory can override
a repository-wide default just by holding its own copy. A single JSON object holds every
option, with the same names the CLI flags use underneath their dashes. `//` and `/* */`
comments are allowed outside string literals and are stripped before parsing:

```json
{
  "threshold": 0.6,
  "limit": 100,
  "minLength": 20,
  "exclude": ["vendor/**"],
  "ignorePath": [".gitignore"],
  "withNodeModules": false,
  "cache": true,
  "cacheStrategy": "content",
  "splitSentences": false,
  "backend": "linear",
  "model": "./model_linear",
  "markdown": false,
  "markdownFiles": ["CLAUDE.md"],
  "disableRules": ["P9"],
  "enableRules": ["C10"],
  "unicodeWhitelist": ["U+2018-U+201F"],
  "languageExtensions": {"c-style": [".c", ".h", ".cpp", ".hpp", ".java"]}
}
```

`commentlint --init` writes a `.commentlintrc.json` in the working directory with every one of
these keys present, commented out, and explained; uncomment the ones a project wants to set. It
refuses to run over an existing config rather than overwrite it.

The written file also gets an uncommented `$schema` key, pinned to the installed version, so
editors that understand JSON Schema (VS Code's built-in JSON support, for one) offer
autocomplete and hover docs while editing it. A hand-written config gets the same support by
adding `"$schema": "https://raw.githubusercontent.com/joeedh/comment-lint/v<version>/schema/commentlintrc.schema.json"`,
matched to the installed commentlint version. `.commentlintrc.jsonc` needs the file associated
as JSONC in the editor for its comments to parse alongside the schema.

An unknown key or a value of the wrong type fails the run rather than being ignored, so a
typo in the config surfaces immediately instead of silently falling back to a default. A CLI
flag always wins over the matching config key, and `--config` points at a specific file when
the nearest one found by upward search is not the one to use. `--no-config` skips the search
entirely, scanning under CLI flags and built-in defaults alone.

`disableRules` (or `--disable-rule RULE`, repeatable) is a list of rule ids -- `C10`, `P9`,
and so on -- that never get reported. An unknown id fails the run the same way an unknown
config key does. Disabling a rule only changes which rule a finding is named after: the gate
that decides whether a comment is flagged at all is a single score across every rule and is
not affected, so a comment that would only have been named for a disabled rule is now
reported clean rather than under a different rule. `C2` (commented-out code) is a heuristic
outside the model and can be disabled the same way.

`C10`, `C11`, `C13`, `P4`, `P10` and `P15` ship off by default: whether comments use `//`
versus `/* */`, how many lines a non-doc comment may run, whether a comment may hold a Unicode
character outside Latin-1, whether a sentence may open with a placeholder before a colon,
whether a sentence may use bold or italics for emphasis, and whether a sentence may fence an
interpolation with paired dashes are per-project style calls, not something the taxonomy can
settle for every codebase.
`enableRules` (or `--enable-rule RULE`, repeatable) turns one back on. A rule named in both
`disableRules` and `enableRules` stays disabled -- disabling is treated as the more specific
request. `--list-rules` marks each rule that is off in the resolved config with `(disabled)`.

`C13` (no non-Latin-1 characters in a comment) is a heuristic outside the model, like `C2`.
`unicodeWhitelist` names codepoints and ranges it lets through: `"U+2014"` for one codepoint,
`"U+2018-U+201F"` for an inclusive range, checked once `C13` is enabled.

`P14` (bracket a supporting premise) has a deterministic checker as well as its taxonomy
entry, on by default. It fires on one shape only: a copular first clause ("X is Y")
followed by a clause coordinated with `and` before a `, so` conclusion whose subject is a
bare pronoun, as in "Building the playable is the question, and it is pure, so ...". After
a copula the pronoun continues X whichever side of the copula it points at; after any
other verb it may point at the object, so the checker stays silent. The finding names the
clause. The rest of P14 has no checker, because a gloss about the first clause's object
reads identically to a correctly coordinated peer premise;
docs/research/p14-bracket-supporting-premise.md has the measurements.

`P13` (an alternative fenced with commas) and `P15` (an interpolation fenced with dashes)
have deterministic checkers too. `P13` is on by default and fires when a plain noun phrase is
split from its verb by a comma-fenced phrase opening with a coordinator such as `or`, `and`
or `rather than`: "A file that is not an image, or one carrying the mock marker, fails"
wants parentheses around the alternative. An adverbial clause between commas ("The handler,
if one is registered, runs first") is ordinary English and is not flagged. `P15` fires on
two em dashes (spaced or not) or two spaced en dashes fencing text inside one sentence;
` -- ` does not count. `P15` ships off, because the dash fence is a style call with a large
footprint (about one comment in thirty in this project's own untouched prose) that plenty of
prose uses deliberately; `enableRules: ["P15"]` or `--enable-rule P15` turns it on, and
docs/research/p13-comma-and-dash-interpolation.md has the numbers. A comment one checker
flags is reported once and not also scored by the model.

### Language families

commentlint extracts comments through three extractors: `c-style` (a state machine written for
TS/JS, reused as-is for any other `//`/`/* */` language -- its extra handling for template
literals and regex literals is JS-specific but harmless on source that has neither),
`python-style`, and `markdown`. Each family owns a default set of extensions --
`c-style`: `.ts`/`.tsx`/`.js`/`.jsx`/`.mjs`/`.cjs`/`.mts`/`.cts`, `python-style`: `.py`/`.pyi`,
`markdown`: `.md`/`.markdown` -- and `languageExtensions` adds more:

```json
{ "languageExtensions": { "c-style": [".c", ".h", ".cpp", ".hpp", ".java"] } }
```

An extension can belong to only one family; naming one already claimed by a default or by
another family in the same config fails the run. `c-style` and `python-style` additions join
directory walks unconditionally, the same as their built-in extensions; a `markdown` addition
is still gated by `--markdown`/`markdownFiles` as usual. A file named directly on the command
line is scanned by whichever family claims its extension, walk or no walk.

### Markdown

commentlint does not scan `.md`/`.markdown` files by default. `--markdown` (or `"markdown":
true` in config) opts a directory walk into them; `--markdown-file PATH` (or
`"markdownFiles"`, repeatable/list) always checks specific files regardless of the walk, and
when that list is non-empty it takes over from the walk-wide flag -- only the named files get
checked, not the whole tree. A file named directly on the command line is always scanned, with
or without either setting. `--markdown` combined with `--with-node-modules` also reaches every
vendored `README.md` under `node_modules`.

The shipped model was trained on code comments, not on prose against a style guide, so a
markdown finding is a weaker signal than a code-comment one. It is tagged `"model-markdown"`
and carries `"experimental": true` in `--json`, and a banner calls it out in the human report.

`<!-- commentlint-off -->` and `<!-- commentlint-on -->`, each on its own line, disable
scanning between them. A block whose lines touch either marker is dropped entirely, and an
unterminated `commentlint-off` disables the rest of the file. An HTML comment is the marker
because it stays literal in every CommonMark context -- a fenced block, a table cell, a
blockquote -- where a plain-text directive would either be swallowed as prose or need its own
escaping rules.

## Tasks

`task.py` is the dispatch point for working on the repository itself. `python task.py` on
its own lists what is available.

```
python task.py install     dependencies, training and type-checking extras included
python task.py check       tests and types, the gate before a commit
python task.py scan src/   lint a tree
python task.py coverage    which rules the model can name, and its calibrated cuts
python task.py clean       delete tool caches
python task.py test-npm    exercise the npm wrapper end to end against an isolated HOME
python task.py release     bump the version, tag git, publish source+model to a GitHub release
python task.py publish-npm run `npm publish` from .npm-release/, and clean it up on success
```

`check` runs every step even after one fails and exits with the worst code, so a type
error and a broken test show up in the same pass. Extra arguments reach the underlying
tool: `python task.py test -k discover` goes to pytest. Scanning follows the linter's own
exit codes, where 1 means findings and 2 means a bad argument.

See docs/scanning.md for using the linter and docs/architecture.md for how it is built.

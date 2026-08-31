"""Command line entry point.

Nothing here may import backends at module scope. A fully cached run has to
stay clear of sklearn's import, which is 2.41s on its own -- more than the rest
of the run put together -- so the model is reached for only when there is
something new to score.

Scanning ranks by score and shows the worst first rather than printing
everything over a cut. Over 6000 real comments the calibrated 0.50 cut yields
1038 findings and 0.70 yields 149; the model's ordering is good at the top and
poor in the middle, so a ranked list is honest where a flat dump is not.
"""
import argparse
import dataclasses
import json
import os
import sys
import time
from typing import Any

from . import ENCODER_DIR, LINEAR_DIR, __version__
from . import cache as cache_mod
from . import config as config_mod
from . import feedback as feedback_mod
from . import rules as rules_mod
from . import unicode_whitelist
from .comments import DEFAULT_WALK_FAMILIES, EXTENSIONS, FAMILIES, UnparseableSource, extract_file
from .comments import filters
from .comments import sentences as sentences_mod
from .comments.base import Comment
from .discover import discover

EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3
TOP_K = 3
GLOB_CHARS = set("*?[")
CODE_RULE = "C2"  # commented-out code: high-volume, hidden unless --show-code
UNICODE_RULE = "C13"  # non-Latin-1 characters in a comment


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="commentlint",
        description="Flag code comments that break the project's comment rules.",
        # a flag typo one letter short of a real one (--split-sentence for
        # --split-sentences) is otherwise accepted as an unambiguous prefix
        # match and silently changes behavior instead of erroring
        allow_abbrev=False,
    )
    p.add_argument("paths", nargs="*", help="files, directories or globs to scan")
    p.add_argument("--text", help="score this literal comment text instead of scanning")
    p.add_argument("--entire-file", help="score the whole contents of this file as one comment")
    p.add_argument("--threshold", type=float, help="gate cut (default: the model's own calibrated cut)")
    p.add_argument("--limit", type=int, help="most findings to print (default: no limit)")
    p.add_argument("--min-length", type=int, help=f"skip comments shorter than this (default {filters.MIN_LEN})")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                   help="gitignore-style pattern to skip; repeatable")
    p.add_argument("--ignore-path", action="append", default=[], metavar="FILE",
                   help="extra ignore file; repeatable")
    p.add_argument("--with-node-modules", action="store_true", help="do not skip node_modules")
    p.add_argument("--disable-rule", action="append", default=[], dest="disable_rules", metavar="RULE",
                   help="never report this rule id (e.g. C10); repeatable")
    p.add_argument("--enable-rule", action="append", default=[], dest="enable_rules", metavar="RULE",
                   help=f"report this rule id even though it is off by default "
                        f"({', '.join(sorted(rules_mod.DEFAULT_DISABLED))}); repeatable")
    p.add_argument("--markdown", action="store_true",
                   help="pick up .md/.markdown files during directory walks (combined with "
                        "--with-node-modules, this also scans vendored markdown)")
    p.add_argument("--markdown-file", action="append", default=[], dest="markdown_files", metavar="PATH",
                   help="always check this markdown file, regardless of --markdown; repeatable")
    p.add_argument("--split-sentences", action="store_true",
                   help="score each sentence of a comment or markdown chunk on its own, "
                        "instead of the comment as a whole")
    p.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    p.add_argument("--cache-location", help="where the cache lives")
    p.add_argument("--cache-strategy", choices=["metadata", "content"], help="default metadata")
    p.add_argument("--config", help="use this config file")
    p.add_argument("--no-config", action="store_true", help="ignore any .commentlintrc.json")
    p.add_argument("--init", action="store_true",
                   help=f"write a default {config_mod.CONFIG_NAME} in the current directory, "
                        f"with every option explained and commented out")
    p.add_argument("--model", help="model directory")
    p.add_argument("--backend", choices=["linear", "encoder"])
    p.add_argument("--top", type=int, default=TOP_K, help=f"rules to name per finding (default {TOP_K})")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.add_argument("--concise", action="store_true",
                   help="print the line:col / rule / score table instead of the tsc-style default")
    color = p.add_mutually_exclusive_group()
    color.add_argument("--color", action="store_true", help="force colored output even when not a tty")
    color.add_argument("--no-color", action="store_true", help="disable colored output")
    p.add_argument("--quiet", action="store_true", help="print only the summary")
    p.add_argument("--show-code", action="store_true", help="list commented-out code, not just count it")
    p.add_argument("--all", action="store_true", help="single-comment mode: every rule's probability")
    p.add_argument("--coverage", action="store_true", help="list which rules the model covers")
    p.add_argument("--list-rules", action="store_true", help="list every rule in the taxonomy and what it means")
    p.add_argument("--false-negative", metavar="COMMENT",
                   help="record a comment the model wrongly passed; - reads it from stdin")
    p.add_argument("--false-positive", metavar="COMMENT",
                   help="record a comment the model wrongly flagged; - reads it from stdin")
    p.add_argument("--note", help="with --false-negative/--false-positive: why the verdict was wrong")
    p.add_argument("--revision", help="with --false-negative: how the comment should read instead")
    p.add_argument("--rule", help="with --false-positive: which rule it was wrongly flagged for")
    p.add_argument("--ledger", help=f"where reports are appended (default ./{feedback_mod.LEDGER_NAME})")
    p.add_argument("--version", action="version", version=f"commentlint {__version__}")
    return p


class Options:
    """CLI over config, since the CLI is the more specific statement."""

    def __init__(self, args: argparse.Namespace, cfg: dict[str, Any]) -> None:
        def pick(name: str, key: str, default: Any) -> Any:
            v = getattr(args, name, None)
            if v not in (None, [], False):
                return v
            return cfg.get(key, default)

        self.threshold = pick("threshold", "threshold", None)
        self.limit = pick("limit", "limit", None)
        self.min_length = pick("min_length", "minLength", filters.MIN_LEN)
        self.exclude = list(args.exclude) + list(cfg.get("exclude", []))
        self.ignore_path = list(args.ignore_path) + list(cfg.get("ignorePath", []))
        self.with_node_modules = pick("with_node_modules", "withNodeModules", False)
        self.explicit_disable_rules = set(args.disable_rules) | set(cfg.get("disableRules", []))
        self.enable_rules = set(args.enable_rules) | set(cfg.get("enableRules", []))
        self.disable_rules = ((rules_mod.DEFAULT_DISABLED - self.enable_rules)
                               | self.explicit_disable_rules)
        self.unicode_whitelist = unicode_whitelist.parse(cfg.get("unicodeWhitelist", []))
        self.markdown = pick("markdown", "markdown", False)
        self.markdown_files = list(args.markdown_files) + list(cfg.get("markdownFiles", []))
        self.split_sentences = pick("split_sentences", "splitSentences", False)
        self.language_extensions: dict[str, list[str]] = cfg.get("languageExtensions", {})
        self.cache = False if args.no_cache else cfg.get("cache", True)
        self.cache_strategy = pick("cache_strategy", "cacheStrategy", "metadata")
        self.backend = pick("backend", "backend", None)
        # left None unless asked for, so each backend falls back to its own
        # directory rather than to whichever one is named first. The cache
        # hashes model bytes, so the fingerprint has to follow the same choice
        # or an edited encoder would be served from a linear-keyed entry.
        self.model = pick("model", "model", None)
        default_dir = ENCODER_DIR if self.backend == "encoder" else LINEAR_DIR
        self.fingerprint_dir = self.model or default_dir


def looks_like_path(arg: str, extra_extensions: frozenset[str] = frozenset()) -> bool:
    """Whether a bare positional is a path rather than literal comment text.

    A single token with no whitespace is taken as a path even when nothing is
    there, so a mistyped one reports itself instead of being scored as a
    one-word comment and reported clean. --text forces the other reading.
    """
    if os.path.exists(arg) or GLOB_CHARS & set(arg):
        return True
    if os.path.splitext(arg)[1].lower() in EXTENSIONS | extra_extensions:
        return True
    return not any(c.isspace() for c in arg)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse argv, folding a second run of bare positionals back into `paths`.

    `paths` is `nargs="*"`, and argparse only binds one contiguous run of
    positional-looking tokens to it per parse -- a token-matching limitation
    of argparse itself (https://bugs.python.org/issue14191), not something
    fixable by reordering this parser's own add_argument calls. A path that
    lands on the far side of an option that takes a value, e.g.
    `commentlint a.ts --threshold 0.7 b.ts`, is left out of `args.paths`
    entirely rather than merged in. `parse_known_args` surfaces that second
    run as leftovers, and every leftover here is either such an orphaned path
    or a genuinely unknown flag; only the latter is still an error.
    """
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    unknown = [e for e in extra if e.startswith("-") and e != "-"]
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    args.paths = args.paths + [e for e in extra if e not in unknown]
    return args


def main(argv: list[str] | None = None) -> int:
    # comments in this corpus are 25% em-dash; the Windows console default
    # codepage turns those into replacement characters
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    args = parse_args(argv)
    if args.init:
        return run_init(args)
    try:
        cfg, cfg_path = config_mod.resolve(args)
    except config_mod.ConfigError as e:
        print(f"commentlint: {e}", file=sys.stderr)
        return EXIT_USAGE
    opts = Options(args, cfg)

    unknown_rules = sorted(opts.explicit_disable_rules - rules_mod.known_ids())
    if unknown_rules:
        print(f"commentlint: unknown rule id(s) in --disable-rule: {', '.join(unknown_rules)}",
              file=sys.stderr)
        return EXIT_USAGE
    unknown_rules = sorted(opts.enable_rules - rules_mod.known_ids())
    if unknown_rules:
        print(f"commentlint: unknown rule id(s) in --enable-rule: {', '.join(unknown_rules)}",
              file=sys.stderr)
        return EXIT_USAGE

    if args.false_negative is not None and args.false_positive is not None:
        print("commentlint: use only one of --false-negative or --false-positive", file=sys.stderr)
        return EXIT_USAGE
    if args.false_negative is not None:
        return run_feedback(args, feedback_mod.FALSE_NEGATIVE, args.false_negative)
    if args.false_positive is not None:
        return run_feedback(args, feedback_mod.FALSE_POSITIVE, args.false_positive)
    if args.note or args.revision or args.rule:
        print("commentlint: --note, --revision and --rule only apply with "
              "--false-negative or --false-positive", file=sys.stderr)
        return EXIT_USAGE

    if args.list_rules:
        return run_list_rules(args, opts)

    if args.coverage:
        return run_coverage(args, opts)

    text = args.text
    if args.entire_file:
        with open(args.entire_file, encoding="utf-8", errors="replace") as f:
            text = f.read()
    walk_extra = frozenset().union(*(opts.language_extensions.get(f, []) for f in DEFAULT_WALK_FAMILIES))
    if text is None and len(args.paths) == 1 and not looks_like_path(args.paths[0], walk_extra):
        text = args.paths[0]  # back-compat: a bare string that is not a path is a comment
    if text is not None:
        return run_single(text, args, opts)

    return run_scan(args, opts)


def run_init(args: argparse.Namespace) -> int:
    target = os.path.join(os.getcwd(), config_mod.CONFIG_NAME)
    try:
        config_mod.write_default(target)
    except config_mod.ConfigError as e:
        print(f"commentlint: {e}", file=sys.stderr)
        return EXIT_USAGE
    if not args.quiet:
        print(f"wrote {_rel(target)}")
    return EXIT_CLEAN


def run_single(text: str, args: argparse.Namespace, opts: Options) -> int:
    from .backends import load

    backend, rule_desc, thresholds = load(opts.backend, opts.model)
    gate, probs = backend.score(text)
    cut: float = opts.threshold
    if opts.threshold is None:
        cut = thresholds.get(rules_mod.GATE_KEY, rules_mod.SINGLE_THRESHOLD)

    order = [i for i in sorted(range(len(probs)), key=lambda i: -probs[i])
             if backend.labels[i] not in opts.disable_rules]
    ranked = [(backend.labels[i], probs[i]) for i in (order if args.all else order[: args.top])]

    if args.as_json:
        json.dump({"text": text, "gate": gate, "cut": cut,
                   "ranked": [{"rule": r, "score": p} for r, p in ranked]}, sys.stdout, indent=1)
        print()
    else:
        if gate is None:
            print(f"{backend.name} backend has no gate; showing ranked rules only")
        elif gate >= cut:
            print(f"VIOLATION  {gate:.2f} (cut {cut:.2f})")
        else:
            print(f"clean      {gate:.2f} (cut {cut:.2f})")
        for rule_id, prob in ranked:
            print(f"  {_display_rule(rule_id):8s} {prob:.2f}  {rule_desc.get(rule_id, '')[:90]}")
    return EXIT_FINDINGS if (gate is not None and gate >= cut) else EXIT_CLEAN


def run_feedback(args: argparse.Namespace, kind: str, text: str) -> int:
    """Append one false-negative or false-positive report to the ledger.

    Reporting a miss or a wrong flag is not itself a finding, so this exits 0
    either way. A caller scripting reports can then tell a refused report from
    an accepted one by the exit code alone.
    """
    flag = "--false-negative" if kind == feedback_mod.FALSE_NEGATIVE else "--false-positive"
    if text == "-":
        # PowerShell writes a BOM at the head of a UTF-8 pipe, and it would
        # otherwise be stored as the first character of the comment
        text = sys.stdin.read().lstrip("﻿")
    if not text.strip():
        print(f"commentlint: {flag} needs the comment text", file=sys.stderr)
        return EXIT_USAGE

    path = args.ledger or feedback_mod.default_location()
    record = feedback_mod.entry(text, kind=kind, note=args.note, revision=args.revision, rule=args.rule)
    try:
        total = feedback_mod.append(path, record)
    except feedback_mod.LedgerError as e:
        print(f"commentlint: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.as_json:
        json.dump({"ledger": path, "entries": total, "recorded": record}, sys.stdout, indent=1)
        print()
    elif not args.quiet:
        label = "false negative" if kind == feedback_mod.FALSE_NEGATIVE else "false positive"
        print(f"recorded a {label} in {_rel(path)} "
              f"({total} entr{'y' if total == 1 else 'ies'})")
    return EXIT_CLEAN


def run_list_rules(args: argparse.Namespace, opts: Options) -> int:
    rules = rules_mod.all_rules()
    if args.as_json:
        out = [{**r, "disabled": r["id"] in opts.disable_rules} for r in rules]
        json.dump({"rules": out}, sys.stdout, indent=1)
        print()
        return EXIT_CLEAN
    for r in rules:
        suffix = " (disabled)" if r["id"] in opts.disable_rules else ""
        print(f"  {_display_rule(r['id']):8s} {r['name']}{suffix}")
        print(f"           {r['desc']}")
    return EXIT_CLEAN


def run_coverage(args: argparse.Namespace, opts: Options) -> int:
    path = os.path.join(opts.fingerprint_dir, "coverage.json")
    if not os.path.exists(path):
        print("no coverage.json; retrain to generate it", file=sys.stderr)
        return EXIT_USAGE
    with open(path, encoding="utf-8") as f:
        cov = json.load(f)
    rule_desc = rules_mod.descriptions()
    if args.as_json:
        json.dump(cov, sys.stdout, indent=1)
        print()
        return EXIT_CLEAN
    if "gate" in cov:
        g, a = cov["gate"], cov.get("attribution", {})
        print(f"GATE: cut {g['cut']:.2f}, AUC {g['auc']:.3f} on held-out text")
        if "scan_cut" in g:
            print(f"SCAN: cut {g['scan_cut']:.2f}, budgeted at {g['scan_max_fpr']:.0%} "
                  f"of clean comments flagged")
        if a:
            print("ATTRIBUTION: a true rule is " + ", ".join(
                f"top-{k[3:]} {v:.0%}" for k, v in sorted(a.items())) + "\n")
    print(f"RANKED ({len(cov['trained'])} rules -- these can be named as suspects):")
    for r in cov["trained"]:
        print(f"  {_display_rule(r):8s} {rule_desc.get(r, '')[:85]}")
    print(f"\nUNTRAINED ({len(cov['untrained'])} rules -- never named, too few examples):")
    for r, n in cov["untrained"].items():
        print(f"  {_display_rule(r):8s} ({n} examples) {rule_desc.get(r, '')[:75]}")
    return EXIT_CLEAN


def run_scan(args: argparse.Namespace, opts: Options) -> int:
    started = time.time()
    skipped: list[tuple[str, str]] = []

    # markdownFiles only rides along with a walk (the default root, an
    # explicit directory, or a glob): naming specific files on argv is the
    # user restricting the scan to exactly those files, and pulling in an
    # unrelated whitelist entry on top would silently widen a targeted scan
    # back out to the whole project.
    paths_are_all_files = bool(args.paths) and all(os.path.isfile(p) for p in args.paths)

    # a stale markdownFiles entry is not the user's typo on argv, so it is
    # reported as a skip rather than raised through discover() and aborting
    # the whole run
    markdown_files = []
    if not paths_are_all_files:
        for p in opts.markdown_files:
            if os.path.isfile(p):
                markdown_files.append(p)
            else:
                skipped.append((p, "no such file"))

    # custom c-style/python-style extensions join the walk unconditionally, the
    # same as their built-in defaults; custom markdown extensions are gated by
    # "markdown" the same as the built-in .md/.markdown are
    walk_extra = frozenset().union(*(opts.language_extensions.get(f, []) for f in DEFAULT_WALK_FAMILIES))
    # markdownFiles' presence overrides the directory-walk enabler for markdown
    # specifically: a repo that lists specific markdown files does not also
    # want every other .md/.markdown file in the tree opted in. The rest of
    # the tree -- non-markdown files -- is still scanned regardless.
    markdown_exts = FAMILIES["markdown"] | frozenset(opts.language_extensions.get("markdown", []))
    extra_extensions = walk_extra | (markdown_exts if (opts.markdown and not opts.markdown_files) else frozenset())

    # markdown_files are appended as extra explicit files, never substituted for
    # the scan root: an empty argv still means "walk the current directory" even
    # once markdownFiles is set, the same as it does without it.
    scan_paths = list(args.paths) if args.paths else ["."]

    try:
        files = discover(
            scan_paths + markdown_files, exclude=opts.exclude, ignore_path=opts.ignore_path,
            with_node_modules=opts.with_node_modules,
            on_skip=lambda p, why: skipped.append((p, why)),
            extra_extensions=extra_extensions,
        )
    except FileNotFoundError as e:
        print(f"commentlint: no such file or directory: {e}", file=sys.stderr)
        return EXIT_USAGE

    # read from thresholds.json, not from the backend, so the cached path can
    # resolve the cut without pulling sklearn into the import graph
    cut: float = opts.threshold
    if opts.threshold is None:
        cut = rules_mod.scan_threshold(opts.fingerprint_dir)
    cache = cache_mod.Cache(
        args.cache_location or cache_mod.default_location(),
        cache_mod.run_key(opts.fingerprint_dir, {
            "cut": cut, "min_length": opts.min_length,
            "backend": opts.backend, "top": args.top,
            "markdown": opts.markdown,
            "markdown_files": tuple(sorted(opts.markdown_files)),
            "split_sentences": opts.split_sentences,
            "language_extensions": tuple(sorted(
                (family, tuple(sorted(exts))) for family, exts in opts.language_extensions.items()
            )),
            "disable_rules": tuple(sorted(opts.disable_rules)),
            "unicode_whitelist": tuple(sorted(opts.unicode_whitelist)),
        }),
        strategy=opts.cache_strategy,
        enabled=opts.cache,
    )

    per_file: dict[str, list[cache_mod.Finding]] = {}
    counts: dict[str, int] = {}
    pending: list[tuple[str, Comment]] = []  # (path, Comment) awaiting a model score
    fresh: list[str] = []  # files scanned this run, so worth writing back

    for path in files:
        hit = cache.get(path)
        if hit is not None:
            per_file[path], counts[path] = list(hit[0]), hit[1]
            continue
        per_file[path], counts[path] = [], 0
        fresh.append(path)
        try:
            comments = extract_file(path, opts.language_extensions)
        except UnparseableSource as e:
            skipped.append((path, f"could not parse: {e}"))
            continue
        except OSError as e:
            skipped.append((path, str(e)))
            continue
        counts[path] = len(comments)
        for c in comments:
            if len(c.text) < opts.min_length:
                continue
            verdict = filters.classify_markdown(c.text) if c.kind == "prose" else filters.classify(c)
            if verdict == "skip":
                continue
            if verdict == "code":
                if CODE_RULE not in opts.disable_rules:
                    per_file[path].append(_finding(c, CODE_RULE, 1.0, [(CODE_RULE, 1.0)], "heuristic"))
                continue
            # verdict == "prose" here; C2 already claimed anything that reads as
            # code, so a unicode character inside a commented-out string literal
            # is not also reported under C13
            if UNICODE_RULE not in opts.disable_rules:
                bad = filters.disallowed_codepoints(c.text, opts.unicode_whitelist)
                if bad:
                    per_file[path].append(_finding_unicode(c, bad))
                    continue
            if opts.split_sentences:
                for sentence in sentences_mod.split(c.text):
                    if len(sentence) < opts.min_length:
                        continue
                    pending.append((path, dataclasses.replace(c, text=sentence)))
            else:
                pending.append((path, c))

    if pending:
        from .backends import load

        backend, _, _ = load(opts.backend, opts.model)
        if not backend.has_gate:
            # scanning cuts on the gate, so a gateless backend would report
            # every file clean; an all-clear nobody earned is worse than a stop
            print(f"commentlint: the {backend.name} backend has no gate head and cannot "
                  f"scan; use --text to rank rules for one comment", file=sys.stderr)
            return EXIT_USAGE
        scores = backend.score_batch([c.text for _, c in pending])
        for (path, c), (gate, probs) in zip(pending, scores):
            # Score.gate is `float | None` for a gateless backend; has_gate is
            # checked above, so it is never None on this path.
            if gate < cut:  # type: ignore[operator]
                continue
            order = [i for i in sorted(range(len(probs)), key=lambda i: -probs[i])
                     if backend.labels[i] not in opts.disable_rules][: args.top]
            if not order:
                continue
            ranked = [(backend.labels[i], probs[i]) for i in order]
            # markdown prose reaches the code-comment gate and rule heads, but
            # nobody trained them on prose, so the finding is tagged distinctly
            # and marked experimental rather than presented as an equal-confidence
            # code-comment violation
            source = "model-markdown" if c.kind == "prose" else "model"
            finding = _finding(c, ranked[0][0], gate, ranked, source)  # type: ignore[arg-type]
            if source == "model-markdown":
                finding["experimental"] = True
            if opts.split_sentences:
                finding["sentence"] = True
            per_file[path].append(finding)

    for path in fresh:
        cache.put(path, per_file.get(path, []), counts.get(path, 0))
    try:
        cache.save(seen=files)
    except OSError as e:
        print(f"commentlint: could not write cache: {e}", file=sys.stderr)

    n_comments = sum(counts.values())
    n_cached = len(files) - len(fresh)
    return report(per_file, files, args, opts, cut, skipped, n_comments, n_cached, time.time() - started)


def _finding(
    c: Comment,
    rule: str,
    score: float,
    ranked: list[tuple[str, float]],
    source: str,
) -> cache_mod.Finding:
    return {
        "line": c.line, "col": c.col, "end_line": c.end_line, "end_col": c.end_col,
        "kind": c.kind, "rule": rule,
        "score": round(float(score), 4),
        "ranked": [{"rule": r, "score": round(float(p), 4)} for r, p in ranked],
        "text": c.text, "source": source,
    }


def _finding_unicode(c: Comment, codepoints: list[int]) -> cache_mod.Finding:
    finding = _finding(c, UNICODE_RULE, 1.0, [(UNICODE_RULE, 1.0)], "heuristic")
    finding["codepoints"] = [f"U+{cp:04X}" for cp in codepoints]
    return finding


def report(
    per_file: dict[str, list[cache_mod.Finding]],
    files: list[str],
    args: argparse.Namespace,
    opts: Options,
    cut: float,
    skipped: list[tuple[str, str]],
    n_comments: int,
    n_cached: int,
    elapsed: float,
) -> int:
    flat = [(p, f) for p in files for f in per_file.get(p, [])]
    total = len(flat)

    # a heuristic's confidence and a model probability are different quantities,
    # so one ranking over both lets a heuristic finding bury the ranked prose
    # findings. C2 is also high-volume enough to hide behind --show-code on top
    # of that; other heuristic rules (e.g. C13) are shown by default instead.
    MODEL_SOURCES = ("model", "model-markdown")
    prose = sorted(
        [pf for pf in flat if pf[1]["source"] in MODEL_SOURCES],
        key=lambda pf: (-pf[1]["score"], pf[0], pf[1]["line"]),
    )
    flagged = sorted(
        [pf for pf in flat if pf[1]["source"] not in MODEL_SOURCES and pf[1]["rule"] != CODE_RULE],
        key=lambda pf: (pf[0], pf[1]["line"]),
    )
    code = sorted([pf for pf in flat if pf[1]["rule"] == CODE_RULE], key=lambda pf: (pf[0], pf[1]["line"]))
    listed = prose + flagged + code if args.show_code else prose + flagged
    shown = listed if opts.limit is None or opts.limit <= 0 else listed[: opts.limit]
    n_experimental = sum(1 for _, f in flat if f.get("experimental"))

    if args.as_json:
        by_file: dict[str, list[cache_mod.Finding]] = {}
        for p, f in flat:
            by_file.setdefault(p, []).append(f)
        json.dump({
            "version": __version__,
            "files": [{"path": p, "findings": fs} for p, fs in by_file.items()],
            "summary": {
                "filesScanned": len(files), "filesWithFindings": len(by_file),
                "findings": total, "comments": n_comments, "cachedFiles": n_cached,
                "threshold": cut, "elapsed": round(elapsed, 3),
                "skipped": [{"path": p, "reason": r} for p, r in skipped],
                "experimentalFindings": n_experimental,
            },
        }, sys.stdout, indent=1)
        print()
        return EXIT_FINDINGS if total else EXIT_CLEAN

    if n_experimental:
        print(f"{n_experimental} markdown findings use the code-comment model and are "
              f"unvalidated for prose style; treat as experimental\n")

    if not args.quiet:
        by_file = {}
        for p, f in shown:
            by_file.setdefault(p, []).append(f)
        if args.concise:
            _print_concise(by_file, rules_mod.descriptions())
        else:
            _print_ts(by_file, _use_color(args))
        if len(listed) > len(shown):
            print(f"... and {len(listed) - len(shown)} more not shown (--limit {opts.limit})\n")

    print(f"{len(files)} files, {n_comments} comments, {len(prose) + len(flagged)} findings "
          f"(cut {cut:.2f}, {n_cached} cached, {elapsed:.1f}s)")
    if code and not args.show_code:
        n_files = len({p for p, _ in code})
        print(f"plus {len(code)} commented-out code blocks (C2) in {n_files} files; --show-code lists them")
    if skipped:
        print(f"{len(skipped)} files skipped:")
        for p, why in skipped[:5]:
            print(f"  {_rel(p)}: {why}")
        if len(skipped) > 5:
            print(f"  ... and {len(skipped) - 5} more")
    return EXIT_FINDINGS if total else EXIT_CLEAN


def _enable_windows_ansi() -> bool:
    """Turn on VT100 processing for the current console.

    cmd.exe and older PowerShell hosts default this off, so an ANSI escape
    prints as literal garbage rather than a color unless the console mode is
    set first. Terminals that already understand ANSI (Windows Terminal,
    ConPTY) tolerate the call as a no-op.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except (OSError, AttributeError, ValueError):
        return False


def _use_color(args: argparse.Namespace) -> bool:
    """Whether to emit ANSI color, honoring the user's own override first.

    Absent an explicit --color/--no-color, this follows the NO_COLOR
    convention (https://no-color.org/) and otherwise only colors a real
    terminal -- a redirected or piped stdout gets plain text.
    """
    if args.no_color:
        return False
    if args.color:
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return _enable_windows_ansi()


class _Colors:
    def __init__(self, enabled: bool) -> None:
        self.reset = "\x1b[0m" if enabled else ""
        self.bold_red = "\x1b[1;31m" if enabled else ""
        self.cyan = "\x1b[36m" if enabled else ""
        self.dim = "\x1b[2m" if enabled else ""


def _concise_tag(f: cache_mod.Finding) -> str:
    """The score column's text: a heuristic's 1.0 is not a graded confidence."""
    if f["rule"] == CODE_RULE:
        return "code"
    if f["source"] == "heuristic":
        return "flag"
    return f"{f['score']:.2f}"


def _print_concise(by_file: dict[str, list[cache_mod.Finding]], rule_desc: dict[str, str]) -> None:
    if by_file:
        print("output format:")
        print(f"  {'startLine:startCol-endLine:endCol':<12} {'rule':8s} {'score':>4}  comment")
        violated_rules = sorted({f["rule"] for fs in by_file.values() for f in fs})
        print("\nViolated rules:")
        for rule in violated_rules:
            print(f"  {_display_rule(rule):8s} {rule_desc.get(rule, '')}")
        print("\nErrors:")
    for p, fs in by_file.items():
        print(_rel(p))
        for f in sorted(fs, key=lambda f: (f["line"], f["col"])):
            tag = _concise_tag(f)
            head = f["text"].split("\n")[0]
            pos = f"{f['line']}:{f['col']}"
            if f["end_line"] != f["line"]:
                pos += f"-{f['end_line']}:{f['end_col']}"
            print(f"  at {pos:<12} {_display_rule(f['rule']):8s} {tag:>4}  {head[:64]}")
        print()


def _print_ts(by_file: dict[str, list[cache_mod.Finding]], use_color: bool) -> None:
    """tsc-style output: one 'path:line:col-line2:col2 - error ruleXX: desc' per finding.

    The comment itself follows on an indented line, since the description
    names the rule but not what specifically tripped it.
    """
    rule_desc = rules_mod.descriptions()
    c = _Colors(use_color)
    for p, fs in by_file.items():
        rel = _rel(p)
        for f in sorted(fs, key=lambda f: (f["line"], f["col"])):
            pos = f"{f['line']}:{f['col']}"
            if f["end_line"] != f["line"] or f["end_col"] != f["col"]:
                pos += f"-{f['end_line']}:{f['end_col']}"
            desc = rule_desc.get(f["rule"], "")
            print(f"{c.bold_red}{rel}:{pos}{c.reset} - {c.bold_red}error{c.reset} "
                  f"{c.cyan}{_display_rule(f['rule'])}{c.reset}: {desc}")
            for line in f["text"].split("\n"):
                print(f"{c.dim}    {line}{c.reset}")
            if f.get("codepoints"):
                chars = ", ".join(f"{cp} ({chr(int(cp[2:], 16))})" for cp in f["codepoints"])
                print(f"{c.dim}    non-Latin-1: {chars}{c.reset}")
            print()


def _display_rule(rule_id: str) -> str:
    """A rule id as shown to a person: 'rule' plus the id, e.g. 'ruleP1'.

    Stored ids (thresholds.json, coverage.json, model labels, the ledger) keep
    the bare 'P1'/'C1' form; this prefix is applied only where a rule id is
    printed for a reader.
    """
    return f"rule{rule_id}"


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path).replace("\\", "/")
    except ValueError:
        return path


def entry() -> None:
    try:
        code = main()
        sys.stdout.flush()  # force the write here, where BrokenPipeError can still be caught
    except KeyboardInterrupt:
        sys.exit(EXIT_INTERNAL)
    except BrokenPipeError:
        # a downstream reader closing early (e.g. `| head`) is not a real
        # failure; redirecting stdout's fd to devnull keeps Python's own
        # atexit flush from raising the same error again on the way out
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(EXIT_INTERNAL)
    else:
        sys.exit(code)

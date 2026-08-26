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
from .comments import EXTENSIONS, UnparseableSource, extract_file
from .comments import filters
from .comments.base import Comment
from .discover import discover

EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3
TOP_K = 3
DEFAULT_LIMIT = 50
GLOB_CHARS = set("*?[")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="commentlint",
        description="Flag code comments that break the project's comment rules.",
    )
    p.add_argument("paths", nargs="*", help="files, directories or globs to scan")
    p.add_argument("--text", help="score this literal comment text instead of scanning")
    p.add_argument("--file", help="score the whole contents of this file as one comment")
    p.add_argument("--threshold", type=float, help="gate cut (default: the model's own calibrated cut)")
    p.add_argument("--limit", type=int, help=f"most findings to print (default {DEFAULT_LIMIT})")
    p.add_argument("--min-length", type=int, help=f"skip comments shorter than this (default {filters.MIN_LEN})")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                   help="gitignore-style pattern to skip; repeatable")
    p.add_argument("--ignore-path", action="append", default=[], metavar="FILE",
                   help="extra ignore file; repeatable")
    p.add_argument("--with-node-modules", action="store_true", help="do not skip node_modules")
    p.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    p.add_argument("--cache-location", help="where the cache lives")
    p.add_argument("--cache-strategy", choices=["metadata", "content"], help="default metadata")
    p.add_argument("--config", help="use this config file")
    p.add_argument("--no-config", action="store_true", help="ignore any .commentlintrc.json")
    p.add_argument("--model", help="model directory")
    p.add_argument("--backend", choices=["linear", "encoder"])
    p.add_argument("--top", type=int, default=TOP_K, help=f"rules to name per finding (default {TOP_K})")
    p.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    p.add_argument("--quiet", action="store_true", help="print only the summary")
    p.add_argument("--show-code", action="store_true", help="list commented-out code, not just count it")
    p.add_argument("--all", action="store_true", help="single-comment mode: every rule's probability")
    p.add_argument("--coverage", action="store_true", help="list which rules the model covers")
    p.add_argument("--false-negative", metavar="COMMENT",
                   help="record a comment the model wrongly passed; - reads it from stdin")
    p.add_argument("--note", help="with --false-negative: why it should have been flagged")
    p.add_argument("--revision", help="with --false-negative: how the comment should read instead")
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
        self.limit = pick("limit", "limit", DEFAULT_LIMIT)
        self.min_length = pick("min_length", "minLength", filters.MIN_LEN)
        self.exclude = list(args.exclude) + list(cfg.get("exclude", []))
        self.ignore_path = list(args.ignore_path) + list(cfg.get("ignorePath", []))
        self.with_node_modules = pick("with_node_modules", "withNodeModules", False)
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


def looks_like_path(arg: str) -> bool:
    """Whether a bare positional is a path rather than literal comment text.

    A single token with no whitespace is taken as a path even when nothing is
    there, so a mistyped one reports itself instead of being scored as a
    one-word comment and reported clean. --text forces the other reading.
    """
    if os.path.exists(arg) or GLOB_CHARS & set(arg):
        return True
    if os.path.splitext(arg)[1].lower() in EXTENSIONS:
        return True
    return not any(c.isspace() for c in arg)


def main(argv: list[str] | None = None) -> int:
    # comments in this corpus are 25% em-dash; the Windows console default
    # codepage turns those into replacement characters
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    args = build_parser().parse_args(argv)
    try:
        cfg, cfg_path = config_mod.resolve(args)
    except config_mod.ConfigError as e:
        print(f"commentlint: {e}", file=sys.stderr)
        return EXIT_USAGE
    opts = Options(args, cfg)

    if args.false_negative is not None:
        return run_false_negative(args)
    if args.note or args.revision:
        print("commentlint: --note and --revision only apply with --false-negative", file=sys.stderr)
        return EXIT_USAGE

    if args.coverage:
        return run_coverage(args, opts)

    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as f:
            text = f.read()
    if text is None and len(args.paths) == 1 and not looks_like_path(args.paths[0]):
        text = args.paths[0]  # back-compat: a bare string that is not a path is a comment
    if text is not None:
        return run_single(text, args, opts)

    return run_scan(args, opts)


def run_single(text: str, args: argparse.Namespace, opts: Options) -> int:
    from .backends import load

    backend, rule_desc, thresholds = load(opts.backend, opts.model)
    gate, probs = backend.score(text)
    cut: float = opts.threshold
    if opts.threshold is None:
        cut = thresholds.get(rules_mod.GATE_KEY, rules_mod.SINGLE_THRESHOLD)

    order = sorted(range(len(probs)), key=lambda i: -probs[i])
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
            print(f"  {rule_id:5s} {prob:.2f}  {rule_desc.get(rule_id, '')[:90]}")
    return EXIT_FINDINGS if (gate is not None and gate >= cut) else EXIT_CLEAN


def run_false_negative(args: argparse.Namespace) -> int:
    """Append one missed comment to the ledger and print where it landed.

    Reporting a miss is not a finding, so this exits 0 even though the comment
    is by assumption a violation. A caller scripting reports can then tell a
    refused report from an accepted one by the exit code alone.
    """
    text = args.false_negative
    if text == "-":
        # PowerShell writes a BOM at the head of a UTF-8 pipe, and it would
        # otherwise be stored as the first character of the comment
        text = sys.stdin.read().lstrip("﻿")
    if not text.strip():
        print("commentlint: --false-negative needs the comment text", file=sys.stderr)
        return EXIT_USAGE

    path = args.ledger or feedback_mod.default_location()
    record = feedback_mod.entry(text, note=args.note, revision=args.revision)
    try:
        total = feedback_mod.append(path, record)
    except feedback_mod.LedgerError as e:
        print(f"commentlint: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.as_json:
        json.dump({"ledger": path, "entries": total, "recorded": record}, sys.stdout, indent=1)
        print()
    elif not args.quiet:
        print(f"recorded a false negative in {_rel(path)} "
              f"({total} entr{'y' if total == 1 else 'ies'})")
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
        print(f"  {r:5s} {rule_desc.get(r, '')[:85]}")
    print(f"\nUNTRAINED ({len(cov['untrained'])} rules -- never named, too few examples):")
    for r, n in cov["untrained"].items():
        print(f"  {r:5s} ({n} examples) {rule_desc.get(r, '')[:75]}")
    return EXIT_CLEAN


def run_scan(args: argparse.Namespace, opts: Options) -> int:
    started = time.time()
    skipped: list[tuple[str, str]] = []

    try:
        files = discover(
            args.paths, exclude=opts.exclude, ignore_path=opts.ignore_path,
            with_node_modules=opts.with_node_modules,
            on_skip=lambda p, why: skipped.append((p, why)),
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
            comments = extract_file(path)
        except UnparseableSource as e:
            skipped.append((path, f"could not parse: {e}"))
            continue
        except OSError as e:
            skipped.append((path, str(e)))
            continue
        counts[path] = len(comments)
        for c in comments:
            verdict = filters.classify(c) if len(c.text) >= opts.min_length else "skip"
            if verdict == "skip":
                continue
            if verdict == "code":
                per_file[path].append(_finding(c, "C2", 1.0, [("C2", 1.0)], "heuristic"))
                continue
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
            order = sorted(range(len(probs)), key=lambda i: -probs[i])[: args.top]
            ranked = [(backend.labels[i], probs[i]) for i in order]
            per_file[path].append(_finding(c, ranked[0][0], gate, ranked, "model"))  # type: ignore[arg-type]

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
        "line": c.line, "col": c.col, "kind": c.kind, "rule": rule,
        "score": round(float(score), 4),
        "ranked": [{"rule": r, "score": round(float(p), 4)} for r, p in ranked],
        "text": c.text, "source": source,
    }


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
    # so one ranking over both lets commented-out code bury the prose findings
    prose = sorted(
        [pf for pf in flat if pf[1]["source"] == "model"],
        key=lambda pf: (-pf[1]["score"], pf[0], pf[1]["line"]),
    )
    code = sorted([pf for pf in flat if pf[1]["source"] != "model"], key=lambda pf: (pf[0], pf[1]["line"]))
    listed = prose + code if args.show_code else prose
    shown = listed if opts.limit is None or opts.limit <= 0 else listed[: opts.limit]

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
            },
        }, sys.stdout, indent=1)
        print()
        return EXIT_FINDINGS if total else EXIT_CLEAN

    if not args.quiet:
        by_file = {}
        for p, f in shown:
            by_file.setdefault(p, []).append(f)
        for p, fs in by_file.items():
            print(_rel(p))
            for f in sorted(fs, key=lambda f: (f["line"], f["col"])):
                tag = "code" if f["source"] == "heuristic" else f"{f['score']:.2f}"
                head = f["text"].split("\n")[0]
                print(f"  {f['line']:>4}:{f['col']:<3} {f['rule']:4s} {tag:>4}  {head[:64]}")
            print()
        if len(listed) > len(shown):
            print(f"... and {len(listed) - len(shown)} more not shown (--limit {opts.limit})\n")

    print(f"{len(files)} files, {n_comments} comments, {len(prose)} findings "
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


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path).replace("\\", "/")
    except ValueError:
        return path


def entry() -> None:
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_INTERNAL)

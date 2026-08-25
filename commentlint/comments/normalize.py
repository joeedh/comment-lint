"""Turn a raw comment into the text shape the model was trained on.

This is the one module that has to match the (uncommitted) miner rather than
match good taste, because a mismatch here is a distribution shift the model
feels on every comment. What the 11,480 training texts actually show:

  newlines survive (65% of texts have one) and so does internal spacing, so
  nothing here collapses whitespace; opening markers are always gone; the
  leading `*` of a continuation line is gone along with its indentation; and
  there is not one line-initial `@tag` in the corpus, so tag bodies are
  entirely out of distribution and get truncated away.

The corpus does leave a trailing `*/` on 10.9% of texts, which is a miner bug
rather than a convention. It is label-neutral -- equally common in the clean
half of a pair -- but the char n-grams still learned it as weak evidence of a
violation, worth +0.09 to +0.19 of gate score. We strip it, which is both
correct and the safe direction: live text lands slightly cleaner than training
text rather than carrying a free false positive.
"""
import re

TAG_LINE = re.compile(r"^\s*@\w")
CONT_STAR = re.compile(r"^\s*\*(?!/)\s?")


def strip_markers(raw, kind):
    """Remove the comment delimiters, leaving the prose and its line breaks."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    if kind == "python":
        lines = [re.sub(r"^\s*#+\s?", "", line) for line in text.split("\n")]
        return "\n".join(lines)

    if kind == "docstring":
        return text

    if text.startswith("//"):
        # per line: a run of `//` lines is folded into one comment upstream
        return "\n".join(re.sub(r"^\s*//+\s?", "", line) for line in text.split("\n"))

    if text.startswith("/*"):
        # closer first, and matching exactly one `*`: in the empty comment
        # `/**/` the middle star belongs to both delimiters, so a greedy `\*+/`
        # would consume it and leave the opener a stray slash to work with
        text = re.sub(r"[ \t]*\*/[ \t]*$", "", text)
        # `[ \t]` not `\s`: eating the newline after `/*` would promote the
        # first continuation line to line 0, where stars are not stripped
        text = re.sub(r"^/\*+[ \t]?", "", text)
        lines = text.split("\n")
        return "\n".join([lines[0]] + [CONT_STAR.sub("", line) for line in lines[1:]])

    return text


def truncate_at_tags(text):
    """Drop everything from the first line-initial @tag on.

    Not one of the 11,480 training texts contains one, so a @param block is
    text the model has never seen in any form.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if TAG_LINE.match(line):
            return "\n".join(lines[:i])
    return text


def normalize(raw, kind="block"):
    """Raw comment (delimiters included) to trained text shape."""
    text = strip_markers(raw, kind)
    lines = text.split("\n")
    text = "\n".join([lines[0].strip()] + [line.strip() for line in lines[1:]])
    return truncate_at_tags(text).strip()

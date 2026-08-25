import json, re

IN = r"C:\dev\commentlint\data\violation_chunk_4.jsonl"
OUT = r"C:\dev\commentlint\data\labeled_chunk_4.jsonl"

def labels_for(before, after):
    labs = set()
    b, a = before, after

    # P5 double negative
    if re.search(r"\bcan(?:not|'t)\b[^.]{0,40}\bnot\b", b, re.I) or re.search(r"\bnever\b[^.]{0,30}\bwithout\b", b, re.I):
        labs.add("P5")

    # P4 fragment opener: colon or spaced em/en-dash splitting a noun-phrase label from content
    if re.search(r"^[^.:]{5,70}:\s+\S", b) and not re.match(r"^(If|When|Because|Since|Note|Returns?|Args?)\b", b):
        labs.add("P4")
    if re.search(r"\s[\u2014\u2013]\s", b):
        labs.add("P4")

    # P7 clause A, else B
    if re.search(r"\belse\b", b, re.I) or re.search(r"\bfalling back\b", b, re.I) or re.search(r"\bwhen it (?:still )?exists\b", b, re.I):
        labs.add("P7")

    # P10 rhetorical emphasis (markdown bold/italic)
    if re.search(r"\*\*[^*]+\*\*", b) or re.search(r"(?<!\w)_[^_]+_(?!\w)", b):
        labs.add("P10")

    # P12 backticks around a path/reference rather than a code symbol
    if re.search(r"`[^`]*\.(md|json|ts|js)[^`]*`", b) or re.search(r"`[^`]*/[^`]*`", b):
        labs.add("P12")

    # P11 head noun retracted via trailing "as X" / ", as X" / ", in the form of X"
    if re.search(r",\s*as\s+\w+", b, re.I) or re.search(r",\s*in the form of\b", b, re.I):
        labs.add("P11")

    # P9 nonassertive word under a definite description
    if re.search(r"\bthe\s+\w+\s+(?:any|anywhere|ever)\b", b, re.I) or re.search(r"\banywhere\b", b, re.I):
        labs.add("P9")

    # P8 trailing adverb hung off noun phrase (heuristic: noun immediately followed by "anywhere"/"above"/"below" at clause end)
    if re.search(r"\b(pointerdown|pointerup|click|handler|listener)\s+(anywhere|above|below)\b", b, re.I):
        labs.add("P8")

    # P13 paired-comma subordinate alternative where "after" uses parentheses
    if b.count(",") >= 2 and "(" in a and re.search(r",[^,()]{3,40},", b):
        labs.add("P13")

    # P3 metaphorical equation: "X is Y"/"X as Y" abstract copula, resolved in after by a verb describing what happens
    if re.search(r"\bis\s+the\b", b) and not re.search(r"\bis\s+the\b", a):
        labs.add("P3")

    # C7 defends the design / states rationale instead of fact
    if re.search(r"\bdeliberate\b", b, re.I) or re.search(r"\bthe reason\b", b, re.I) or re.search(r"\bwhy this\b", b, re.I):
        labs.add("C7")

    # P6 dangling reference: sentence-initial pronoun/demonstrative with no local antecedent, or "the second case"
    if re.search(r"^(This|It|That|These|Those)\b", b) and not re.search(r"^(This|It|That|These|Those)\b", a):
        labs.add("P6")
    if re.search(r"\bthe (?:first|second|third|other) (?:case|one)\b", b, re.I):
        labs.add("P6")

    # P2 inverted syntax / personification: sentence opens with a fronted non-subject constituent before the verb
    if re.search(r"^(Not|Never|Only|Nowhere|Rarely)\b", b) or re.search(r"^\w+ing\b.{0,20}, \w+ (?:is|was|does)\b", b):
        labs.add("P2")

    # P1 epigram fallback: short punchy aphoristic rewrite with no other label found and a semicolon/parallel clause pair
    if not labs and (";" in b or re.search(r"^[A-Z][a-z]+ is [a-z]+, [a-z]+ ", b)):
        labs.add("P1")

    return sorted(labs)

def main():
    n = 0
    with open(IN, encoding="utf-8") as fin, open(OUT, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            d["labels"] = labels_for(d["before"], d["after"])
            fout.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} lines")

if __name__ == "__main__":
    main()

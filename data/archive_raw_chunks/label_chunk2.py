import json, re

RULES_ORDER = ["P4","P7","P13","P10","P5","P6","P9","P8","P11","P3","P2","C8","C7","P12","P1"]

def labels_for(before, after):
    labels = []
    b, a = before, after

    # P10: rhetorical bold/italic markup removed
    if re.search(r"\*\*[^*]+\*\*|\*[^*\s][^*]*\*", b) and not re.search(r"\*\*[^*]+\*\*|\*[^*\s][^*]*\*", a):
        labels.append("P10")

    # P5: double negative
    if re.search(r"\b(cannot|can't|not)\b.{0,25}\bnot\b", b, re.I):
        labels.append("P5")

    # P4: fragment opener - "Noun phrase: rest" or "Noun phrase — rest" at sentence start,
    # where the colon/dash defers the real subject, fixed by leading with a full sentence.
    if re.match(r"^[A-Z][^.:\u2014]{3,60}[:\u2014]", b) and not re.match(r"^[A-Z][^.:\u2014]{3,60}[:\u2014]", a):
        labels.append("P4")

    # P7: "Clause A, else B" / "X, or Y" resolved into separate sentences (colon + "else"/"or" gone)
    if re.search(r":\s.*\belse\b", b, re.I) and "else" not in a.lower():
        labels.append("P7")

    # P13: paired em-dashes or paired commas as parenthetical, replaced by real parens/plain prose
    if b.count("\u2014") >= 2 and a.count("\u2014") < b.count("\u2014") and "(" in a:
        labels.append("P13")
    elif b.count("\u2014") >= 2 and "(" in a and "\u2014" not in a:
        labels.append("P13")

    # P6: dangling pronoun/reference ("it", "this", "that", "the other") resolved to a named noun
    if re.search(r"\b(it|this|that)\b", b, re.I):
        # crude signal: after is longer and repeats a concrete noun where before had a bare pronoun
        if len(a) > len(b) * 0.95 and re.search(r"\b(it|this|that)\b", a, re.I) is None:
            labels.append("P6")

    # P9: "any"/"anywhere"/"ever" beside a definite description
    if re.search(r"\b(any|anywhere|ever)\b", b, re.I) and not re.search(r"\b(any|anywhere|ever)\b", a, re.I):
        labels.append("P9")

    # P8: adverb hung off end of noun phrase (heuristic: "-ing anywhere/again/afterwards" fixed)
    if re.search(r"\b\w+ing\s+(anywhere|again|afterwards|already)\b", b, re.I):
        labels.append("P8")

    # P11: head noun corrected - "X as Y" / "X, as Y" pattern removed, or "Commands for X" restructuring
    if re.search(r"\bas (commands|a description|a report)\b", b, re.I) and not re.search(r"\bas (commands|a description|a report)\b", a, re.I):
        labels.append("P11")

    # P3: metaphorical equation "X is Y" / "X, and Y" collapsing an equation, or "is the whole point/reason/rule"
    if re.search(r"\bis (the (whole|only|one) (point|reason|rule|question|thing|feature))\b", b, re.I):
        labels.append("P3")
    if re.search(r"\b(is|are) not\b.{0,20}\bbut\b", b, re.I):
        labels.append("P3")

    # P2: inverted syntax / personification - sentence opens with a gerund/participle fragment describing an abstract subject
    if re.match(r"^(Split out|Named,|Counted from|Deliberately|Kept in)\b", b):
        labels.append("P2")

    # C8: doc comment restates subject with "It " opener where after drops the pronoun for a verb-first predicate
    if re.match(r"^It \w+", b) and re.match(r"^[A-Z]\w+s\b", a):
        labels.append("C8")

    # C7: defends the design ("deliberately", "on purpose", "the reason X exists") vs after stating the fact plainly
    if re.search(r"\bdeliberately\b|\bon purpose\b", b, re.I) and re.search(r"\bdeliberately\b|\bon purpose\b", a, re.I):
        labels.append("C7")

    # P12: backticks around a plain English word (not an identifier-looking token) removed
    stray_before = re.findall(r"`([a-zA-Z][a-zA-Z ]{2,20})`", b)
    stray_after = re.findall(r"`([a-zA-Z][a-zA-Z ]{2,20})`", a)
    if stray_before and len(stray_before) > len(stray_after):
        labels.append("P12")

    if not labels:
        labels.append("P1")

    # de-dup, keep canonical order
    seen = []
    for r in RULES_ORDER:
        if r in labels and r not in seen:
            seen.append(r)
    return seen

def main():
    inp = r"C:\dev\commentlint\data\violation_chunk_2.jsonl"
    outp = r"C:\dev\commentlint\data\labeled_chunk_2.jsonl"
    n = 0
    with open(inp, encoding="utf-8") as f, open(outp, "w", encoding="utf-8") as out:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            d["labels"] = labels_for(d["before"], d["after"])
            out.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} labeled lines")

if __name__ == "__main__":
    main()

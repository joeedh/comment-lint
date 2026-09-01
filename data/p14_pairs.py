"""P14 (bracket-supporting-premise) training pairs, written by hand.

The silver labeler cannot reach P14: the ", and <clause>, so" chain shape occurs
in 37 pairs of violation_pairs.jsonl, but only five of those revisions are about
the coordinated premise, so every surface signature scores mostly false
positives. See the note in label_heuristics.py.

Two provenances, both carrying the same fix direction:

  natural   Real before-text that breaks P14. The `after` is written here, and
            changes only the coordination -- every other feature of the comment
            is left as the author had it, so the pair isolates the rule. Four
            come from violation_pairs.jsonl (two of them from a revision's
            `after`, where the chain survived the rewrite untouched) and one is
            the pane/popup revision the rule was proposed from.

  derived   Real after-text whose premise the author already bracketed or
            relativized. The `before` is written here by de-bracketing it into
            the coordinated chain. The fix is attested prose; only the defect is
            reconstructed, which is the direction that matters, because the head
            has to learn what the repaired form looks like.

These pairs are deliberately NOT merged into labeled_all_v2.jsonl. Merging them
clears MIN_SUPPORT and gives P14 a head, but the head is noise. Measured over 12
reseeded splits of the linear model, pooling 33 held-out P14 positives:

  P14 ranked in the top 3 for a true P14 comment   0%   (median rank 10 of 17)
  the gate called a P14 comment bad at all         6/33
  P14 ranked top-1 on a comment that is not P14    78 of 13575

The attribution failure is not specific to P14 -- P13 ships today with 21
positives and also ranks its own comments 0% at top-1, median rank 10. What
separates P14 is the gate: 6 of 33 against P13's 15 of 30. A P14 before-text
differs from its after by a conjunction and a bracket, and is otherwise clean
prose, so tf-idf over word and char n-grams cannot see the defect at all.

Shipping it anyway would put P14 in coverage.json's `trained` list and advertise
a rule the model cannot name. What the head needs is either features that reach
clause structure, or an order of magnitude more positives than hand-authoring
can supply.

Run `python data/p14_pairs.py` to write data/p14_pairs.jsonl.
"""
import json
import os

# (file, commit, before, after)
NATURAL = [
    (
        "apps/desktop/renderer/pathux/panes.ts",
        "working-tree",
        """This pane is a floating popup window rather than a tile in the mesh.

It is on screen and shows an editor, so {@link paneShowing} finds it: asking for the
Tasks editor while a Tasks popup is up returns that popup. Everything else here is about
arranging the mesh, and a popup is not part of the mesh, so splitting one, collapsing one,
or covering one with a different editor are all things the author never asked for.""",
        """This pane is a floating popup window rather than a tile in the mesh.

It is on screen and shows an editor, so {@link paneShowing} finds it: asking for the
Tasks editor while a Tasks popup is up returns that popup. Everything else here is about
arranging the mesh (which the popup is not part of), so splitting one, collapsing one,
or covering one with a different editor are all things the author never asked for.""",
    ),
    (
        "apps/desktop/renderer/pathux/bridge.ts",
        "8d5b59bf",
        """Both go through main. A renderer-side `window.close()` would close only the window that asked
and leave the others up; main closes them all, and each still runs its own
`will-prevent-unload`, so an unsaved draft in each window is still asked about.""",
        """Both go through main. A renderer-side `window.close()` would close only the window that asked
and leave the others up; main closes them all (each still running its own
`will-prevent-unload`), so an unsaved draft in each window is still asked about.""",
    ),
    (
        "apps/desktop/renderer/pathux/closepane.ts",
        "8d5b59bf",
        """This app has two rules about that — the header is not a pane, and the last pane is kept —
and they live in `panes.ts`, so the pick has to be made against them.""",
        """This app has two rules about that — the header is not a pane, and the last pane is kept —
which live in `panes.ts`, so the pick has to be made against them.""",
    ),
    (
        "apps/desktop/renderer/pathux/editors/branch.ts",
        "8d5b59bf",
        """A press that never travelled is a click, and a click is a selection: the scene it opens
is the shared one, so the coverage strip and the script column follow it.""",
        """A press that never travelled is a click, which is a selection: the scene it opens
is the shared one, so the coverage strip and the script column follow it.""",
    ),
    (
        "apps/desktop/src/main/commands/tests/autorun.test.ts",
        "8d5b59bf",
        """When a requeue runs the pipeline by itself. The decision is the whole feature, and the act it
guards spends a real image call, so it is pinned here rather than left to a live run.""",
        """When a requeue runs the pipeline by itself. The decision is the whole feature (the act it
guards spends a real image call), so it is pinned here rather than left to a live run.""",
    ),
]

DERIVED = [
    (
        "apps/desktop/renderer/pathux/editors/project.ts",
        "8d5b59bf",
        """`project.yaml`, as the run reads it. A singleton pane with no subject, and a workspace has one
config, so it is deliberately absent from `SUBJECT_OF` and `view.open(editor=project)` carries
nothing.""",
        """`project.yaml`, as the run reads it. A singleton pane with no subject (a workspace has one
config), so it is deliberately absent from `SUBJECT_OF` and `view.open(editor=project)` carries
nothing.""",
    ),
    (
        "apps/desktop/renderer/pathux/reportpreview.ts",
        "8d5b59bf",
        """Stay open either way. Nothing has been posted yet, and the browser holds a form, so closing on
success would take away the only copy of the text while the author is still reading it over.
The author closes the dialog with the Close button instead""",
        """Stay open either way. Nothing has been posted yet (the browser holds a form), so closing on
success would take away the only copy of the text while the author is still reading it over.
The author closes the dialog with the Close button instead""",
    ),
    (
        "apps/desktop/renderer/pathux/route.ts",
        "8d5b59bf",
        """Which selection field an editor's subject comes from. A path and a hash are not interchangeable,
and pointing `docPath` at a `.png` would have the wiki editor `doc.read` a binary, so an editor
with no entry here has no subject, and the field it does not name is left alone.""",
        """Which selection field an editor's subject comes from. A path and a hash are not interchangeable
(pointing `docPath` at a `.png` would have the wiki editor `doc.read` a binary), so an editor
with no entry here has no subject, and the field it does not name is left alone.""",
    ),
    (
        "apps/desktop/renderer/pathux/selection.ts",
        "8d5b59bf",
        """The generated asset, by hash. A task produces one but does not name one, and an asset's hash is
its bytes rather than its recipe, so like `docPath` it is carried through untouched here.""",
        """The generated asset, by hash. A task produces one but does not name one (an asset's hash is
its bytes, not its recipe), so like `docPath` it is carried through untouched here.""",
    ),
    (
        "apps/desktop/renderer/rules/timeline/editing.ts",
        "8d5b59bf",
        """Why a handle does not move while an editor is open. No command was invoked here, so no command
supplied this sentence. The handle cannot take focus away from the editor, and its `pointerdown`
is prevented so there is no blur and no commit, so without this notice the click reads as a
broken drag.""",
        """Why a handle does not move while an editor is open. No command was invoked here, so no command
supplied this sentence. The handle cannot take focus away from the editor (its `pointerdown` is
prevented, so there is no blur and no commit), so without this notice the click reads as a
broken drag.""",
    ),
    (
        "apps/desktop/renderer/rules/script.ts",
        "6a05af36",
        """leave the head empty, and `splitScene` refuses that, so offering it would only ever produce a
refusal.""",
        """leave the head empty, which `splitScene` refuses, so offering it would only ever produce a
refusal.""",
    ),
    (
        "apps/desktop/renderer/pathux/editors/branch.ts",
        "8d5b59bf",
        """All three drags read their verdict from `pathux/branch.ts`, and it asks the same `branchops`
the command will run, so the refusal shown mid-drag is the refusal the commit would give.""",
        """All three drags read their verdict from `pathux/branch.ts`, which asks the same `branchops`
the command will run, so the refusal shown mid-drag is the refusal the commit would give.""",
    ),
    (
        "apps/desktop/renderer/pathux/editors/documents.ts",
        "8d5b59bf",
        """It holds no selection of its own. A click publishes `ui.sceneId` / `ui.shotId` /
`ui.characterId` / `ui.docPath`, and every other editor already observes those, so the tree
steers the app without knowing what is open, and a scene picked in the branch graph highlights
here.""",
        """It holds no selection of its own. A click publishes `ui.sceneId` / `ui.shotId` /
`ui.characterId` / `ui.docPath`, which every other editor already observes, so the tree steers
the app without knowing what is open, and a scene picked in the branch graph highlights here.""",
    ),
    (
        "apps/desktop/renderer/pathux/editors/header.ts",
        "8d5b59bf",
        """Every editor an author browses to, each entry a `view.open`. This replaced the room nav. The
list is `shared/editors.ts`, and the command's props are built from it too, so the menu cannot
offer something the command would refuse.""",
        """Every editor an author browses to, each entry a `view.open`. This replaced the room nav. The
list is `shared/editors.ts`, which is also what the command's props are built from, so the
menu cannot offer something the command would refuse.""",
    ),
    (
        "apps/desktop/renderer/pathux/layouts.ts",
        "8d5b59bf",
        """window shows the mesh the session remembered, and the author regards that as the template, so
re-applying it here would throw away a border they dragged last session.""",
        """window shows the mesh the session remembered, which the author regards as the template, so
re-applying it here would throw away a border they dragged last session.""",
    ),
    (
        "apps/desktop/renderer/rules/assetview.ts",
        "8d5b59bf",
        """A portrait is approved through the gate and nothing else. `gate.approve` also writes
`character.md` and `approved.png`, and that is what clears the character, so the pane offers
that command rather than the generic `asset.accept` the command itself would refuse.""",
        """A portrait is approved through the gate and nothing else. `gate.approve` also writes
`character.md` and `approved.png`, which is what clears the character, so the pane offers that
command rather than the generic `asset.accept` the command itself would refuse.""",
    ),
    (
        "apps/desktop/src/main/commands/art.ts",
        "8d5b59bf",
        """Writes a sheet, a manifest row and a `done` task record across two trees, and no document
snapshot covers them, so it is committed like any other act but never undone""",
        """Writes a sheet, a manifest row and a `done` task record across two trees, which no document
snapshot covers, so it is committed like any other act but never undone""",
    ),
    (
        "apps/desktop/src/main/layouts.ts",
        "8d5b59bf",
        """Put the shipped layouts back. The `all` scope additionally deletes the author's own layouts,
and "reset" alone does not promise that, so the scope is a named value rather than a boolean
flag.""",
        """Put the shipped layouts back. The `all` scope additionally deletes the author's own layouts,
which "reset" alone does not promise, so the scope is a named value rather than a boolean flag.""",
    ),
    (
        "apps/desktop/src/main/windows.ts",
        "8d5b59bf",
        """move, resize and close. A quit closes every window in a cascade, and that would otherwise
rewrite the list down to nothing and lose the whole arrangement, so `freeze()` at `before-quit`
snapshots the open set and stops writing for the rest of the process.""",
        """move, resize and close. A quit closes every window in a cascade, which would otherwise rewrite
the list down to nothing and lose the whole arrangement, so `freeze()` at `before-quit`
snapshots the open set and stops writing for the rest of the process.""",
    ),
    (
        "packages/artgen/src/prompts.ts",
        "8d5b59bf",
        """Only the shot's own notes. A character's notes and a location's already reach this frame
through the sheets and plates it references, and those were generated with them, so repeating
them here would state them twice""",
        """Only the shot's own notes. A character's notes and a location's already reach this frame
through the sheets and plates it references, which were generated with them, so repeating
them here would state them twice""",
    ),
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p14_pairs.jsonl")


def rows():
    for origin, group in (("authored-p14", NATURAL), ("derived-p14", DERIVED)):
        for path, commit, before, after in group:
            yield {
                "repo": "visualnovel",
                "commit": commit,
                "file": path,
                "before": before,
                "after": after,
                "labels": ["P14"],
                "labels_agreed": ["P14"],
                "agreement": "full",
                "source": origin,
            }


def main():
    out = list(rows())
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} pairs to {OUT}")


if __name__ == "__main__":
    main()

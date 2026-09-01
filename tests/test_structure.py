"""The clause-structure features are experimental and off by default, but they
live in the shipped package, so the shapes they claim to separate are pinned."""
from commentlint import structure

DEFECT = "Everything else here is about arranging the mesh, and a popup is not part of the mesh, so splitting one is wrong."
REPAIR = "Everything else here is about arranging the mesh (which the popup is not part of), so splitting one is wrong."


def test_coordinated_premise_and_its_repair_differ():
    assert "c2:AND>SO" in structure.tokens(DEFECT)
    assert "c2:AND>SO" not in structure.tokens(REPAIR)
    assert "c3:LPAREN>RPAREN>SO" in structure.tokens(REPAIR)


def test_relative_clause_premise_is_its_own_shape():
    tokens = structure.tokens("leave the head empty, which splitScene refuses, so offering it produces a refusal.")
    assert "c2:WHICH>SO" in tokens
    assert "premise:WHICH" in tokens


def test_backref_counts_content_overlap_with_the_clause_before():
    assert "AND:bref:1" in structure.tokens(DEFECT)
    none = "The lock is taken late, and the picker can appear, so an author may pick a taken repo."
    assert "AND:bref:0" in structure.tokens(none)


def test_a_comment_with_no_connective_yields_nothing():
    assert structure.tokens("Hand a URL to the OS.") == []

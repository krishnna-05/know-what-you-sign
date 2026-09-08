"""Unfair-clause rules for consumer terms of service.

The baseline the trained model must beat, and the fallback when no model is
present. Each test pins a distinction the rules had to learn the hard way.
"""

from __future__ import annotations

from kwys.classify.unfair_rules import labels, predict, score_clause


def test_consumer_right_is_not_unfairness():
    """Regression: "you may cancel at any time" was read as a unilateral
    termination clause. It shares every keyword with one — and means the
    opposite. A tool that flags the user's own rights as risks is worse than
    useless to them."""
    assert predict("you may cancel your booking at any time by contacting us") == []


def test_modal_separated_from_its_verb():
    """Regression: "may, in its absolute discretion, immediately terminate"
    matched nothing, because the pattern required the verb to follow the modal
    directly. Real terms of service almost never write it that way."""
    text = (
        "skyscanner may in its absolute discretion immediately terminate any "
        "agreement with you under these terms at any time upon notice to you"
    )
    assert "Unilateral termination" in predict(text)


def test_multi_label_by_construction():
    """A venue clause is routinely both a jurisdiction and a choice-of-law
    clause. Forcing a single label would lose one of them."""
    got = predict(
        "these terms shall be governed by and construed in accordance with the "
        "laws of england and the courts of england shall have exclusive jurisdiction"
    )
    assert {"Choice of law", "Jurisdiction"} <= set(got)


def test_limitation_of_liability():
    assert "Limitation of liability" in predict(
        "to the maximum extent permitted by law , we do not accept any liability "
        "for any loss or damage arising from your use of the service"
    )


def test_arbitration_and_class_action_waiver():
    assert "Arbitration" in predict(
        "any dispute shall be resolved by binding arbitration and you waive any "
        "right to a jury trial or to participate in a class action"
    )


def test_ordinary_clause_stays_quiet():
    """A report that flags everything has told the user nothing."""
    assert predict("we will send you a confirmation email after each booking") == []


def test_scores_are_inspectable():
    """Every flag must be explainable: the caller can see what fired and by how
    much, which is what makes a rule baseline defensible at all."""
    scores = score_clause("we reserve the right to modify these terms at any time")
    assert scores and all(isinstance(v, float) for v in scores.values())


def test_label_set_matches_the_benchmark():
    """Eight categories, as annotated in LexGLUE unfair_tos. Drifting from the
    published label set would make the evaluation incomparable."""
    assert len(labels()) == 8

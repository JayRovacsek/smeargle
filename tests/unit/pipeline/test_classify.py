from fakes.clients import FakeJevClient

from smeargle.domain.jev import JevAnswer, JevResult
from smeargle.domain.mapping import Relationship
from smeargle.pipeline import classify


def _choice(label, confidence=0.9):
    return JevResult(answers=(JevAnswer("q", label, confidence, 0.1),))


def test_classifies_positive_relationship_and_confidence():
    jev = FakeJevClient(responses=[_choice("subset-of", 0.85)])
    outcome = classify.classify_pair(jev, "MUST x", "control")
    assert outcome.classify_status == "done"
    assert outcome.relation is Relationship.SUBSET_OF
    assert outcome.confidence_percentage == 0.85
    assert classify.category_for(0.85, high=0.8, medium=0.5) == "high"


def test_no_relationship_is_unmapped():
    jev = FakeJevClient(responses=[_choice("no-relationship", 0.9)])
    outcome = classify.classify_pair(jev, "MUST x", "control")
    assert outcome.classify_status == "unmapped"
    assert outcome.relation is None


def test_unknown_relation_string_is_unmapped_not_coerced():
    jev = FakeJevClient(responses=[_choice("kinda-related", 0.9)])
    outcome = classify.classify_pair(jev, "MUST x", "control")
    assert outcome.classify_status == "unmapped"
    assert outcome.relation is None


def test_min_confidence_suppression_is_skipped_and_category_cutoffs():
    jev = FakeJevClient(responses=[_choice("equal-to", 0.4)])
    outcome = classify.classify_pair(jev, "MUST x", "control", min_confidence=0.5)
    assert outcome.classify_status == "skipped"
    assert outcome.low_confidence is True
    assert classify.category_for(0.5, high=0.8, medium=0.5) == "medium"
    assert classify.category_for(0.49, high=0.8, medium=0.5) == "low"

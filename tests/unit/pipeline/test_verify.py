from fakes.clients import FakeJevClient

from smeargle.domain.jev import JevAnswer, JevResult
from smeargle.pipeline import verify


def _noul(probability):
    return JevResult(answers=(JevAnswer("q", "yes", probability),))


def test_passes_at_or_above_mapped_threshold():
    jev = FakeJevClient(responses=[_noul(0.5)])
    outcome = verify.verify_pair(jev, "MUST x", "control text", threshold=0.5)
    assert outcome.verify_status == "passed"
    assert outcome.noul_prob == 0.5
    assert outcome.low_confidence is False


def test_rejects_below_mapped_threshold():
    jev = FakeJevClient(responses=[_noul(0.49)])
    outcome = verify.verify_pair(jev, "MUST x", "control text", threshold=0.5)
    assert outcome.verify_status == "rejected"
    assert outcome.noul_prob == 0.49


def test_min_confidence_suppresses_even_above_mapped_threshold():
    jev = FakeJevClient(responses=[_noul(0.98)])
    outcome = verify.verify_pair(
        jev, "MUST x", "control text", threshold=0.5, min_confidence=0.99
    )
    assert outcome.verify_status == "rejected"
    assert outcome.low_confidence is True

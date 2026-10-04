from smeargle.domain.requirements import Keyword, Requirement
from smeargle.domain.run import Ledger


def test_ledger_is_frozen_hashable_and_defaults():
    requirement = Requirement(
        "run-1", "req-1", "doc-1", 0, "The system MUST log.", "The system MUST log.",
        Keyword.MUST, "proposed", "passed", 0.9, "MUST", "nominated",
    )
    ledger = Ledger(
        run_id="run-1", documents=({"doc_id": "doc-1"},), requirements=(requirement,),
        catalogs=(), controls=(), pairs=(), mappings=(), evidence=(),
        domains={"c-1": "access"}, failures=(), run={"run_id": "run-1"},
    )
    assert ledger.run_id == "run-1"
    assert ledger.requirements[0].keyword is Keyword.MUST
    assert hash(ledger) == hash(ledger)
    assert ledger.failures == ()

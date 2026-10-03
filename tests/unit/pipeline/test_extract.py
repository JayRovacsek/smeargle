from fakes.clients import FakeJevClient, FakeLLMClient

from smeargle.clients.ports import CallMeta
from smeargle.domain.jev import JevAnswer, JevResult
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.pipeline import extract


def _requirement(text: str) -> Requirement:
    return Requirement(
        run_id="run-1", req_id="req-1", doc_id="doc-1", ordinal=0,
        text=text, normalized_text=extract.normalise_text(text), keyword=Keyword.MUST,
        extract_status="proposed", gate_status=None, gate_noul_prob=None,
        gate_choice=None, retrieve_status=None,
    )


def _noul(probability: float) -> JevResult:
    return JevResult(answers=(JevAnswer("q", "yes", probability),))


def _choice(label: str, confidence: float = 0.9) -> JevResult:
    return JevResult(answers=(JevAnswer("q", label, confidence, 0.1),))


def test_normalise_text_nfkc_newlines_and_whitespace():
    assert extract.normalise_text("a\r\n b\t\t c\r") == "a b c"
    assert extract.normalise_text("\u00a0MUST\u00a0 x") == "MUST x"


def test_chunk_text_is_deterministic_and_overlaps():
    text = "0123456789"
    chunks = extract.chunk_text(text, chunk_size=6, overlap=2)
    assert chunks == ["012345", "456789"]
    assert extract.chunk_text("short", chunk_size=100, overlap=10) == ["short"]


def test_propose_chunk_renders_untrusted_and_returns_candidates():
    llm = FakeLLMClient(default={"requirements": [{"text": "MUST a", "keyword": "must"}]})
    candidates = extract.propose_chunk(llm, "MUST a", meta=None)
    assert candidates[0][0] == "MUST a"
    assert candidates[0][1] is Keyword.MUST
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "<<<UNTRUSTED-DOCUMENT-DATA>>>" in prompt


def test_gate_passes_and_confirms_choice_keyword():
    jev = FakeJevClient(responses=[_noul(0.9), _choice("SHOULD")])
    meta = CallMeta(stage="extract", item_ref="gate:req-1", call_type="jev_gate")
    outcome = extract.gate_requirement(
        jev, _requirement("The system MUST x"), threshold=0.5, min_confidence=None, meta=meta
    )
    assert outcome.gate_status == "passed"
    assert outcome.keyword is Keyword.SHOULD
    assert outcome.gate_choice == "SHOULD"
    assert outcome.gate_noul_prob == 0.9
    assert len(jev.calls) == 2
    assert jev.calls[0]["meta"].call_type == "jev_gate_noul"
    assert jev.calls[1]["meta"].call_type == "jev_gate_choice"


def test_gate_rejects_below_authenticity_threshold_without_choice_call():
    jev = FakeJevClient(responses=[_noul(0.2)])
    outcome = extract.gate_requirement(
        jev, _requirement("maybe x"), threshold=0.5, min_confidence=None
    )
    assert outcome.gate_status == "rejected"
    assert outcome.keyword is None
    assert outcome.gate_noul_prob == 0.2
    assert len(jev.calls) == 1


def test_gate_rejects_unparseable_choice_and_low_confidence():
    jev = FakeJevClient(responses=[_noul(0.9), _choice("MAY")])
    unparseable = extract.gate_requirement(
        jev, _requirement("MAY x"), threshold=0.5, min_confidence=None
    )
    assert unparseable.gate_status == "rejected"
    assert unparseable.gate_choice == "MAY"

    low = FakeJevClient(responses=[_noul(0.9), _choice("MUST", confidence=0.3)])
    suppressed = extract.gate_requirement(
        low, _requirement("MUST x"), threshold=0.5, min_confidence=0.5
    )
    assert suppressed.gate_status == "rejected"
    assert suppressed.low_confidence is True

import pytest
from pydantic import ValidationError

from smeargle.clients import dto
from smeargle.domain.jev import JevQuestion
from smeargle.domain.requirements import Keyword


def test_extraction_response_validates_and_converts_keywords():
    parsed = dto.ExtractionResponseModel.model_validate(
        {"requirements": [{"text": "The system MUST encrypt.", "keyword": "must_not"}]}
    )
    candidates = dto.extraction_to_candidates(parsed)
    assert candidates[0][0] == "The system MUST encrypt."
    assert candidates[0][1] is Keyword.MUST_NOT


def test_unknown_keyword_is_rejected_not_coerced():
    with pytest.raises(ValidationError):
        dto.ExtractionResponseModel.model_validate(
            {"requirements": [{"text": "x", "keyword": "OPTIONAL"}]}
        )


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        dto.loads_strict('{"a": 1, "a": 2}')


def test_out_of_range_probability_is_rejected():
    with pytest.raises(ValidationError):
        dto.JevAnswerModel.model_validate(
            {"answer": "yes", "answer_confidence": 1.5}
        )


def test_jev_response_converts_to_domain_values():
    response = dto.JevSystemOneResponseModel.model_validate(
        {"answers": {"q0": {"type": "noul", "action": {"act_probability": 1}, "noul": 0.9}}}
    )
    question = JevQuestion(question="q", kind="noul")
    result = dto.single_result_to_domain([question], response.answers)
    assert result.answers[0].answer == "yes"
    assert result.answers[0].answer_confidence == 0.9
    assert result.answers[0].confidence is None


def test_retrieval_and_index_dtos_require_expected_shapes():
    with pytest.raises(ValidationError):
        dto.NominationResponseModel.model_validate({"control_ids": "ac-2"})
    labels = dto.IndexResponseModel.model_validate(
        {"labels": [{"control_id": "ac-2", "domain": "access", "family": "Access"}]}
    )
    assert labels.labels[0].control_id == "ac-2"

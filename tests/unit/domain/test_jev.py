from smeargle.domain.jev import JevAnswer, JevQuestion, JevResult


def test_jev_values_are_frozen_and_hashable():
    question = JevQuestion(question="Is this genuine?", kind="noul")
    answer = JevAnswer(question=question.question, answer="yes", answer_confidence=0.9)
    result = JevResult(answers=(answer,))
    assert question.kind == "noul"
    assert result.answers[0].answer_confidence == 0.9
    assert result.answers[0].confidence is None
    hash(question)
    hash(answer)
    hash(result)
    assert JevResult(answers=(answer,), raw={"x": 1}) == JevResult(answers=(answer,), raw={"y": 2})


def test_choice_answer_records_entropy_confidence_separately():
    answer = JevAnswer(
        question="Which relation?", answer="subset-of", answer_confidence=0.7, confidence=0.2
    )
    assert answer.answer == "subset-of"
    assert answer.answer_confidence == 0.7
    assert answer.confidence == 0.2

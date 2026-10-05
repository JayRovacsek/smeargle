import json

import httpx
import respx

from smeargle.cli import main


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return document, catalog


def _chat(content):
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _answers(answer, confidence):
    return {"answers": [{"question": "q", "answer": answer, "answer_confidence": confidence}]}


def _mock():
    def llm(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]}))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat({"domains": ["access"]}))
        return httpx.Response(200, json=_chat({"control_ids": ["c-1.1"]}))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=llm)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=[
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("MUST", 0.9)),
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("subset-of", 0.85)),
    ])


def _common(tmp_path):
    return [
        "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "--yes",
        "--llm-endpoint", "https://llm.example", "--jev-endpoint", "https://jev.example",
    ]


@respx.mock
def test_run_emits_artifacts_and_prints_estimates(tmp_path, capsys):
    _mock()
    document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)])
    out = capsys.readouterr().out
    assert code == 0
    assert "requirement(s)" in out
    assert (tmp_path / "o" / "profile.json").exists()


@respx.mock
def test_extract_then_map_completes_the_run(tmp_path):
    _mock()
    document, catalog = _fixtures(tmp_path)
    base = _common(tmp_path) + ["--run-id", "run-x"]
    assert main(base + ["extract", "-i", str(document)]) == 0
    assert (tmp_path / "o" / "requirements-catalog.json").exists()
    assert not (tmp_path / "o" / "profile.json").exists()
    assert main(base + ["map", "-c", str(catalog)]) == 0
    assert (tmp_path / "o" / "profile.json").exists()


@respx.mock
def test_resume_after_a_completed_run_is_a_no_op(tmp_path):
    _mock()
    document, catalog = _fixtures(tmp_path)
    base = _common(tmp_path) + ["--run-id", "run-r"]
    assert main(base + ["run", "-i", str(document), "-c", str(catalog)]) == 0
    assert main(base + ["resume"]) == 0


@respx.mock
def test_run_exits_six_when_a_requirement_is_unmapped(tmp_path):
    def llm(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat({"labels": []}))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat({"domains": []}))
        return httpx.Response(200, json=_chat({"control_ids": []}))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=llm)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[httpx.Response(200, json=_answers("yes", 0.9)),
                     httpx.Response(200, json=_answers("MUST", 0.9))]
    )
    document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)])
    assert code == 6


def test_force_and_run_id_are_accepted_options(tmp_path, capsys):
    document, catalog = _fixtures(tmp_path)
    code = main([
        "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "--yes",
        "--run-id", "run-z", "--force",
        "run", "-i", str(document), "-c", str(catalog),
    ])
    assert code == 2
    assert "--llm-endpoint" in capsys.readouterr().err


@respx.mock
def test_map_without_a_run_selector_is_a_usage_error(tmp_path, capsys):
    _mock()
    _document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["map", "-c", str(catalog)])
    assert code == 2
    assert "run" in capsys.readouterr().err.lower()


@respx.mock
def test_resume_without_a_run_selector_is_a_usage_error(tmp_path, capsys):
    _mock()
    assert main(_common(tmp_path) + ["resume"]) == 2
    assert "run" in capsys.readouterr().err.lower()


def test_integrity_failure_exits_seven(tmp_path, monkeypatch):
    # CLI exit-code mapping only: the pipeline is stubbed, so no assembly or IO happens.
    # The real gate-before-write invariant is covered by Task 10's
    # `test_run_assemble_checks_integrity_before_writing_any_assemble_artifact`.
    from smeargle.errors import IntegrityError
    from smeargle.pipeline import run as run_pipeline

    def boom(*_args, **_kwargs):
        raise IntegrityError("broken output")

    monkeypatch.setattr(run_pipeline, "run_pipeline", boom)
    document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)])
    assert code == 7
    # The stubbed pipeline writes nothing, so the required output directory is never created.
    assert not (tmp_path / "o").exists()

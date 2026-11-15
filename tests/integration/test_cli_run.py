import json

import httpx
import respx

from smeargle.cli import main


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


def _answers(answer, confidence):
    if answer in {"yes", "no"}:
        payload = {"type": "noul", "action": {"act_probability": 1}, "confidence": confidence, "noul": confidence}
    else:
        payload = {
            "type": "choice", "action": {"act_probability": 1}, "confidence": confidence,
            "choice": answer, "probabilities": {answer: confidence},
        }
    return {"answers": {"q0": payload}}


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {"catalog": {"name": "V", "securityControls": [
                {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}
        ),
        encoding="utf-8",
    )
    return document, catalog


@respx.mock
def test_run_persists_and_status_reports_stages(tmp_path, capsys):
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[
            httpx.Response(200, json=_answers("yes", 0.9)),
            httpx.Response(200, json=_answers("MUST", 0.9)),
            httpx.Response(200, json=_answers("yes", 0.9)),
            httpx.Response(200, json=_answers("subset-of", 0.85)),
        ]
    )
    state = tmp_path / "state"
    output = tmp_path / "out"
    code = main(
        [
            "--state-dir", str(state), "--output", str(output), "--yes",
            "--llm-base-url", "https://llm.example",
            "--jev-base-url", "https://jev.example",
            "--jev-transport", "systemone",
            "run", "-i", str(document), "-c", str(catalog),
        ]
    )
    assert code == 0
    assert "requirement(s)" in capsys.readouterr().out

    code = main(["--state-dir", str(state), "status"])
    out = capsys.readouterr().out
    assert code == 0
    assert "extract" in out
    assert "classify" in out


def test_run_requires_base_urls(tmp_path):
    document, catalog = _fixtures(tmp_path)
    code = main(
        [
            "--state-dir", str(tmp_path / "state"), "--output", str(tmp_path / "out"),
            "run", "-i", str(document), "-c", str(catalog),
        ]
    )
    assert code == 2

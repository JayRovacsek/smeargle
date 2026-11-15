import json
import sqlite3

import httpx
import respx
from support.schemas import validate_against_schema

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


@respx.mock
def test_phase2_run_ingests_and_emits_valid_catalog(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog": {
                    "name": "Vendor Controls",
                    "securityControls": [
                        {
                            "controlId": "1.1",
                            "title": "Policy",
                            "family": "Access Control",
                            "description": "Establish a policy.",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    output = tmp_path / "out"

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(
                200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]}))
            )
        if "classify security controls" in prompt:
            return httpx.Response(
                200,
                json=_chat(
                    json.dumps(
                        {"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]}
                    )
                ),
            )
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

    code = main(
        [
            "--state-dir",
            str(state),
            "--output",
            str(output),
            "--yes",
            "--llm-base-url",
            "https://llm.example",
            "--jev-base-url",
            "https://jev.example",
            "--jev-transport",
            "systemone",
            "run",
            "-i",
            str(document),
            "-c",
            str(catalog),
        ]
    )

    assert code == 0

    conn = sqlite3.connect(state / "smeargle.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        catalog_count = conn.execute("SELECT COUNT(*) FROM catalogs").fetchone()[0]
        control_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        assert (run_count, document_count, catalog_count, control_count) == (1, 1, 1, 1)
    finally:
        conn.close()

    emitted = json.loads((output / "catalogs" / "vendor.json").read_text(encoding="utf-8"))
    validate_against_schema("catalog", emitted)
    assert emitted["catalog"]["metadata"]["oscal-version"] == "1.2.3"

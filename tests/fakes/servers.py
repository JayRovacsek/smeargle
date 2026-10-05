"""In-thread real HTTP fake LLM and JEV servers for e2e tests (spec 14)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        response = self.server.responder(self.path, body)
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


class FakeHttpService:
    def __init__(self, responder):
        self._calls = 0
        self._lock = threading.Lock()
        self._responder = responder
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.responder = self._respond
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _respond(self, path, body):
        with self._lock:
            self._calls += 1
        return self._responder(path, body)

    @property
    def calls(self):
        with self._lock:
            return self._calls

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def llm_responder(path, body):
    prompt = body["messages"][0]["content"]
    if "extract normative requirements" in prompt:
        content = {"requirements": [{"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}
    elif "classify security controls" in prompt:
        content = {"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]}
    elif "control domains" in prompt:
        content = {"domains": ["access"]}
    else:
        content = {"control_ids": ["c-1.1"]}
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _noul(confidence):
    return {"type": "noul", "action": {"act_probability": 1}, "confidence": confidence, "noul": confidence}


def _choice(choice, confidence):
    return {
        "type": "choice", "action": {"act_probability": 1}, "confidence": confidence,
        "choice": choice, "probabilities": {choice: confidence},
    }


def jev_responder(path, body):
    questions = body.get("questions", {})
    question = next(iter(questions.values())) if questions else {"type": "noul"}
    if question["type"] == "noul":
        return {"answers": {"q0": _noul(0.9)}}
    criteria = question.get("criteria", {})
    if "MUST" in criteria:
        return {"answers": {"q0": _choice("MUST", 0.9)}}
    return {"answers": {"q0": _choice("subset-of", 0.85)}}

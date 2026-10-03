import httpx
import respx

from smeargle.clients import http


@respx.mock
def test_client_sends_bearer_token_and_content_type():
    route = respx.post("https://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = http.build_client(base_url="https://llm.example", timeout=5.0, token="secret")
    with client:
        client.post("/v1/chat/completions", json={})
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer secret"
    assert request.headers["content-type"] == "application/json"


@respx.mock
def test_client_without_token_omits_authorization():
    route = respx.get("https://jev.example/health").mock(
        return_value=httpx.Response(200, json={})
    )
    client = http.build_client(base_url="https://jev.example", timeout=5.0, token=None)
    with client:
        client.get("/health")
    assert "authorization" not in route.calls[0].request.headers


def test_token_precedence_auth_file_then_env(tmp_path, monkeypatch):
    auth_file = tmp_path / "token"
    auth_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setenv("SMEARGLE_TEST_KEY", "from-env")
    assert http.load_bearer_token(auth_file=auth_file, api_key_env="SMEARGLE_TEST_KEY") == "from-file"
    assert http.load_bearer_token(auth_file=None, api_key_env="SMEARGLE_TEST_KEY") == "from-env"
    assert http.load_bearer_token(auth_file=None, api_key_env=None) is None

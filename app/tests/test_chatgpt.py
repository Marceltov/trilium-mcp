import httpx
import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture
def chatgpt(monkeypatch):
    """The token-mode app with CHATGPT_ACTIONS on, over a mock Trilium that
    records every forwarded request."""
    monkeypatch.setenv(server.CHATGPT_ENV, "true")
    monkeypatch.setenv(server.BASE_URL_ENV, "https://mcp.example/")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    etapi = httpx.AsyncClient(
        base_url="http://trilium:8080/etapi",
        auth=server.EtapiTokenAuth(),
        transport=httpx.MockTransport(handler),
    )
    app = server.TokenCaptureMiddleware(
        server.build_server(client=etapi).http_app(path=server.DEFAULT_PATH)
    )
    return TestClient(app), seen


def test_spec_is_public_trimmed_and_points_at_proxy(chatgpt):
    http, _ = chatgpt
    spec = http.get(server.CHATGPT_SPEC_PATH).json()
    ops = {
        op["operationId"]: op
        for item in spec["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    }
    assert len(ops) == 30
    assert not server.CHATGPT_DROP & ops.keys()
    assert all(len(op.get("description", "")) <= 300 for op in ops.values())
    assert spec["servers"] == [{"url": "https://mcp.example/chatgpt/etapi"}]
    assert "application/json" in ops["putNoteContentById"]["requestBody"]["content"]


def test_proxy_forwards_with_stripped_token(chatgpt):
    http, seen = chatgpt
    r = http.get(
        "/chatgpt/etapi/notes", params={"search": "x", "limit": "5"},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert seen[0].url.path == "/etapi/notes"
    assert seen[0].url.params["search"] == "x"
    assert seen[0].headers["Authorization"] == "tok"


def test_note_content_json_becomes_text_plain(chatgpt):
    http, seen = chatgpt
    r = http.put(
        "/chatgpt/etapi/notes/abc/content", json={"content": "<p>hi</p>"},
        headers={"Authorization": "tok"},
    )
    assert r.status_code == 200
    assert seen[0].content == b"<p>hi</p>"
    assert seen[0].headers["content-type"] == "text/plain; charset=utf-8"
    bad = http.put(
        "/chatgpt/etapi/notes/abc/content", content=b"raw", headers={"Authorization": "tok"}
    )
    assert bad.status_code == 400


def test_proxy_blocks_operations_outside_the_spec(chatgpt):
    http, seen = chatgpt
    for method, path in [("POST", "/auth/login"), ("GET", "/attachments/a1"), ("DELETE", "/notes")]:
        r = http.request(method, "/chatgpt/etapi" + path, headers={"Authorization": "tok"})
        assert r.status_code == 404, path
    assert not seen


def test_proxy_requires_token(chatgpt):
    http, seen = chatgpt
    assert http.get("/chatgpt/etapi/app-info").status_code == 401
    assert not seen


def test_flag_without_base_url_fails_startup(monkeypatch):
    monkeypatch.setenv(server.CHATGPT_ENV, "true")
    monkeypatch.delenv(server.BASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match=server.BASE_URL_ENV):
        server.build_server()

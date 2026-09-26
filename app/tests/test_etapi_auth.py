import httpx
import pytest

import server


def _run_auth(header_value):
    reset = server._incoming_auth.set(header_value)
    try:
        auth = server.EtapiTokenAuth()
        request = httpx.Request("GET", "http://trilium:8080/etapi/app-info")
        return next(auth.auth_flow(request))
    finally:
        server._incoming_auth.reset(reset)


def test_strips_bearer_prefix():
    out = _run_auth("Bearer secret-token")
    assert out.headers["Authorization"] == "secret-token"


def test_bearer_prefix_case_insensitive():
    out = _run_auth("bearer secret-token")
    assert out.headers["Authorization"] == "secret-token"


def test_raw_token_passthrough():
    out = _run_auth("raw-token-no-prefix")
    assert out.headers["Authorization"] == "raw-token-no-prefix"


def test_missing_token_raises():
    reset = server._incoming_auth.set(None)
    try:
        auth = server.EtapiTokenAuth()
        request = httpx.Request("GET", "http://trilium:8080/etapi/app-info")
        with pytest.raises(RuntimeError):
            next(auth.auth_flow(request))
    finally:
        server._incoming_auth.reset(reset)


def test_empty_after_bearer_strip_raises():
    reset = server._incoming_auth.set("Bearer ")
    try:
        with pytest.raises(RuntimeError):
            next(server.EtapiTokenAuth().auth_flow(
                httpx.Request("GET", "http://trilium:8080/etapi/app-info")))
    finally:
        server._incoming_auth.reset(reset)


def test_bearer_with_only_whitespace_raises():
    reset = server._incoming_auth.set("Bearer     ")
    try:
        with pytest.raises(RuntimeError):
            next(server.EtapiTokenAuth().auth_flow(
                httpx.Request("GET", "http://trilium:8080/etapi/app-info")))
    finally:
        server._incoming_auth.reset(reset)


def test_oauth_access_token_claim_wins(monkeypatch):
    from fastmcp.server.auth import AccessToken

    token = AccessToken(
        token="tmcp_x", client_id="c1", scopes=[], claims={"etapi_token": "minted"}
    )
    monkeypatch.setattr(server, "get_access_token", lambda: token)
    out = _run_auth("Bearer tmcp_x")
    assert out.headers["Authorization"] == "minted"

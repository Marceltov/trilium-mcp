"""Drive the OAuth 2.1 browser flow against the live stack (both mode)."""

import base64
import hashlib
import secrets

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.live._client import MCP_URL, run_async

BASE = str(httpx.URL(MCP_URL).copy_with(path="/", query=None)).rstrip("/")
PASSWORD = "trilium-mcp"  # committed dev fixture password (see CLAUDE.md)
REDIRECT = "http://localhost:9/cb"


def _login(http: httpx.Client) -> dict:
    """register -> authorize -> /login -> token; returns the token JSON + client_id."""
    client_id = http.post("/register", json={
        "client_name": "live-oauth", "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }).json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    r = http.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
    })
    pending = httpx.URL(r.headers["location"]).params["id"]
    r = http.post("/login", data={"id": pending, "password": PASSWORD})
    code = httpx.URL(r.headers["location"]).params["code"]
    tokens = http.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier,
    }).json()
    return {**tokens, "client_id": client_id}


def test_oauth_access_token_calls_a_tool():
    with httpx.Client(base_url=BASE) as http:
        tokens = _login(http)

    async def go():
        transport = StreamableHttpTransport(
            MCP_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        async with Client(transport) as c:
            return await c.call_tool("getAppInfo", {})

    assert run_async(go()).data["appVersion"]


def test_refresh_rotates_and_old_access_token_is_rejected():
    with httpx.Client(base_url=BASE) as http:
        tokens = _login(http)
        r = http.post("/token", data={
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        })
        assert r.status_code == 200
        assert r.json()["access_token"] != tokens["access_token"]
        stale = http.post(
            "/mcp", json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert stale.status_code == 401

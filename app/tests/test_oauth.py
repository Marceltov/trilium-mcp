"""OAuth through mcp-login-oauth, driven end to end over HTTP against a fake Trilium:
register -> authorize -> /login -> /token -> MCP tool call, refresh and /revoke.
The library's own tests cover the OAuth machinery; these cover how this server
plugs into it (the login check, the grant, logout on revoke, both mode)."""

import asyncio
import base64
import hashlib
import json
import secrets

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from key_value.aio.stores.memory import MemoryStore

import server
from tests.test_integration import APP_INFO

BASE = "http://localhost"
ETAPI = "http://trilium:8080/etapi"
REDIRECT = "http://localhost:9/cb"


class FakeTrilium:
    """ETAPI with the password `pw`; records every request."""

    def __init__(self):
        self.calls: list[httpx2.Request] = []
        self.transport = httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/auth/login"):
            if json.loads(request.content)["password"] == "pw":
                return httpx2.Response(201, json={"authToken": "minted-etapi"})
            return httpx2.Response(401, json={"status": 401})
        if path.endswith("/auth/logout"):
            return httpx2.Response(204)
        if path.endswith("/app-info"):
            return httpx2.Response(200, json=APP_INFO)
        return httpx2.Response(404)

    def to(self, suffix: str) -> list[httpx2.Request]:
        return [c for c in self.calls if c.url.path.endswith(suffix)]


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("MCP_BASE_URL", BASE)
    monkeypatch.setenv("MCP_OAUTH_SECRET", "s3cret-s3cret")


def make_app(trilium: FakeTrilium, mode: str):
    """This server's ASGI app in `mode`, on an in-memory store; returns (app, inner)."""
    provider = server.build_oauth_provider(
        mode, etapi=httpx2.AsyncClient(base_url=ETAPI, transport=trilium.transport),
        store=MemoryStore(),
    )
    mcp = server.build_server(
        client=httpx2.AsyncClient(base_url=ETAPI, auth=server.EtapiTokenAuth(),
                                  transport=trilium.transport),
        auth=provider,
    )
    inner = mcp.http_app(path=server.DEFAULT_PATH)
    return server.wrap_app(inner, mode), inner


def run(app, inner, scenario):
    """Run `scenario(http, call_tool)` against the app inside its lifespan."""

    def factory(**kw):
        kw.pop("transport", None)
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, **kw)

    async def call_tool(authorization: str, name: str = "getAppInfo"):
        transport = StreamableHttpTransport(url=f"{BASE}/mcp", headers={"Authorization": authorization},
                                            httpx_client_factory=factory)
        async with Client(transport) as c:
            return await c.call_tool(name, {})

    async def go():
        async with inner.router.lifespan_context(inner):
            async with factory() as http:
                return await scenario(http, call_tool)

    return asyncio.run(go())


async def start_login(http) -> tuple[str, str, str]:
    """register -> authorize: (client id, pending login id, PKCE verifier)."""
    r = await http.post("/register", json={
        "client_name": "itest", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
    })
    client_id = r.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = await http.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s1",
    })
    return client_id, httpx2.URL(r.headers["location"]).params["id"], verifier


async def login(http) -> dict:
    """The whole browser login; the token response plus client_id."""
    client_id, pending, verifier = await start_login(http)
    r = await http.post("/login", data={"id": pending, "password": "pw"})
    code = httpx2.URL(r.headers["location"]).params["code"]
    r = await http.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier,
    })
    assert r.status_code == 200, r.text
    return {**r.json(), "client_id": client_id}


def test_full_oauth_flow_forwards_minted_etapi_token(oauth_env):
    """The tool's ETAPI call must carry the token minted by /auth/login."""
    trilium = FakeTrilium()

    async def scenario(http, call_tool):
        r = await http.post(server.DEFAULT_PATH, json={})
        assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
        client_id, pending, verifier = await start_login(http)
        page = await http.get("/login", params={"id": pending})
        assert "itest" in page.text and "localhost:9" in page.text and "Trilium password" in page.text
        bad = await http.post("/login", data={"id": pending, "password": "nope"})
        assert bad.status_code == 401 and "Trilium rejected the login (HTTP 401)" in bad.text
        r = await http.post("/login", data={"id": pending, "password": "pw"})
        back = httpx2.URL(r.headers["location"])  # pending login survived the typo
        assert back.params["state"] == "s1"
        r = await http.post("/token", data={
            "grant_type": "authorization_code", "code": back.params["code"], "redirect_uri": REDIRECT,
            "client_id": client_id, "code_verifier": verifier,
        })
        access = r.json()["access_token"]
        assert access.startswith(server.OAUTH_TOKEN_PREFIX)
        return await call_tool(f"Bearer {access}")

    result = run(*make_app(trilium, "oauth"), scenario)
    assert result.data["appVersion"] == "1"
    assert trilium.to("/app-info")[-1].headers["Authorization"] == "minted-etapi"


def test_refresh_keeps_the_minted_token_and_kills_the_old_access(oauth_env):
    trilium = FakeTrilium()

    async def scenario(http, call_tool):
        tokens = await login(http)
        r = await http.post("/token", data={"grant_type": "refresh_token", "client_id": tokens["client_id"],
                                            "refresh_token": tokens["refresh_token"]})
        assert r.status_code == 200, r.text
        await call_tool(f"Bearer {r.json()['access_token']}")
        old = await http.post(server.DEFAULT_PATH, json={},
                              headers={"Authorization": f"Bearer {tokens['access_token']}"})
        return old.status_code

    assert run(*make_app(trilium, "oauth"), scenario) == 401
    assert trilium.to("/app-info")[-1].headers["Authorization"] == "minted-etapi"
    assert len(trilium.to("/auth/login")) == 1


def test_revoke_logs_the_minted_token_out_of_trilium(oauth_env):
    """claude.ai is a public client: revoking must work without a client secret."""
    trilium = FakeTrilium()

    async def scenario(http, call_tool):
        tokens = await login(http)
        r = await http.post("/revoke", data={"token": tokens["refresh_token"], "client_id": tokens["client_id"]})
        assert r.status_code == 200
        after = await http.post(server.DEFAULT_PATH, json={},
                                headers={"Authorization": f"Bearer {tokens['access_token']}"})
        return after.status_code

    assert run(*make_app(trilium, "oauth"), scenario) == 401
    logout = trilium.to("/auth/logout")
    assert len(logout) == 1 and logout[0].headers["Authorization"] == "minted-etapi"


def test_both_mode_accepts_raw_header_without_bearer(oauth_env):
    """Existing clients send `Authorization: <etapi token>` (no Bearer); in both
    mode that must still reach Trilium, as it does in token mode."""
    trilium = FakeTrilium()
    run(*make_app(trilium, "both"), lambda http, call_tool: call_tool("raw-etapi-token"))
    assert trilium.to("/app-info")[-1].headers["Authorization"] == "raw-etapi-token"


def test_oauth_mode_rejects_raw_etapi_token(oauth_env):
    async def scenario(http, call_tool):
        r = await http.post(server.DEFAULT_PATH, json={}, headers={"Authorization": "Bearer raw-etapi"})
        return r.status_code

    assert run(*make_app(FakeTrilium(), "oauth"), scenario) == 401


def test_stale_prefixed_token_is_rejected_even_in_both_mode(oauth_env):
    """An expired/revoked OAuth token must 401 (so the client refreshes), not be
    forwarded to Trilium as if it were a raw ETAPI token."""
    trilium = FakeTrilium()

    async def scenario(http, call_tool):
        r = await http.post(server.DEFAULT_PATH, json={},
                            headers={"Authorization": f"Bearer {server.OAUTH_TOKEN_PREFIX}gone"})
        return r.status_code

    assert run(*make_app(trilium, "both"), scenario) == 401
    assert not trilium.to("/app-info")


def assert_explains_reconnect(page: str):
    """Dead-end login pages must say why it happened (the app interrupted its own
    flow, e.g. a claude.ai login), that it isn't the server's fault, and the fix."""
    assert "Nothing is wrong with this server" in page
    assert "remove the connector and add it again" in page
    assert "Reconnect" in page


def test_expired_login_link_is_rejected(oauth_env):
    async def scenario(http, call_tool):
        return await http.get("/login", params={"id": "nope"})

    r = run(*make_app(FakeTrilium(), "oauth"), scenario)
    assert r.status_code == 400
    assert_explains_reconnect(r.text)


def test_replayed_login_says_completed_and_mints_nothing(oauth_env):
    """A browser can re-submit the login form after it succeeded (seen with
    claude.ai's connector flow). The replay must not mint a second ETAPI token,
    and must not claim the link "expired" -- the login already went through."""
    trilium = FakeTrilium()

    async def scenario(http, call_tool):
        _, pending, _ = await start_login(http)
        first = await http.post("/login", data={"id": pending, "password": "pw"})
        assert first.status_code == 302
        return await http.post("/login", data={"id": pending, "password": "pw"})

    replay = run(*make_app(trilium, "oauth"), scenario)
    assert replay.status_code == 200
    assert "already completed" in replay.text and "expired" not in replay.text
    assert_explains_reconnect(replay.text)
    assert len(trilium.to("/auth/login")) == 1


OAUTH_VARS = {"MCP_BASE_URL": "https://mcp.example", "MCP_OAUTH_SECRET": "s3cret-s3cret"}


@pytest.mark.parametrize(
    "mode, env, expected",
    [
        (None, {}, "token"),              # unset + no OAuth vars: safe upgrade path
        (None, OAUTH_VARS, "both"),       # unset + vars: default is both
        ("token", {}, "token"),
        ("oauth", OAUTH_VARS, "oauth"),
        ("BOTH", OAUTH_VARS, "both"),
    ],
)
def test_resolve_auth_mode(monkeypatch, mode, env, expected):
    for var in ("MCP_AUTH_MODE", *OAUTH_VARS):
        monkeypatch.delenv(var, raising=False)
    if mode:
        monkeypatch.setenv("MCP_AUTH_MODE", mode)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert server.resolve_auth_mode() == expected


@pytest.mark.parametrize("mode", ["oauth", "both", "bogus"])
def test_resolve_auth_mode_fails_loudly_when_explicit(monkeypatch, mode):
    for var in OAUTH_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MCP_AUTH_MODE", mode)
    with pytest.raises(RuntimeError, match="MCP_"):
        server.resolve_auth_mode()


def test_encrypted_store_round_trips(monkeypatch, tmp_path):
    from mcp.shared.auth import OAuthClientInformationFull

    monkeypatch.setattr(server, "OAUTH_STORE_DIR", tmp_path)
    for k, v in OAUTH_VARS.items():
        monkeypatch.setenv(k, v)
    p = server.build_oauth_provider("both")
    client = OAuthClientInformationFull(client_id="c1", redirect_uris=[REDIRECT])

    async def go():
        await p.register_client(client)
        return await p.get_client("c1")

    assert asyncio.run(go()).client_id == "c1"
    stored = b"".join(f.read_bytes() for f in tmp_path.rglob("*.json"))
    assert stored and b"localhost:9" not in stored  # encrypted at rest


def test_plain_http_base_url_fails_at_startup(monkeypatch, tmp_path):
    # OAuth issuers must be HTTPS (localhost excepted); catch it while building,
    # so main() shows startup_error instead of serve() crashing later.
    monkeypatch.setattr(server, "OAUTH_STORE_DIR", tmp_path)
    monkeypatch.setenv("MCP_BASE_URL", "http://192.168.1.50:8081")
    monkeypatch.setenv("MCP_OAUTH_SECRET", "s3cret-s3cret")
    with pytest.raises(RuntimeError, match="MCP_BASE_URL.*HTTPS"):
        server.build_oauth_provider("both")

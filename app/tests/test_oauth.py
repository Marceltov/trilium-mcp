import asyncio
import json

import httpx
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.auth import OAuthClientInformationFull

import server

CLIENT = OAuthClientInformationFull(client_id="c1", redirect_uris=["http://localhost:9/cb"])


def make_provider(passthrough=True):
    """Provider on an in-memory store with a fake Trilium; returns (provider, calls)."""
    calls = []

    def trilium(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/auth/login"):
            if json.loads(request.content)["password"] == "pw":
                return httpx.Response(201, json={"authToken": "minted-etapi"})
            return httpx.Response(401, json={"status": 401})
        if request.url.path.endswith("/auth/logout"):
            return httpx.Response(204)
        return httpx.Response(404)

    etapi = httpx.AsyncClient(
        base_url="http://trilium:8080/etapi", transport=httpx.MockTransport(trilium)
    )
    provider = server.TriliumOAuthProvider(
        base_url="http://localhost", store=MemoryStore(), etapi=etapi, passthrough=passthrough
    )
    return provider, calls


def test_issued_token_maps_to_etapi_token():
    p, _ = make_provider()

    async def go():
        tok = await p._issue("c1", [], "etapi-x")
        return tok, await p.verify_token(tok.access_token)

    tok, found = asyncio.run(go())
    assert tok.access_token.startswith(server.OAUTH_TOKEN_PREFIX)
    assert found.claims["etapi_token"] == "etapi-x"


def test_both_mode_passes_unknown_bearer_through():
    p, _ = make_provider(passthrough=True)
    found = asyncio.run(p.verify_token("raw-etapi"))
    assert found.claims["etapi_token"] == "raw-etapi"


def test_oauth_mode_rejects_unknown_bearer():
    p, _ = make_provider(passthrough=False)
    assert asyncio.run(p.verify_token("raw-etapi")) is None


def test_stale_prefixed_token_is_rejected_even_in_both_mode():
    # An expired/revoked OAuth token must 401 (so the client refreshes), not be
    # forwarded to Trilium as if it were a raw ETAPI token.
    p, _ = make_provider(passthrough=True)
    assert asyncio.run(p.verify_token(server.OAUTH_TOKEN_PREFIX + "gone")) is None


def test_refresh_rotates_the_pair():
    p, _ = make_provider()

    async def go():
        first = await p._issue("c1", [], "etapi-x")
        rt = await p.load_refresh_token(CLIENT, first.refresh_token)
        second = await p.exchange_refresh_token(CLIENT, rt, [])
        return (
            await p.verify_token(first.access_token),
            await p.load_refresh_token(CLIENT, first.refresh_token),
            await p.verify_token(second.access_token),
        )

    old_access, old_refresh, new_access = asyncio.run(go())
    assert old_access is None and old_refresh is None
    assert new_access.claims["etapi_token"] == "etapi-x"


def test_revoke_drops_pair_and_logs_out_of_trilium():
    p, calls = make_provider()

    async def go():
        tok = await p._issue("c1", [], "etapi-x")
        await p.revoke_token(await p.load_access_token(tok.access_token))
        return tok, await p.load_refresh_token(CLIENT, tok.refresh_token)

    tok, refresh = asyncio.run(go())
    assert refresh is None
    logout = [c for c in calls if c.url.path.endswith("/auth/logout")]
    assert logout and logout[0].headers["Authorization"] == "etapi-x"


def test_registered_client_round_trips():
    p, _ = make_provider()

    async def go():
        await p.register_client(CLIENT)
        return await p.get_client("c1")

    assert asyncio.run(go()).redirect_uris == CLIENT.redirect_uris


import base64
import hashlib
import secrets

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.test_integration import APP_INFO

REDIRECT = "http://localhost:9/cb"


def test_full_oauth_flow_forwards_minted_etapi_token():
    """register -> authorize -> /login -> token -> MCP tool call, all in-process;
    the tool's ETAPI call must carry the token minted by /auth/login."""
    seen = {}

    def trilium(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            ok = json.loads(request.content)["password"] == "pw"
            return httpx.Response(201, json={"authToken": "minted-etapi"}) if ok else httpx.Response(401)
        if request.url.path.endswith("/app-info"):
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=APP_INFO)
        return httpx.Response(404)

    mock = httpx.MockTransport(trilium)
    base = "http://trilium:8080/etapi"
    provider = server.TriliumOAuthProvider(
        base_url="http://localhost",
        store=MemoryStore(),
        etapi=httpx.AsyncClient(base_url=base, transport=mock),
        passthrough=False,
    )
    mcp = server.build_server(
        client=httpx.AsyncClient(base_url=base, auth=server.EtapiTokenAuth(), transport=mock),
        auth=provider,
    )
    app = mcp.http_app(path=server.DEFAULT_PATH)

    def factory(**kw):
        kw.pop("transport", None)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", **kw
        )

    async def run():
        async with app.router.lifespan_context(app):
            async with factory() as http:
                # Unauthenticated MCP call -> 401 that points at OAuth discovery.
                r = await http.post(server.DEFAULT_PATH, json={})
                assert r.status_code == 401
                assert "resource_metadata" in r.headers["www-authenticate"]

                r = await http.post("/register", json={
                    "client_name": "itest", "redirect_uris": [REDIRECT],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                })
                client_id = r.json()["client_id"]
                verifier = secrets.token_urlsafe(48)
                challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode()).digest()
                ).rstrip(b"=").decode()
                r = await http.get("/authorize", params={
                    "response_type": "code", "client_id": client_id,
                    "redirect_uri": REDIRECT, "code_challenge": challenge,
                    "code_challenge_method": "S256", "state": "s1",
                })
                pending = httpx.URL(r.headers["location"]).params["id"]

                page = await http.get("/login", params={"id": pending})
                assert "itest" in page.text and "localhost:9" in page.text
                bad = await http.post("/login", data={"id": pending, "password": "nope"})
                assert bad.status_code == 401  # pending login survives a typo
                r = await http.post("/login", data={"id": pending, "password": "pw"})
                back = httpx.URL(r.headers["location"])
                assert back.params["state"] == "s1"

                r = await http.post("/token", data={
                    "grant_type": "authorization_code", "code": back.params["code"],
                    "redirect_uri": REDIRECT, "client_id": client_id,
                    "code_verifier": verifier,
                })
                access = r.json()["access_token"]

            transport = StreamableHttpTransport(
                url="http://localhost/mcp",
                headers={"Authorization": f"Bearer {access}"},
                httpx_client_factory=factory,
            )
            async with Client(transport) as c:
                return await c.call_tool("getAppInfo", {})

    result = asyncio.run(run())
    assert result.data["appVersion"] == "1"
    assert seen["auth"] == "minted-etapi"


def test_expired_login_link_is_rejected():
    p, _ = make_provider()
    app = p.get_routes(server.DEFAULT_PATH)
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    r = TestClient(Starlette(routes=app)).get("/login", params={"id": "nope"})
    assert r.status_code == 400
    assert_explains_reconnect(r.text)


def assert_explains_reconnect(page: str):
    """Dead-end login pages must say why it happened (the app interrupted its own
    flow, e.g. a claude.ai login), that it isn't the server's fault, and the fix."""
    assert "claude.ai" in page
    assert "Nothing is wrong with your Trilium or this MCP server" in page
    assert "remove this connector and add it again" in page
    assert "Reconnect" in page


import pytest

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
    monkeypatch.setattr(server, "OAUTH_STORE_DIR", tmp_path)
    for k, v in OAUTH_VARS.items():
        monkeypatch.setenv(k, v)
    p = server.build_oauth_provider("both")

    async def go():
        await p.register_client(CLIENT)
        return await p.get_client("c1")

    assert asyncio.run(go()).client_id == "c1"
    stored = b"".join(f.read_bytes() for f in tmp_path.rglob("*.json"))
    assert b"localhost:9" not in stored  # encrypted at rest


def test_plain_http_base_url_fails_at_startup(monkeypatch, tmp_path):
    # OAuth issuers must be HTTPS (localhost excepted); catch it while building,
    # so main() shows startup_error instead of serve() crashing later.
    monkeypatch.setattr(server, "OAUTH_STORE_DIR", tmp_path)
    monkeypatch.setenv("MCP_BASE_URL", "http://192.168.1.50:8081")
    monkeypatch.setenv("MCP_OAUTH_SECRET", "s3cret-s3cret")
    with pytest.raises(RuntimeError, match="MCP_BASE_URL.*HTTPS"):
        server.build_oauth_provider("both")


def test_both_mode_accepts_raw_header_without_bearer():
    """Existing clients send `Authorization: <etapi token>` (no Bearer); in both
    mode that must still reach Trilium, as it does in token mode."""
    seen = {}

    def trilium(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=APP_INFO)

    mock = httpx.MockTransport(trilium)
    base = "http://trilium:8080/etapi"
    provider = server.TriliumOAuthProvider(
        base_url="http://localhost", store=MemoryStore(),
        etapi=httpx.AsyncClient(base_url=base, transport=mock), passthrough=True,
    )
    mcp = server.build_server(
        client=httpx.AsyncClient(base_url=base, auth=server.EtapiTokenAuth(), transport=mock),
        auth=provider,
    )
    inner = mcp.http_app(path=server.DEFAULT_PATH)
    app = server.wrap_app(inner, "both")

    def factory(**kw):
        kw.pop("transport", None)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", **kw
        )

    async def run():
        async with inner.router.lifespan_context(inner):
            transport = StreamableHttpTransport(
                url="http://localhost/mcp",
                headers={"Authorization": "raw-etapi-token"},
                httpx_client_factory=factory,
            )
            async with Client(transport) as c:
                return await c.call_tool("getAppInfo", {})

    asyncio.run(run())
    assert seen["auth"] == "raw-etapi-token"


def test_replayed_login_says_completed_and_mints_nothing():
    """A browser can re-submit the login form after it succeeded (seen with
    claude.ai's connector flow). The replay must not mint a second ETAPI token,
    and must not claim the link "expired" -- the login already went through."""
    p, calls = make_provider()
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    async def begin():
        await p.register_client(CLIENT)
        from mcp.server.auth.provider import AuthorizationParams
        url = await p.authorize(CLIENT, AuthorizationParams(
            state="s", scopes=[], code_challenge="x" * 43,
            redirect_uri="http://localhost:9/cb", redirect_uri_provided_explicitly=True,
        ))
        return httpx.URL(url).params["id"]

    pending = asyncio.run(begin())
    http = TestClient(Starlette(routes=p.get_routes(server.DEFAULT_PATH)), follow_redirects=False)
    first = http.post("/login", data={"id": pending, "password": "pw"})
    assert first.status_code == 302
    replay = http.post("/login", data={"id": pending, "password": "pw"})
    assert replay.status_code == 200
    assert "already" in replay.text and "expired" not in replay.text
    assert_explains_reconnect(replay.text)
    assert len([c for c in calls if c.url.path.endswith("/auth/login")]) == 1

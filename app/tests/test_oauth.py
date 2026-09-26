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
        base_url="http://test", store=MemoryStore(), etapi=etapi, passthrough=passthrough
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

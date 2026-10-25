import asyncio

import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

import server

APP_INFO = {
    "appVersion": "1", "dbVersion": 1, "syncVersion": 1,
    "buildDate": "2026-01-01T00:00:00Z", "buildRevision": "r",
    "dataDirectory": "/d", "clipperProtocolVersion": "1",
    "utcDateTime": "2026-01-01T00:00:00Z",
}


def test_full_chain_forwards_stripped_token():
    """Client sends `Authorization: Bearer <token>`; TokenCaptureMiddleware
    captures it and EtapiTokenAuth forwards the raw token (no Bearer prefix)
    to Trilium's ETAPI, driven through the real ASGI app end-to-end."""
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["auth"] = request.headers.get("Authorization")
        if request.url.path.endswith("/app-info"):
            return httpx2.Response(200, json=APP_INFO)
        return httpx2.Response(404, json={"status": 404})

    etapi = httpx2.AsyncClient(
        base_url="http://trilium:8080/etapi",
        auth=server.EtapiTokenAuth(),
        transport=httpx2.MockTransport(handler),
    )
    mcp = server.build_server(client=etapi)
    inner = mcp.http_app(path=server.DEFAULT_PATH)
    wrapped = server.TokenCaptureMiddleware(inner)

    def factory(**kw):
        kw.pop("transport", None)
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=wrapped),
            base_url="http://test", **kw,
        )

    transport = StreamableHttpTransport(
        url="http://test/mcp",
        headers={"Authorization": "Bearer secret-etapi-token"},
        httpx_client_factory=factory,
    )

    async def run():
        # Drive the inner app's lifespan so the streamable-HTTP session
        # manager initializes (the middleware forwards the lifespan scope).
        async with inner.router.lifespan_context(inner):
            async with Client(transport) as client:
                return await client.call_tool("getAppInfo", {})

    result = asyncio.run(run())
    assert isinstance(result.data, dict)
    assert result.data["appVersion"] == "1"
    assert captured["auth"] == "secret-etapi-token"  # Bearer stripped, raw forwarded

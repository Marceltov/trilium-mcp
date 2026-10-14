import asyncio
import io
import zipfile

import httpx

import server


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _export_client(zip_payload: bytes) -> httpx.AsyncClient:
    """Client whose transport returns a binary ZIP for the export endpoint,
    exactly the shape that crashes FastMCP's JSON-decoding tool."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/export"):
            return httpx.Response(
                200, content=zip_payload,
                headers={"content-type": "application/zip"},
            )
        return httpx.Response(404, json={"status": 404})

    return httpx.AsyncClient(
        base_url="http://trilium:8080/etapi",
        auth=server.EtapiTokenAuth(),
        transport=httpx.MockTransport(handler),
    )


def _capture_put_content_client(captured: dict) -> httpx.AsyncClient:
    """Client whose transport records the PUT /content request so we can assert
    the raw body and Content-Type header reach Trilium (they didn't before the
    fix: FastMCP sent a scalar text/plain body with no Content-Type)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/content") and request.method == "PUT":
            captured["content_type"] = request.headers.get("content-type")
            captured["body"] = request.content
            return httpx.Response(204)
        return httpx.Response(404, json={"status": 404})

    return httpx.AsyncClient(
        base_url="http://trilium:8080/etapi",
        auth=server.EtapiTokenAuth(),
        transport=httpx.MockTransport(handler),
    )


def _mock_client():
    """An httpx client whose transport fakes Trilium's create-note response,
    including branch.prefix == null (the field the spec types as string)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/create-note"):
            return httpx.Response(201, json={
                "note": {
                    "noteId": "abc123", "isProtected": False, "title": "t",
                    "type": "text", "mime": "text/html", "blobId": "b1",
                    "dateCreated": "2026-07-08 00:00:00.000+0000",
                    "dateModified": "2026-07-08 00:00:00.000+0000",
                    "utcDateCreated": "2026-07-08 00:00:00.000Z",
                    "utcDateModified": "2026-07-08 00:00:00.000Z",
                    "parentNoteIds": ["root"], "childNoteIds": [],
                    "parentBranchIds": ["root_abc123"], "childBranchIds": [],
                    "attributes": [],
                },
                "branch": {
                    "branchId": "root_abc123", "noteId": "abc123",
                    "parentNoteId": "root", "prefix": None, "notePosition": 10,
                    "isExpanded": False,
                    "utcDateModified": "2026-07-08 00:00:00.000Z",
                },
            })
        return httpx.Response(404, json={"status": 404})

    return httpx.AsyncClient(
        base_url="http://trilium:8080/etapi",
        auth=server.EtapiTokenAuth(),
        transport=httpx.MockTransport(handler),
    )


def _content_client(html: bytes) -> httpx.AsyncClient:
    """Client whose transport returns text/html for the note-content endpoint,
    the shape that tripped the output-schema validation before the fix."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/content"):
            return httpx.Response(
                200, content=html, headers={"content-type": "text/html"},
            )
        return httpx.Response(404, json={"status": 404})

    return httpx.AsyncClient(
        base_url="http://trilium:8080/etapi",
        auth=server.EtapiTokenAuth(),
        transport=httpx.MockTransport(handler),
    )


def test_build_server_needs_no_token_and_builds_tools():
    mcp = server.build_server()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert len(tools) >= 30
    assert "createNote" in names


def test_instructions_unset_by_default(monkeypatch):
    monkeypatch.delenv("MCP_INSTRUCTIONS", raising=False)
    assert server.build_server().instructions is None


def test_instructions_come_from_env(monkeypatch):
    monkeypatch.setenv("MCP_INSTRUCTIONS", "  Always answer in German.\n")
    assert server.build_server().instructions == "Always answer in German."


def test_blank_instructions_count_as_unset(monkeypatch):
    monkeypatch.setenv("MCP_INSTRUCTIONS", "   ")
    assert server.build_server().instructions is None


def test_createnote_with_null_prefix_does_not_error():
    from fastmcp import Client

    async def run():
        reset = server._incoming_auth.set("Bearer test-token")
        try:
            mcp = server.build_server(client=_mock_client())
            async with Client(mcp) as c:
                return await c.call_tool("createNote", {
                    "parentNoteId": "root", "title": "t",
                    "type": "text", "content": "c",
                })
        finally:
            server._incoming_auth.reset(reset)

    # Must NOT raise ToolError("Output validation error: None is not of type 'string'").
    result = asyncio.run(run())
    assert result is not None


def test_export_subtree_returns_readable_text_from_zip():
    from fastmcp import Client

    zip_payload = _zip_bytes({
        "Root Note.md": b"# Root Note\n\nHello world.",
        "Root Note/Child.md": b"# Child\n\nNested content.",
        "Root Note/image.png": b"\x89PNG\r\n\x1a\n\x8e\x00binary",  # non-UTF-8
    })

    async def run():
        reset = server._incoming_auth.set("Bearer test-token")
        try:
            mcp = server.build_server(client=_export_client(zip_payload))
            async with Client(mcp) as c:
                return await c.call_tool("exportNoteSubtree", {"noteId": "root"})
        finally:
            server._incoming_auth.reset(reset)

    # The generated tool would crash with UnicodeDecodeError on the ZIP bytes.
    result = asyncio.run(run())
    text = result.content[0].text
    assert "Hello world." in text
    assert "Nested content." in text
    # Binary entries are listed, not inlined.
    assert "image.png" in text
    assert "\x89PNG" not in text


def test_export_subtree_replaces_generated_tool_exactly_once():
    mcp = server.build_server()
    tools = asyncio.run(mcp.list_tools())
    names = [t.name for t in tools]
    assert names.count("exportNoteSubtree") == 1


def test_content_put_tools_registered_exactly_once():
    mcp = server.build_server()
    names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert names.count("putNoteContentById") == 1
    assert names.count("putAttachmentContentById") == 1


def test_auth_session_tools_are_excluded():
    # login/logout manage ETAPI session tokens and must not be exposed as MCP
    # tools: an LLM authenticates via the Authorization header, and logout would
    # invalidate its own credential.
    mcp = server.build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "login" not in names
    assert "logout" not in names


def test_get_note_content_html_passes_through():
    from fastmcp import Client

    async def run():
        reset = server._incoming_auth.set("Bearer test-token")
        try:
            mcp = server.build_server(client=_content_client(b"<p>hello</p>"))
            async with Client(mcp) as c:
                return await c.call_tool("getNoteContent", {"noteId": "abc123"})
        finally:
            server._incoming_auth.reset(reset)

    # Before the fix this raised "outputSchema defined but no structured output
    # returned" because the text/html response carried no structured content.
    result = asyncio.run(run())
    assert result.content[0].text == "<p>hello</p>"


def test_put_note_content_sends_text_plain_body():
    from fastmcp import Client

    captured: dict = {}

    async def run():
        reset = server._incoming_auth.set("Bearer test-token")
        try:
            mcp = server.build_server(client=_capture_put_content_client(captured))
            async with Client(mcp) as c:
                return await c.call_tool(
                    "putNoteContentById", {"noteId": "abc123", "content": "hello body"}
                )
        finally:
            server._incoming_auth.reset(reset)

    # Before the fix Trilium got no parsable body (no Content-Type). Now the raw
    # text is forwarded with an explicit text/plain Content-Type.
    result = asyncio.run(run())
    assert result.is_error is False
    assert captured["body"] == b"hello body"
    assert captured["content_type"].startswith("text/plain")

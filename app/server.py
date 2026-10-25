# SPDX-License-Identifier: AGPL-3.0-or-later
#
# trilium-mcp — Standalone MCP server exposing the Trilium ETAPI over HTTP.
# Copyright (C) 2026 Marcel Bruckner
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

import copy
import io
import json
import os
import re
import sys
import traceback
import zipfile
from contextvars import ContextVar
from pathlib import Path

import httpx2
import uvicorn
import yaml
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.providers.openapi import MCPType, OpenAPITool, RouteMap
from key_value.aio.protocols import AsyncKeyValue
from mcp.server.auth.routes import validate_issuer_url
from mcp_login_oauth import (
    BearerPrefixMiddleware,
    LoginField,
    LoginOAuthProvider,
    LoginRejected,
    build_store,
)
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

# The ETAPI OpenAPI spec ships alongside this server (baked into the image).
# Tools are generated from it at startup.
DEFAULT_SPEC = Path(__file__).parent / "trilium-etapi.openapi"

# All configuration comes from the environment so the server runs cleanly as a
# container sidecar with no command-line arguments.
SERVER_ENV = "TRILIUM_SERVER_URL"          # Base URL of the Trilium instance
SPEC_ENV = "TRILIUM_ETAPI_SPEC"            # Override path to the OpenAPI spec
MCP_HOST_ENV = "MCP_HOST"                  # Interface the MCP server binds to
MCP_PORT_ENV = "MCP_PORT"                  # Port the MCP server listens on
MCP_PATH_ENV = "MCP_PATH"                  # HTTP path the MCP endpoint is served at
MCP_ALLOWED_HOSTS_ENV = "MCP_ALLOWED_HOSTS"  # comma-separated Host allowlist (see serve)
AUTH_MODE_ENV = "MCP_AUTH_MODE"            # token | oauth | both (see resolve_auth_mode)
BASE_URL_ENV = "MCP_BASE_URL"              # public URL clients reach us at (OAuth issuer)
OAUTH_SECRET_ENV = "MCP_OAUTH_SECRET"      # encrypts the OAuth store at rest
CHATGPT_ENV = "CHATGPT_ACTIONS"            # true -> serve a Custom GPT Action (see register_chatgpt_routes)
INSTRUCTIONS_ENV = "MCP_INSTRUCTIONS"      # optional standing instructions sent to every MCP client

DEFAULT_SERVER_URL = "http://trilium:8080"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8081
DEFAULT_PATH = "/mcp"
HEALTH_PATH = "/health"
AUTH_MODES = ("token", "oauth", "both")
OAUTH_STORE_DIR = Path("/data/oauth")      # mount a volume at /data to keep logins

# ChatGPT Custom GPT Action (see register_chatgpt_routes). A GPT Action takes at
# most 30 operations and 300-character descriptions; the full spec minus
# CHATGPT_DROP is exactly 30.
CHATGPT_SPEC_PATH = "/chatgpt/openapi.json"
CHATGPT_PROXY_PREFIX = "/chatgpt/etapi"
CHATGPT_DROP = {
    "login", "logout", "exportNoteSubtree", "importZip",
    "postAttachment", "getAttachmentById", "patchAttachmentById",
    "deleteAttachmentById", "getAttachmentContent", "putAttachmentContentById",
}
CHATGPT_MAX_DESCRIPTION = 300
CHATGPT_NOTE_CONTENT = "/notes/{noteId}/content"

# exportNoteSubtree returns a binary ZIP, which FastMCP's OpenAPI machinery
# tries to JSON-decode (crashing on the first non-UTF-8 byte). We exclude the
# generated tool and register a replacement that unpacks the ZIP into text.
EXPORT_FORMATS = ("markdown", "html")
EXPORT_DEFAULT_FORMAT = "markdown"
# Cap the returned text so a huge subtree can't blow up the client context.
MAX_EXPORT_CHARS = 200_000

# OAuth (see build_oauth_provider). Issued codes/tokens carry this prefix so a
# stale one is recognizably ours and is never mistaken for a raw ETAPI token.
OAUTH_TOKEN_PREFIX = "tmcp_"
# Salt of the encrypted store. "-v2" since mcp-login-oauth: entries written by the
# old in-repo provider have another shape, so they must decrypt to misses (clients
# log in again) rather than be read.
OAUTH_STORE_SALT = "trilium-mcp-oauth-v2"

# Per-request holder for the incoming client Authorization header. Populated by
# TokenCaptureMiddleware and read by EtapiTokenAuth when calling Trilium.
_incoming_auth: ContextVar[str | None] = ContextVar("incoming_auth", default=None)


class EtapiTokenAuth(httpx2.Auth):
    """Forward the client's ETAPI token to Trilium.

    With OAuth (see build_oauth_provider), FastMCP's request-scoped access token
    carries the login's grant, `{"etapi_token": ...}`, in `claims["grant"]`. Otherwise the token is
    the raw client header in the `_incoming_auth` contextvar (set by
    TokenCaptureMiddleware). Trilium's ETAPI expects the raw token as the
    Authorization value, so we strip a leading 'Bearer ' if the client sent one.
    """

    def auth_flow(self, request: httpx2.Request):
        access = get_access_token()
        raw = access.claims["grant"]["etapi_token"] if access else _incoming_auth.get()
        if raw and raw[:7].lower() == "bearer ":
            raw = raw[7:].strip()
        if not raw:
            raise RuntimeError(
                "No client Authorization header available for the ETAPI call."
            )
        request.headers["Authorization"] = raw
        yield request


class TokenCaptureMiddleware:
    """Pure-ASGI middleware that requires a client Authorization header on the
    MCP endpoint and stashes it for the outgoing ETAPI call.

    The token IS the auth: a request without one is rejected with 401 before it
    reaches FastMCP; validity is enforced by Trilium on the actual ETAPI call.
    The health check and the (public) ChatGPT Action spec are always allowed.
    Implemented at the ASGI layer (not BaseHTTPMiddleware) so it does not buffer
    the streamable-HTTP response.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Forward lifespan / websocket scopes untouched.
            await self.app(scope, receive, send)
            return
        if scope.get("path") in (HEALTH_PATH, CHATGPT_SPEC_PATH):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        authorization = headers.get(b"authorization", b"").decode()
        if not authorization:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error":"missing Authorization header"}',
            })
            return
        token = _incoming_auth.set(authorization)
        try:
            await self.app(scope, receive, send)
        finally:
            _incoming_auth.reset(token)


def load_spec(spec_path: Path) -> dict:
    """Parse the on-disk ETAPI OpenAPI spec into a dict.

    The spec ships as YAML; because YAML is a superset of JSON this also parses
    a JSON spec, so the file can be swapped for either format.
    """
    if not spec_path.exists():
        raise RuntimeError(f"OpenAPI spec not found at {spec_path}.")
    text = spec_path.read_text()
    if not text.strip():
        raise RuntimeError(
            f"OpenAPI spec at {spec_path} is empty -- populate it with the "
            f"Trilium ETAPI OpenAPI spec."
        )
    spec = yaml.safe_load(text)
    if not isinstance(spec, dict):
        raise RuntimeError(f"OpenAPI spec at {spec_path} is not a valid mapping.")
    return spec


def register_health(mcp: FastMCP) -> None:
    """Add an unauthenticated health endpoint for container healthchecks."""

    @mcp.custom_route(HEALTH_PATH, methods=["GET"])
    async def health(_request: Request):
        return PlainTextResponse("ok")


def drop_non_json_output_schema(route, component) -> None:
    """Clear the output schema on tools whose ETAPI response isn't JSON.

    Endpoints like getNoteContent return text/html, so the generated tool returns
    plain text with no structured content. FastMCP still attaches an output
    schema, and the MCP layer then rejects the call with "outputSchema defined
    but no structured output returned". Dropping the schema lets those text
    responses pass through. Applied via mcp_component_fn (see build_server).
    """
    if not isinstance(component, OpenAPITool):
        return
    content_types: list[str] = []
    for status, info in route.responses.items():
        # Only the success (2xx) responses decide the real output shape; the
        # "default" error response is always JSON and must not be counted.
        if status[:1] == "2":
            content_types.extend(info.content_schema)
    if not any("json" in ct.lower() for ct in content_types):
        component.output_schema = None


def register_export_tool(mcp: FastMCP, client: httpx2.AsyncClient) -> None:
    """Register a working replacement for the generated exportNoteSubtree tool.

    Trilium's `/notes/{noteId}/export` returns a binary ZIP archive. FastMCP's
    OpenAPI-generated tool tries to `response.json()` every response and only
    catches `json.JSONDecodeError`, so a ZIP body raises an uncaught
    `UnicodeDecodeError` and the tool crashes. Here we fetch the ZIP ourselves,
    unpack it, and return the notes as readable text so an LLM can answer
    questions about the subtree. The `client` carries the same per-request ETAPI
    auth as the generated tools (see EtapiTokenAuth).
    """

    @mcp.tool(name="exportNoteSubtree")
    async def export_note_subtree(noteId: str, format: str = EXPORT_DEFAULT_FORMAT) -> str:
        """Export a note and its entire subtree as readable text.

        Fetches Trilium's ZIP export of the subtree rooted at `noteId` (use
        "root" for the whole document), unpacks it, and returns each note's path
        followed by its text content. `format` is "markdown" (default, most
        readable) or "html". Binary files in the export (images, attachments)
        are listed by name but not inlined.
        """
        fmt = format.lower()
        if fmt not in EXPORT_FORMATS:
            raise ValueError(
                f"Unsupported format {format!r}; use one of {', '.join(EXPORT_FORMATS)}."
            )
        response = await client.get(f"/notes/{noteId}/export", params={"format": fmt})
        response.raise_for_status()

        try:
            archive = zipfile.ZipFile(io.BytesIO(response.content))
        except zipfile.BadZipFile as e:
            raise ValueError(
                f"Trilium did not return a valid ZIP export for note {noteId!r}: {e}"
            ) from e

        sections: list[str] = []
        binaries: list[str] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            try:
                text = archive.read(info).decode("utf-8")
            except UnicodeDecodeError:
                binaries.append(f"{info.filename} ({info.file_size} bytes)")
                continue
            sections.append(f"===== {info.filename} =====\n{text}")

        out = (
            f"Exported subtree of note {noteId!r} (format: {fmt}); "
            f"{len(sections)} text file(s).\n\n" + "\n\n".join(sections)
        )
        if binaries:
            out += "\n\n[binary files not shown: " + ", ".join(binaries) + "]"
        if len(out) > MAX_EXPORT_CHARS:
            out = out[:MAX_EXPORT_CHARS] + f"\n\n[truncated at {MAX_EXPORT_CHARS} characters]"
        return out


def register_content_put_tools(mcp: FastMCP, client: httpx2.AsyncClient) -> None:
    """Register working replacements for the two text/plain PUT-content tools.

    The `/notes/{id}/content` and `/attachments/{id}/content` PUT endpoints take
    a raw text/plain body. FastMCP's request director sets a scalar body as httpx
    `content` but never adds a Content-Type header (see the final `else: content =
    body` branch in fastmcp/utilities/openapi/director.py), so Trilium receives no
    parsable body and rejects the update with 500 "Cannot set null content". We
    send the raw body with an explicit text/plain Content-Type instead. The
    `client` carries the same per-request ETAPI auth as the generated tools.
    """

    @mcp.tool(name="putNoteContentById")
    async def put_note_content(noteId: str, content: str) -> str:
        """Update the content of a note (raw text/plain body)."""
        response = await client.put(
            f"/notes/{noteId}/content",
            content=content.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        response.raise_for_status()
        return f"Updated content of note {noteId!r}."

    @mcp.tool(name="putAttachmentContentById")
    async def put_attachment_content(attachmentId: str, content: str) -> str:
        """Update the content of an attachment (raw text/plain body)."""
        response = await client.put(
            f"/attachments/{attachmentId}/content",
            content=content.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        response.raise_for_status()
        return f"Updated content of attachment {attachmentId!r}."


def chatgpt_spec(spec: dict, base_url: str) -> dict:
    """The ETAPI spec trimmed to what a ChatGPT Custom GPT Action accepts,
    pointed at this server's proxy (see register_chatgpt_routes).

    putNoteContentById's text/plain body becomes JSON `{"content": ...}`: GPT
    Actions send JSON bodies, and the proxy turns it back into text/plain.
    """
    out = copy.deepcopy(spec)
    out["servers"] = [{"url": base_url + CHATGPT_PROXY_PREFIX}]
    out["security"] = [{"EtapiTokenAuth": []}]
    for path, item in list(out["paths"].items()):
        for method, op in list(item.items()):
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            if op["operationId"] in CHATGPT_DROP:
                del item[method]
            elif "description" in op:
                op["description"] = op["description"][:CHATGPT_MAX_DESCRIPTION]
        if not any(isinstance(op, dict) and "operationId" in op for op in item.values()):
            del out["paths"][path]
    out["paths"][CHATGPT_NOTE_CONTENT]["put"]["requestBody"] = {
        "required": True,
        "content": {"application/json": {"schema": {
            "type": "object",
            "required": ["content"],
            "properties": {"content": {
                "type": "string", "description": "New note content (HTML for text notes).",
            }},
        }}},
    }
    return out


def register_chatgpt_routes(
    mcp: FastMCP, client: httpx2.AsyncClient, spec: dict, base_url: str
) -> None:
    """Serve a ChatGPT Custom GPT Action: the trimmed spec at CHATGPT_SPEC_PATH
    and a REST proxy to ETAPI under CHATGPT_PROXY_PREFIX.

    ChatGPT's Android app can't use MCP servers yet, but it can use a Custom
    GPT's Actions (plain REST + OpenAPI). The proxy forwards only the spec's
    operations -- notably not ETAPI's unauthenticated /auth/login -- through
    `client`, so the token is handled exactly as for MCP tool calls
    (TokenCaptureMiddleware / OAuth -> EtapiTokenAuth).
    """
    action_spec = chatgpt_spec(spec, base_url)
    # Dates in the YAML examples parse as date objects; JSON needs strings.
    spec_json = json.dumps(action_spec, default=str)
    allowed = [
        (method.upper(), re.compile(re.sub(r"\{[^}]+\}", "[^/]+", path)))
        for path, item in action_spec["paths"].items()
        for method, op in item.items()
        if isinstance(op, dict) and "operationId" in op
    ]
    note_content = re.compile(re.sub(r"\{[^}]+\}", "[^/]+", CHATGPT_NOTE_CONTENT))

    @mcp.custom_route(CHATGPT_SPEC_PATH, methods=["GET"])
    async def chatgpt_openapi(_request: Request):
        return Response(spec_json, media_type="application/json")

    @mcp.custom_route(
        CHATGPT_PROXY_PREFIX + "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def chatgpt_proxy(request: Request):
        path = "/" + request.path_params["path"]
        if not any(m == request.method and r.fullmatch(path) for m, r in allowed):
            return JSONResponse({"error": "not available to ChatGPT"}, status_code=404)
        body = await request.body()
        headers = {"Content-Type": request.headers.get("content-type", "application/json")}
        if request.method == "PUT" and note_content.fullmatch(path):
            try:
                body = json.loads(body)["content"].encode("utf-8")
            except (ValueError, KeyError, TypeError, AttributeError):
                return JSONResponse(
                    {"error": 'body must be JSON {"content": "<text>"}'}, status_code=400
                )
            headers = {"Content-Type": "text/plain; charset=utf-8"}
        try:
            response = await client.request(
                request.method, path,
                params=list(request.query_params.multi_items()),
                content=body or None,
                headers=headers if body else None,
            )
        except RuntimeError:  # EtapiTokenAuth found no usable token
            return JSONResponse({"error": "missing or invalid Authorization"}, status_code=401)
        return Response(
            response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )


def etapi_url() -> str:
    """TRILIUM_SERVER_URL with `/etapi` appended (see the spec's `servers`)."""
    server_url = os.environ.get(SERVER_ENV, DEFAULT_SERVER_URL).rstrip("/")
    return server_url if server_url.endswith("/etapi") else f"{server_url}/etapi"


def resolve_auth_mode() -> str:
    """Pick token / oauth / both from the environment.

    Unset MCP_AUTH_MODE means `both` when OAuth is configured, else `token` with
    a warning -- so an existing deployment keeps working after an image update.
    An explicit oauth/both without its config is an error (-> startup_error).
    """
    mode = os.environ.get(AUTH_MODE_ENV, "").strip().lower()
    missing = [
        v for v in (BASE_URL_ENV, OAUTH_SECRET_ENV) if not os.environ.get(v, "").strip()
    ]
    if not mode:
        if missing:
            print(f"OAuth disabled: {' and '.join(missing)} not set; accepting raw "
                  f"ETAPI tokens only.", file=sys.stderr)
            return "token"
        return "both"
    if mode not in AUTH_MODES:
        raise RuntimeError(
            f"{AUTH_MODE_ENV}={mode!r} is invalid; use one of {', '.join(AUTH_MODES)}."
        )
    if mode != "token" and missing:
        raise RuntimeError(f"{AUTH_MODE_ENV}={mode} requires {' and '.join(missing)}.")
    return mode


def build_oauth_provider(
    mode: str,
    etapi: httpx2.AsyncClient | None = None,
    store: AsyncKeyValue | None = None,
) -> LoginOAuthProvider:
    """OAuth whose login is the Trilium password (mcp-login-oauth).

    The password goes to ETAPI /auth/login, which mints a fresh ETAPI token; that
    token is the login's grant, `{"etapi_token": ...}`, read by EtapiTokenAuth.
    Revoking logs it out of Trilium again. In `both` mode a bearer that isn't one
    of ours is forwarded as a raw ETAPI token, exactly as in `token` mode; Trilium
    judges it. `etapi` (unauthenticated: only login and logout) and `store` are
    injectable for testing.
    """
    base_url = os.environ[BASE_URL_ENV].strip().rstrip("/")
    try:
        validate_issuer_url(AnyHttpUrl(base_url))
    except ValueError as e:
        raise RuntimeError(
            f"{BASE_URL_ENV}={base_url!r} is not a valid OAuth issuer: {e} "
            f"(plain http is only allowed for localhost)."
        ) from e
    if store is None:
        store = build_store(OAUTH_STORE_DIR, os.environ[OAUTH_SECRET_ENV], OAUTH_STORE_SALT)
    if etapi is None:
        etapi = httpx2.AsyncClient(base_url=etapi_url(), timeout=60)

    async def check_login(form) -> dict:
        # The password goes straight to Trilium and is never stored or logged.
        response = await etapi.post("/auth/login", json={"password": form["password"]})
        if not response.is_success:
            raise LoginRejected(f"Trilium rejected the login (HTTP {response.status_code}).")
        return {"etapi_token": response.json()["authToken"]}

    async def on_revoke(grant: dict) -> None:
        await etapi.post("/auth/logout", headers={"Authorization": grant["etapi_token"]})

    async def verify_static(token: str) -> dict:
        return {"etapi_token": token}

    return LoginOAuthProvider(
        base_url=base_url,
        store=store,
        service_name="Trilium Notes",
        fields=[LoginField("password", "Trilium password", type="password",
                           required=True, autocomplete="current-password")],
        check_login=check_login,
        on_revoke=on_revoke,
        verify_static=verify_static if mode == "both" else None,
        token_prefix=OAUTH_TOKEN_PREFIX,
    )


def build_server(
    client: httpx2.AsyncClient | None = None,
    auth: LoginOAuthProvider | None = None,
) -> FastMCP:
    """Load the local OpenAPI spec and turn every documented ETAPI endpoint
    into a FastMCP tool. The ETAPI token is supplied per request by the client
    (see TokenCaptureMiddleware / EtapiTokenAuth), so no token is read here.

    `client` is injectable for testing; in production the default client targets
    TRILIUM_SERVER_URL and authenticates from the per-request token. `auth`
    enables OAuth (see build_oauth_provider); None keeps plain token pass-through.
    """
    if client is None:
        client = httpx2.AsyncClient(
            base_url=etapi_url(), auth=EtapiTokenAuth(), timeout=60
        )

    spec_path = Path(os.environ.get(SPEC_ENV, str(DEFAULT_SPEC)))
    spec = load_spec(spec_path)

    # Several ETAPI endpoints don't fit FastMCP's JSON-in/JSON-out assumption,
    # and they need different fixes because they fail at different layers:
    #
    #   * text/html RESPONSES (getNoteContent, ...) -- a *metadata* problem.
    #     FastMCP's tool already returns the right thing (response.json() raises
    #     the *caught* JSONDecodeError, so it falls back to returning the text
    #     body); it just leaves an output schema attached that the MCP layer then
    #     rejects. Fixable by clearing the schema -> mcp_component_fn.
    #   * application/zip RESPONSE (exportNoteSubtree) -- a *behavior* problem.
    #     The ZIP bytes make response.json() raise an *uncaught* UnicodeDecodeError,
    #     so the tool crashes before any schema is consulted; and raw bytes are
    #     useless to a client anyway. Needs real logic (fetch + unzip), so we
    #     exclude the generated tool and replace it -> register_export_tool.
    #   * text/plain REQUEST bodies (putNoteContentById, putAttachmentContentById)
    #     -- a *behavior* problem on the request side. FastMCP's director sends a
    #     scalar text/plain body with no Content-Type header, so Trilium receives
    #     no parsable body and 500s. Needs a real request, so we exclude the
    #     generated tools and replace them -> register_content_put_tools.
    #
    # mcp_component_fn can only adjust component metadata, so it can't fix the
    # behavior cases; that's why they are handled by exclusion + replacement.
    #
    # Separately, the /auth/login and /auth/logout endpoints are excluded outright
    # (not replaced): they manage ETAPI session tokens, but an MCP client already
    # authenticates with the token in the Authorization header. An LLM has no
    # reason to mint a token from a password (login) and calling logout would
    # invalidate its own credential -- so neither belongs on the tool surface.
    # Operator-supplied house rules, delivered in the MCP initialize response
    # (clients such as Claude Code and claude.ai put them in the system prompt).
    # Deliberately no default: the server has no opinion about how notes are
    # used; see docs/configuration.md for examples.
    instructions = os.environ.get(INSTRUCTIONS_ENV, "").strip() or None

    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="Trilium ETAPI MCP",
        instructions=instructions,
        auth=auth,
        # The live ETAPI returns null for fields the spec types as plain
        # strings (e.g. branch.prefix), so response validation would reject
        # otherwise-successful calls. Return the real response instead.
        validate_output=False,
        # Behavior fixes: drop the generated tools whose bodies/responses FastMCP
        # mishandles (see above); the register_* calls below replace them.
        # Plus: drop auth session-token endpoints outright (see above) -- not
        # useful, and logout is a footgun for a token-authenticated client.
        route_maps=[
            RouteMap(methods=["GET"], pattern=r"/export$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods=["PUT"], pattern=r"/content$", mcp_type=MCPType.EXCLUDE),
            RouteMap(
                methods=["POST"],
                pattern=r"/auth/(login|logout)$",
                mcp_type=MCPType.EXCLUDE,
            ),
        ],
        # Metadata fix: clear the output schema on non-JSON tools (see above).
        mcp_component_fn=drop_non_json_output_schema,
    )
    register_export_tool(mcp, client)
    register_content_put_tools(mcp, client)
    register_health(mcp)
    if os.environ.get(CHATGPT_ENV, "").strip().lower() in ("1", "true", "yes"):
        base_url = os.environ.get(BASE_URL_ENV, "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError(f"{CHATGPT_ENV} requires {BASE_URL_ENV} (the public URL).")
        register_chatgpt_routes(mcp, client, spec, base_url)
    return mcp


def build_error_server(error: BaseException) -> FastMCP:
    """Stand-in MCP server that reports a startup failure over a live
    connection instead of dying with an opaque error. Reached if the bundled
    OpenAPI spec is missing/unparseable or the auth configuration is invalid.
    """
    summary = str(error).strip() or error.__class__.__name__
    detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).strip()
    instructions = (
        f"This Trilium ETAPI MCP server FAILED TO START and exposes no Trilium "
        f"tools.\n\nReason: {summary}\n\nFix the configuration or bundled OpenAPI "
        f"spec and restart. Call the `startup_error` tool for the full error."
    )
    mcp = FastMCP(
        name="Trilium ETAPI MCP (startup failed)",
        instructions=instructions,
    )
    register_health(mcp)

    @mcp.tool
    def startup_error() -> str:
        """Explain why this Trilium ETAPI MCP server failed to start."""
        return (
            "The Trilium ETAPI MCP server failed to start, so no Trilium tools "
            f"are available.\n\n--- Full error ---\n{detail}"
        )

    return mcp


def wrap_app(inner, mode: str):
    """Put the auth-mode's ASGI gate in front of FastMCP's app."""
    if mode == "token":
        return TokenCaptureMiddleware(inner)
    if mode == "both":
        return BearerPrefixMiddleware(inner)
    return inner


def serve(mcp: FastMCP, mode: str = "token") -> None:
    """Serve an MCP server over streamable HTTP using the MCP_* environment
    configuration. In `token` mode TokenCaptureMiddleware gates the endpoint;
    otherwise FastMCP's OAuth middleware does (see build_oauth_provider)."""
    host = os.environ.get(MCP_HOST_ENV, DEFAULT_HOST)
    port = int(os.environ.get(MCP_PORT_ENV, DEFAULT_PORT))
    path = os.environ.get(MCP_PATH_ENV, DEFAULT_PATH)

    # FastMCP's streamable-HTTP transport does DNS-rebinding protection: by
    # default it 421s any Host header that isn't localhost. This server is meant
    # to be reached by LAN IP or (behind a reverse proxy) a public domain, and
    # the ETAPI token is the real gate -- so leave the Host allowlist open by
    # default and only restrict when MCP_ALLOWED_HOSTS is set.
    allowed = os.environ.get(MCP_ALLOWED_HOSTS_ENV, "").strip()
    if allowed:
        hosts = [h.strip() for h in allowed.split(",") if h.strip()]
        inner = mcp.http_app(path=path, allowed_hosts=hosts)
        print(f"Host protection ON; allowed hosts (plus localhost): {hosts}",
              file=sys.stderr)
    else:
        inner = mcp.http_app(path=path, host_origin_protection=False)
        print(f"Host protection OFF (any Host accepted) -- set "
              f"{MCP_ALLOWED_HOSTS_ENV} to restrict.", file=sys.stderr)
    app = wrap_app(inner, mode)

    print(f"Serving Trilium ETAPI MCP on http://{host}:{port}{path} "
          f"(auth mode: {mode})",
          file=sys.stderr)
    uvicorn.run(app, host=host, port=port)


def main():
    mode = "token"
    try:
        mode = resolve_auth_mode()
        auth = None if mode == "token" else build_oauth_provider(mode)
        mcp = build_server(auth=auth)
    except Exception as e:
        print(f"Error: failed to build Trilium ETAPI MCP server: {e}",
              file=sys.stderr)
        mode = "token"
        mcp = build_error_server(e)
    serve(mcp, mode)


if __name__ == "__main__":
    main()

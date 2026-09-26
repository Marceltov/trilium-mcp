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

import html
import io
import os
import secrets
import sys
import time
import traceback
import zipfile
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
import yaml
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, OAuthProvider
from fastmcp.server.auth.auth import ClientRegistrationOptions, RevocationOptions
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.providers.openapi import MCPType, OpenAPITool, RouteMap
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import validate_issuer_url
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

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

DEFAULT_SERVER_URL = "http://trilium:8080"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8081
DEFAULT_PATH = "/mcp"
HEALTH_PATH = "/health"
AUTH_MODES = ("token", "oauth", "both")
OAUTH_STORE_DIR = Path("/data/oauth")      # mount a volume at /data to keep logins

# exportNoteSubtree returns a binary ZIP, which FastMCP's OpenAPI machinery
# tries to JSON-decode (crashing on the first non-UTF-8 byte). We exclude the
# generated tool and register a replacement that unpacks the ZIP into text.
EXPORT_FORMATS = ("markdown", "html")
EXPORT_DEFAULT_FORMAT = "markdown"
# Cap the returned text so a huge subtree can't blow up the client context.
MAX_EXPORT_CHARS = 200_000

# OAuth (see TriliumOAuthProvider). Issued codes/tokens carry this prefix so a
# stale one is recognizably ours and is never mistaken for a raw ETAPI token.
OAUTH_TOKEN_PREFIX = "tmcp_"
PENDING_LOGIN_TTL = 10 * 60
AUTH_CODE_TTL = 5 * 60
ACCESS_TOKEN_TTL = 60 * 60
REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60

# Per-request holder for the incoming client Authorization header. Populated by
# TokenCaptureMiddleware and read by EtapiTokenAuth when calling Trilium.
_incoming_auth: ContextVar[str | None] = ContextVar("incoming_auth", default=None)


class EtapiTokenAuth(httpx.Auth):
    """Forward the client's ETAPI token to Trilium.

    With OAuth (see TriliumOAuthProvider), FastMCP's request-scoped access token
    carries the ETAPI token in `claims["etapi_token"]`. Otherwise the token is
    the raw client header in the `_incoming_auth` contextvar (set by
    TokenCaptureMiddleware). Trilium's ETAPI expects the raw token as the
    Authorization value, so we strip a leading 'Bearer ' if the client sent one.
    """

    def auth_flow(self, request: httpx.Request):
        access = get_access_token()
        raw = access.claims.get("etapi_token") if access else _incoming_auth.get()
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
    Implemented at the ASGI layer (not BaseHTTPMiddleware) so it does not buffer
    the streamable-HTTP response. The health check is always allowed.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Forward lifespan / websocket scopes untouched.
            await self.app(scope, receive, send)
            return
        if scope.get("path") == HEALTH_PATH:
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


def _login_page(pending_id="", client_name="", redirect_host="", error="", status=200):
    """The one page a human sees: who is asking, where the code goes, password."""
    e = html.escape
    form = "" if not pending_id else (
        f"<p><b>{e(client_name)}</b> wants access to your Trilium notes. After "
        f"login you will be sent to <b>{e(redirect_host)}</b>. Only continue if "
        f"you started this.</p>"
        f'<form method="post"><input type="hidden" name="id" value="{e(pending_id)}">'
        f'<label>Trilium password <input type="password" name="password" '
        f"autofocus required></label><button>Authorize</button></form>"
    )
    err = f'<p style="color:#b00">{e(error)}</p>' if error else ""
    body = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Trilium MCP login</title><style>body{font-family:system-ui,"
        "sans-serif;max-width:28rem;margin:4rem auto;padding:0 1rem}input,button"
        "{font:inherit;padding:.4rem;margin:.3rem 0;width:100%;box-sizing:"
        f"border-box}}</style></head><body><h1>Trilium MCP</h1>{err}{form}"
        "</body></html>"
    )
    # DENY framing so the password form can't be clickjacked.
    return HTMLResponse(body, status_code=status, headers={"X-Frame-Options": "DENY"})


class TriliumOAuthProvider(OAuthProvider):
    """OAuth 2.1 authorization server whose login is the Trilium password.

    FastMCP/the MCP SDK serve discovery, dynamic client registration,
    /authorize, /token (PKCE) and /revoke on top of these methods. Logging in
    mints a fresh ETAPI token via ETAPI /auth/login; every code and token we
    issue maps to it, and verify_token hands it to EtapiTokenAuth through the
    access token's `etapi_token` claim.

    `passthrough` is `both` mode: a bearer that isn't one of ours is forwarded
    to Trilium as a raw ETAPI token, exactly as in `token` mode.
    """

    def __init__(
        self,
        *,
        base_url: str,
        store: AsyncKeyValue,
        etapi: httpx.AsyncClient,
        passthrough: bool,
    ):
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        self.store = store
        self.etapi = etapi  # unauthenticated: only /auth/login and /auth/logout
        self.passthrough = passthrough

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = await self.store.get(client_id, collection="clients")
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self.store.put(
            client_info.client_id,
            client_info.model_dump(mode="json"),
            collection="clients",
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        pending_id = secrets.token_urlsafe(32)
        await self.store.put(
            pending_id,
            {"client_id": client.client_id, "params": params.model_dump(mode="json")},
            collection="pending",
            ttl=PENDING_LOGIN_TTL,
        )
        return f"{str(self.base_url).rstrip('/')}/login?id={pending_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        data = await self.store.get(authorization_code, collection="codes")
        if not data or data["code"]["client_id"] != client.client_id:
            return None
        return AuthorizationCode.model_validate(data["code"])

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        data = await self.store.get(authorization_code.code, collection="codes")
        if not data:
            raise TokenError("invalid_grant", "Authorization code not found or already used.")
        await self.store.delete(authorization_code.code, collection="codes")
        return await self._issue(
            client.client_id, authorization_code.scopes, data["etapi_token"]
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        data = await self.store.get(refresh_token, collection="refresh")
        if not data or data["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=data["client_id"],
            scopes=data["scopes"],
            expires_at=data["expires_at"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        data = await self.store.get(refresh_token.token, collection="refresh")
        if not data:
            raise TokenError("invalid_grant", "Refresh token not found or already used.")
        if not set(scopes) <= set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Requested scopes exceed the original grant.")
        # Rotate: the old pair dies, the minted ETAPI token lives on in the new one.
        await self._drop(data["access"], refresh_token.token)
        return await self._issue(
            client.client_id, scopes or refresh_token.scopes, data["etapi_token"]
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = await self.store.get(token, collection="access")
        if not data:
            return None
        return AccessToken(
            token=token,
            client_id=data["client_id"],
            scopes=data["scopes"],
            expires_at=data["expires_at"],
            claims={"etapi_token": data["etapi_token"]},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        found = await self.load_access_token(token)
        if found or not self.passthrough or token.startswith(OAUTH_TOKEN_PREFIX):
            return found
        # `both` mode: not ours, so it's a raw ETAPI token; Trilium judges it.
        return AccessToken(
            token=token, client_id="etapi-token", scopes=[],
            claims={"etapi_token": token},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            data = await self.store.get(token.token, collection="refresh")
            pair = (data["access"], token.token) if data else None
        else:
            data = await self.store.get(token.token, collection="access")
            pair = (token.token, data["refresh"]) if data else None
        if not pair:
            return
        await self._drop(*pair)
        # Also delete the minted ETAPI token in Trilium. Best effort: the OAuth
        # pair is already gone, so a failure here only leaves a stray token.
        try:
            await self.etapi.post(
                "/auth/logout", headers={"Authorization": data["etapi_token"]}
            )
        except httpx.HTTPError:
            pass

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        return [
            *super().get_routes(mcp_path),
            Route("/login", self._login, methods=["GET", "POST"]),
        ]

    async def _login(self, request: Request):
        form = await request.form() if request.method == "POST" else request.query_params
        pending_id = form.get("id", "")
        pending = (
            await self.store.get(pending_id, collection="pending") if pending_id else None
        )
        if not pending:
            return _login_page(
                error="This login link has expired. Start the connection again "
                "from your MCP client.",
                status=400,
            )
        params = AuthorizationParams.model_validate(pending["params"])
        client = await self.get_client(pending["client_id"])
        client_name = (client.client_name if client else None) or pending["client_id"]
        redirect = str(params.redirect_uri)
        page = (pending_id, client_name, urlsplit(redirect).netloc or redirect)
        if request.method == "GET":
            return _login_page(*page)

        # The password goes straight to Trilium and is never stored or logged.
        response = await self.etapi.post(
            "/auth/login", json={"password": form.get("password", "")}
        )
        if not response.is_success:
            return _login_page(
                *page,
                error=f"Trilium rejected the login (HTTP {response.status_code}).",
                status=401,
            )
        await self.store.delete(pending_id, collection="pending")
        code = AuthorizationCode(
            code=OAUTH_TOKEN_PREFIX + secrets.token_urlsafe(32),
            client_id=pending["client_id"],
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        await self.store.put(
            code.code,
            {"code": code.model_dump(mode="json"), "etapi_token": response.json()["authToken"]},
            collection="codes",
            ttl=AUTH_CODE_TTL,
        )
        return RedirectResponse(
            construct_redirect_uri(redirect, code=code.code, state=params.state),
            status_code=302,
        )

    async def _issue(
        self, client_id: str, scopes: list[str], etapi_token: str
    ) -> OAuthToken:
        access = OAUTH_TOKEN_PREFIX + secrets.token_urlsafe(32)
        refresh = OAUTH_TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = int(time.time())
        common = {"client_id": client_id, "scopes": scopes, "etapi_token": etapi_token}
        await self.store.put(
            access,
            {**common, "refresh": refresh, "expires_at": now + ACCESS_TOKEN_TTL},
            collection="access",
            ttl=ACCESS_TOKEN_TTL,
        )
        # ponytail: a client that never comes back leaves its minted ETAPI token
        # in Trilium after this TTL; delete it there by hand, or add a sweeper
        # that logs out expired refresh entries if that list grows.
        await self.store.put(
            refresh,
            {**common, "access": access, "expires_at": now + REFRESH_TOKEN_TTL},
            collection="refresh",
            ttl=REFRESH_TOKEN_TTL,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh,
            scope=" ".join(scopes) or None,
        )

    async def _drop(self, access: str, refresh: str) -> None:
        await self.store.delete(access, collection="access")
        await self.store.delete(refresh, collection="refresh")


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


def register_export_tool(mcp: FastMCP, client: httpx.AsyncClient) -> None:
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


def register_content_put_tools(mcp: FastMCP, client: httpx.AsyncClient) -> None:
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


def build_oauth_provider(mode: str) -> TriliumOAuthProvider:
    """OAuth provider on a Fernet-encrypted file store (same pattern as
    FastMCP's own OAuthProxy)."""
    base_url = os.environ[BASE_URL_ENV].strip().rstrip("/")
    try:
        validate_issuer_url(AnyHttpUrl(base_url))
    except ValueError as e:
        raise RuntimeError(
            f"{BASE_URL_ENV}={base_url!r} is not a valid OAuth issuer: {e} "
            f"(plain http is only allowed for localhost)."
        ) from e
    OAUTH_STORE_DIR.mkdir(parents=True, exist_ok=True)
    files = FileTreeStore(
        data_directory=OAUTH_STORE_DIR,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(OAUTH_STORE_DIR),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            OAUTH_STORE_DIR
        ),
    )
    store = FernetEncryptionWrapper(
        key_value=files,
        source_material=os.environ[OAUTH_SECRET_ENV],
        salt="trilium-mcp-oauth",
        # A changed secret turns stored state into misses: clients just log in again.
        raise_on_decryption_error=False,
    )
    return TriliumOAuthProvider(
        base_url=base_url,
        store=store,
        etapi=httpx.AsyncClient(base_url=etapi_url(), timeout=60),
        passthrough=mode == "both",
    )


def build_server(
    client: httpx.AsyncClient | None = None,
    auth: TriliumOAuthProvider | None = None,
) -> FastMCP:
    """Load the local OpenAPI spec and turn every documented ETAPI endpoint
    into a FastMCP tool. The ETAPI token is supplied per request by the client
    (see TokenCaptureMiddleware / EtapiTokenAuth), so no token is read here.

    `client` is injectable for testing; in production the default client targets
    TRILIUM_SERVER_URL and authenticates from the per-request token. `auth`
    enables OAuth (see TriliumOAuthProvider); None keeps plain token pass-through.
    """
    if client is None:
        client = httpx.AsyncClient(
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
    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="Trilium ETAPI MCP",
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


def serve(mcp: FastMCP, mode: str = "token") -> None:
    """Serve an MCP server over streamable HTTP using the MCP_* environment
    configuration. In `token` mode TokenCaptureMiddleware gates the endpoint;
    otherwise FastMCP's OAuth middleware does (see TriliumOAuthProvider)."""
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
    app = TokenCaptureMiddleware(inner) if mode == "token" else inner

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

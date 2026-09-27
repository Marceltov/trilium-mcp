# How it works

trilium-mcp turns every ETAPI endpoint into an MCP tool and forwards each call to Trilium with an ETAPI token: either the one the client sent, or, with OAuth, the one it minted for that client at login.

![Architecture: MCP clients → trilium-mcp → Trilium, on the Docker network](architecture.png){ width="720" }

trilium-mcp runs as a container sidecar and talks to Trilium over the internal Docker network, so Trilium's ETAPI is never exposed publicly on its own. Clients reach it through a TLS-terminating reverse proxy or directly over a trusted LAN.

## Tools from the OpenAPI spec

At startup the server reads the bundled ETAPI OpenAPI spec and generates one tool per endpoint with `FastMCP.from_openapi`. A few endpoints don't fit the JSON-in, JSON-out shape and are handled specially:

- **Text and HTML responses** (such as `getNoteContent`) keep the generated tool but drop its output schema.
- **ZIP export** (`exportNoteSubtree`) is replaced by a tool that unpacks the archive and returns readable text.
- **Plain-text uploads** (`putNoteContentById`, `putAttachmentContentById`) are replaced by tools that send the body with an explicit `text/plain` content type.
- **`login` and `logout`** are left out: clients already authenticate through the header, and logout would invalidate their own credential.

## ETAPI token

![A tool call with an ETAPI token, forwarded to Trilium unchanged](overview-token.png){ width="560" }

??? note "In detail: tool call in token mode"

    The middleware rejects any request without an `Authorization` header, and the token is carried per request from the middleware to the outgoing ETAPI call:

    ![Token mode: missing-token 401, then an authenticated tool call through TokenCaptureMiddleware and EtapiTokenAuth](token-call.png){ width="720" }

## OAuth

![A one-time browser login mints an ETAPI token; later tool calls use an OAuth access token mapped to it](overview-oauth.png){ width="560" }

??? note "In detail: login (discovery, registration, password, code exchange)"

    The client discovers the OAuth endpoints from the `401`, registers itself, and sends the user to the login page. The Trilium password is exchanged once for a fresh ETAPI token; the client only ever holds opaque `tmcp_` tokens that map to it:

    ![OAuth login: discovery and registration, password login minting an ETAPI token, code exchange for tmcp_ tokens](oauth-login.png){ width="720" }

??? note "In detail: tool call in oauth or both mode"

    `verify_token` maps a `tmcp_` token to its ETAPI token. In `both` mode any other token is passed through as a raw ETAPI token, and an expired `tmcp_` token gets a `401` so the client refreshes:

    ![OAuth tool call: bearer prefixing, verify_token outcomes, and the ETAPI call with the mapped token](oauth-call.png){ width="720" }

??? note "In detail: refresh and revoke"

    ![Refresh rotates the token pair onto the same ETAPI token; revoke drops the pair and deletes the ETAPI token in Trilium](oauth-refresh-revoke.png){ width="720" }

## Startup and health

??? note "In detail: startup, startup_error fallback, health check"

    ![Startup: resolve auth mode, build tools from the OpenAPI spec, fall back to startup_error, serve; health check](startup.png){ width="640" }

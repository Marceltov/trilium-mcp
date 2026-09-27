# Configuration

All configuration is through environment variables, so the server runs cleanly as a sidecar.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `TRILIUM_SERVER_URL` | `http://trilium:8080` | Base URL of the Trilium instance (`/etapi` is appended automatically). |
| `MCP_HOST` | `0.0.0.0` | Interface the MCP server binds to. |
| `MCP_PORT` | `8081` | Port the MCP server listens on. |
| `MCP_PATH` | `/mcp` | HTTP path the MCP endpoint is served at. |
| `TRILIUM_ETAPI_SPEC` | bundled spec | Override the OpenAPI spec path. |
| `MCP_ALLOWED_HOSTS` | *(unset = any)* | Comma-separated `Host` allowlist (DNS-rebinding protection). Unset accepts any Host; set it to restrict. See [Security](security.md#host-allowlist). |
| `MCP_AUTH_MODE` | `both` if the two OAuth variables are set, else `token` | `token` (raw ETAPI token in `Authorization`), `oauth` (OAuth 2.1 only) or `both`. |
| `MCP_BASE_URL` | *(unset)* | Public URL clients reach this server at, e.g. `https://trilium-mcp.example.com`. The OAuth issuer: must be HTTPS (plain `http` only for `localhost`). Required for `oauth` and `both`. |
| `MCP_OAUTH_SECRET` | *(unset)* | Encrypts the OAuth store at `/data/oauth` (mount a volume at `/data`). Required for `oauth` and `both`; changing it logs every OAuth client out. |
| `CHATGPT_ACTIONS` | *(unset = off)* | `true` serves a ChatGPT Custom GPT Action (spec and REST proxy), see [ChatGPT on Android](chatgpt.md). Requires `MCP_BASE_URL`. |

## OAuth details

With `MCP_BASE_URL` and `MCP_OAUTH_SECRET` set, clients that support the MCP authorization spec need only the URL. On first connect they open a login page served by this server, you enter your **Trilium password**, and the server mints a dedicated ETAPI token for that client (visible and deletable in Trilium's ETAPI token list).

- The password goes to Trilium once and is never stored.
- Revoking a client's OAuth token also deletes its ETAPI token in Trilium.
- Raw ETAPI tokens in the `Authorization` header (with or without `Bearer `) keep working in the default `both` mode.
- Mount a volume at `/data` so logins survive container restarts.

An invalid `MCP_AUTH_MODE`, or an explicit `oauth`/`both` without its variables, starts the server in the [`startup_error` state](security.md#startup-errors).

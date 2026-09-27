# Security

The MCP endpoint grants **full read and write access to your notes**. Every request must carry either a Trilium ETAPI token or an OAuth access token issued by this server in the `Authorization` header. Requests with no `Authorization` header are rejected with `401` before reaching any tool.

The server never validates an ETAPI token itself: Trilium enforces validity when the forwarded request reaches the ETAPI. In token-only mode the server holds no secret of its own. The `/health` endpoint is always unauthenticated, for the container healthcheck.

## Tokens in transit

The token is sent in the `Authorization` header on every call. Over plain HTTP it travels in cleartext, so either keep traffic on a **trusted network** (a LAN or the Docker network) or put TLS in front with a [reverse proxy](reverse-proxy.md).

## Host allowlist

By default the server accepts requests for **any** `Host` (FastMCP's DNS-rebinding protection is off), so it can be reached by LAN IP or by the domain your reverse proxy forwards. To lock this down, set `MCP_ALLOWED_HOSTS` to a comma-separated list of the `host[:port]` values you actually use, for example `192.168.1.50:8081,trilium.example.com`. `localhost` is always allowed; anything else gets a `421`.

## OAuth secrets

With [OAuth](configuration.md#oauth-details) enabled the server does hold secrets: the ETAPI tokens it mints, stored Fernet-encrypted under `/data/oauth` with the key from `MCP_OAUTH_SECRET`. Protect that volume and that variable like the tokens themselves.

The login page shows which client is asking and where the authorization code will be sent. Only approve logins you started yourself, because any client can register and send you a login link.

## Startup errors

If the OpenAPI spec can't be loaded or the auth configuration is invalid, the server still starts and completes the MCP handshake, but exposes only a single `startup_error` tool describing how to fix it, rather than failing with an opaque connection error.

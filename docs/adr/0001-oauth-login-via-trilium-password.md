---
status: accepted
date: 2026-09-26
---

# OAuth 2.1 login via the Trilium password, alongside raw ETAPI tokens

## Context and Problem Statement

trilium-mcp authenticated clients only by forwarding a raw ETAPI token from the `Authorization` header, so it stored no secret. App and remote clients (Claude desktop/web/mobile, IDEs) expect the MCP authorization spec — OAuth 2.1 with discovery, dynamic client registration and PKCE — and pasting a long-lived token into each client's config is awkward there. Trilium's ETAPI has no OAuth of its own and accepts only ETAPI tokens, so whatever OAuth flow a client completes, the server must end up holding an ETAPI token to forward.

## Decision Drivers

* Keep one sidecar per Trilium, with no external identity provider to run or register with.
* Existing token clients (the trilium plugin, headless scripts) must keep working unchanged, including across watchtower's automatic image updates.
* Each OAuth client should have its own revocable credential visible in Trilium.

## Considered Options

* The MCP server is its own authorization server; login is the Trilium password, exchanged via ETAPI `/auth/login` for a per-client ETAPI token.
* An external identity provider (GitHub, Google, Authelia/Keycloak) via FastMCP's OAuth proxy, with a configured identity → ETAPI token mapping.
* Stay token-only.

## Decision Outcome

Chosen option: "the MCP server is its own authorization server", because it is the only option that needs no external service, gives every client its own ETAPI token (revocable in Trilium or via OAuth revoke, which calls `/auth/logout`), and builds on FastMCP's `OAuthProvider`, so we write only the login page and storage.

`MCP_AUTH_MODE=token|oauth|both` selects the gate. Unset means `both` when `MCP_BASE_URL` and `MCP_OAUTH_SECRET` are set, otherwise `token` — so deployments that upgrade without the new variables keep their current behavior. In `both`, bearers the server didn't issue (no `tmcp_` prefix) are forwarded to Trilium as raw ETAPI tokens. Guidance for users: OAuth for remote access and app clients, ETAPI tokens for headless clients and the local LAN.

### Consequences

* Good, because app clients connect with just a URL, and no secret is pasted into client config.
* Good, because existing token clients are unaffected.
* Bad, because the server is no longer stateless in OAuth modes: it stores client registrations and minted ETAPI tokens (Fernet-encrypted, `/data/oauth`), which needs a volume and a secret to protect.
* Bad, because the issuer must be HTTPS (localhost excepted, an MCP SDK rule), so OAuth needs a TLS reverse proxy.
* Bad, because dynamic client registration lets anyone send a user a genuine login link; the login page shows the client name and redirect host as the mitigation, with no redirect allowlist yet.
* Bad, because a client that never returns leaves its minted ETAPI token in Trilium after its refresh token expires, until deleted by hand.

### Confirmation

`app/tests/test_oauth.py` drives the full flow in-process (register → authorize → login → token → tool call carries the minted ETAPI token) and covers mode selection, rotation, revoke and the raw-header passthrough; `app/tests/live/test_oauth_flow.py` repeats the flow against the dev stack.

## More Information

Flow diagram: `docs/sequence-oauth.puml`. Implementation: `TriliumOAuthProvider`, `resolve_auth_mode` and `wrap_app` in `app/server.py`.

---
status: accepted
date: 2026-10-25
decision-makers: Marcel Bruckner
---

# OAuth through the shared mcp-login-oauth library, on FastMCP 4

## Context and Problem Statement

ADR 0001 made this server its own OAuth authorization server with the Trilium password as the login.
That code (`TriliumOAuthProvider`, the login and dead-end pages, the encrypted store) was a copy of
the same code in invoiceninja-mcp, paperless-ngx-mcp and the recall engine, and the copies drifted:
this one had no delay after a wrong password, and its `/revoke` was the MCP SDK's, which demands a
client secret, so claude.ai could never revoke. The library also needs FastMCP 4, and this server was
on FastMCP 3.

## Considered Options

* Keep the in-repo copy and port fixes by hand.
* Use [mcp-login-oauth](https://github.com/Marceltov/mcp-login-oauth), supplying only the login field,
  the password check, the logout on revoke and the raw-token passthrough.

## Decision Outcome

Chosen: **mcp-login-oauth** (v0.2.0, pinned by git tag), as decided for all of these servers in its
own ADR 0001. ADR 0001 here still holds: the login is the Trilium password and every client gets its
own ETAPI token. Only the implementation moves.

Upgrading to FastMCP 4 comes with it. Its OpenAPI provider deprecates plain `httpx` clients for
`httpx2` (the same API), so the ETAPI clients are `httpx2` now; the generated tools, route maps and
component function are unchanged.

### Consequences

* Good, because this server gets the library's hardening: public-client revoke, a delay after each
  wrong password, login links that end after 5 failures, tokens bound to this server (RFC 8707) and
  `iss` on the redirect (RFC 9207).
* Bad, because stored OAuth logins don't carry over: the store has a new salt, so the old entries
  (another record shape) read as misses and every OAuth client logs in once more. ETAPI-token clients
  are unaffected.
* Bad, because the image build needs git in its builder stage until the library is on PyPI.

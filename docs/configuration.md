# Configuration

All configuration is through environment variables, so the server runs cleanly as a sidecar. The [compose examples](compose-examples.md) keep them in an env file next to the compose file.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `TRILIUM_SERVER_URL` | `http://trilium:8080` | Base URL of the Trilium Notes instance (`/etapi` is appended automatically). |
| `MCP_HOST` | `0.0.0.0` | Interface the MCP server binds to. |
| `MCP_PORT` | `8081` | Port the MCP server listens on. |
| `MCP_PATH` | `/mcp` | HTTP path the MCP endpoint is served at. |
| `TRILIUM_ETAPI_SPEC` | bundled spec | Override the OpenAPI spec path. |
| `MCP_ALLOWED_HOSTS` | *(unset = any)* | Comma-separated `Host` allowlist (DNS-rebinding protection). Unset accepts any Host; set it to restrict. See [Security](security.md#host-allowlist). |
| `MCP_AUTH_MODE` | *(unset = automatic)* | Usually leave unset: setting `MCP_BASE_URL` and `MCP_OAUTH_SECRET` turns on OAuth next to ETAPI tokens (`both`), otherwise the server accepts ETAPI tokens only (`token`). Set `oauth` to reject raw ETAPI tokens, so clients can only connect through a login you can revoke. See [Choosing a mode](#choosing-a-mode). |
| `MCP_BASE_URL` | *(unset)* | Public URL clients reach this server at, e.g. `https://trilium-mcp.example.com`. The OAuth issuer: must be HTTPS (plain `http` only for `localhost`). Required for `oauth` and `both`. |
| `MCP_OAUTH_SECRET` | *(unset)* | Encrypts the OAuth store at `/data/oauth` (mount a volume at `/data`). Required for `oauth` and `both`; changing it logs every OAuth client out. |
| `CHATGPT_ACTIONS` | *(unset = off)* | `true` serves a ChatGPT Custom GPT Action (spec and REST proxy), see [ChatGPT on Android](chatgpt.md#android). Requires `MCP_BASE_URL`. |
| `MCP_INSTRUCTIONS` | *(unset = none)* | Standing instructions sent to every connecting client, for house rules about how your notes should be used. See [Standing instructions](#standing-instructions). |

## Standing instructions

`MCP_INSTRUCTIONS` is free text that the server returns in the MCP `initialize` response. Claude Code, claude.ai and most other clients place it in the model's system prompt, so it reaches every assistant that connects, on any device, without configuring each client. The server ships no default: it has no opinion on how you use your notes.

Keep it to a few sentences, since it is read at the start of every session, and describe rules, not tools. The tools already come with descriptions. Compose takes multi-line values with `|`:

```yaml
environment:
  MCP_INSTRUCTIONS: |
    Notes are written in German. Never delete a note; move it under "Archive" instead.
    The "Projects" subtree is the source of truth for anything work-related.
```

A longer example, for an [LLM-maintained wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) kept in Trilium Notes:

```yaml
environment:
  MCP_INSTRUCTIONS: |
    This Trilium contains an LLM-maintained wiki. When you learn something during a task
    that would be worth having again (a decision, a non-obvious finding, how a system
    actually behaves), offer to file it there once the task is done; do not interrupt the
    work for it. Search for #llmWikiSchema, read that note and follow it. Write new pages
    as drafts marked AI-assisted and never write under "Sources".
```

An unset or blank variable sends no instructions, which is the behaviour of earlier versions.

## OAuth details

With `MCP_BASE_URL` and `MCP_OAUTH_SECRET` set, clients that support the MCP authorization spec need only the URL. On first connect they open a login page served by this server, you enter your **Trilium Notes password**, and the server mints a dedicated ETAPI token for that client (visible and deletable in Trilium Notes' ETAPI token list).

- The password goes to Trilium Notes once and is never stored.
- Revoking a client's OAuth token also deletes its ETAPI token in Trilium Notes.
- Raw ETAPI tokens in the `Authorization` header (with or without `Bearer `) keep working in the default `both` mode.
- Mount a volume at `/data` (see the [compose examples](compose-examples.md)) so logins survive the container being recreated, for example on an image update.

An invalid `MCP_AUTH_MODE`, or an explicit `oauth`/`both` without its variables, starts the server in the [`startup_error` state](security.md#startup-errors).

### Choosing a mode

You rarely need `MCP_AUTH_MODE`. Adding the two OAuth variables is enough to turn OAuth on, and ETAPI tokens keep working next to it.

Set it explicitly when:

- **The server is open to the internet and you only want OAuth.** In the default `both` mode, any token the server didn't issue is passed to Trilium Notes as an ETAPI token. `oauth` turns that off, so clients can only get in through a login you can revoke, never with a long-lived token pasted into their config.
- **You want a mistake to stop the server.** With `oauth` or `both` set explicitly, a missing `MCP_BASE_URL` or `MCP_OAUTH_SECRET` starts the server in the [`startup_error` state](security.md#startup-errors). When the mode is worked out automatically, the server quietly falls back to token-only and only logs a warning.

`token` turns OAuth off without deleting its variables.

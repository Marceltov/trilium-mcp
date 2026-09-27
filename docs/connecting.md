# Connect a client

## Choosing an auth method

| Method | Best for | How the client authenticates |
| ------ | -------- | ---------------------------- |
| **OAuth** | Remote access and app clients (Claude desktop, web and mobile, IDEs, anything that can open a browser) | Only the URL is configured. On first connect a browser page asks for your Trilium password once, and the server mints a dedicated ETAPI token for that client. Nothing secret is pasted into client config. |
| **ETAPI token** | Headless clients (scripts, CI, servers, agents with no browser) and the local network | The token from *Options → ETAPI* goes in the `Authorization` header on every request. |

Both work side by side in the default `both` mode once OAuth is configured (`MCP_BASE_URL` and `MCP_OAUTH_SECRET`, see [OAuth details](configuration.md#oauth-details)). Without those variables the server accepts ETAPI tokens only. OAuth needs an **HTTPS** public URL (plain `http` only for `localhost`), so it goes with a [reverse proxy](reverse-proxy.md). An ETAPI token over plain HTTP is for networks you trust.

## OAuth

Register the URL with no header. The client opens the login page on first use:

```bash
claude mcp add trilium --scope user --transport http \
  https://trilium-mcp.example.com/mcp
```

In Claude Code, run `/mcp` and pick the server to authenticate.

On claude.ai, add it under *Settings → Connectors → Add custom connector*.

!!! warning "Log in to claude.ai first"

    Make sure you are already logged in to claude.ai before adding the connector. If claude.ai asks you to log in partway through, it can drop the finished OAuth login, and the connector stays unauthenticated with no tools. Remove that connector and add it again; the second attempt goes straight through.

Each client gets its own ETAPI token, visible and deletable under *Options → ETAPI* in Trilium. Deleting it there, or revoking the OAuth token, disconnects just that client.

## ETAPI token

The ETAPI token is the credential: pass it in the `Authorization` header. Point the URL at wherever trilium-mcp is reachable.

=== "Behind a reverse proxy (TLS)"

    ```bash
    claude mcp add trilium --scope user --transport http \
      https://trilium-mcp.example.com/mcp \
      --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
    ```

=== "On a trusted local network"

    ```bash
    claude mcp add trilium --scope user --transport http \
      http://192.168.1.50:8081/mcp \
      --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
    ```

=== "`.mcp.json`"

    Commit a project-level config instead, filling in your host and token (a copy is in the repo as [`.mcp.json`](https://github.com/Marceltov/trilium-mcp/blob/main/.mcp.json)):

    ```json
    {
      "mcpServers": {
        "trilium": {
          "type": "http",
          "url": "https://trilium-mcp.example.com/mcp",
          "headers": {
            "Authorization": "YOUR_TRILIUM_ETAPI_TOKEN"
          }
        }
      }
    }
    ```

The raw token is what Trilium's ETAPI expects. A `Bearer ` prefix is also accepted and stripped before the request is forwarded, so `Authorization: Bearer YOUR_TOKEN` works too.

## Multiple Trilium instances

Run one trilium-mcp container per Trilium (each bound to its instance via `TRILIUM_SERVER_URL`), then add one connection per container under its own name. Each connection picks its own auth method, so you can mix them:

```bash
# OAuth: log in with /mcp on first use
claude mcp add trilium-home --scope user --transport http \
  https://trilium-home.example.com/mcp

# ETAPI token
claude mcp add trilium-work --scope user --transport http \
  https://trilium-work.example.com/mcp \
  --header "Authorization: WORK_TOKEN"
```

## User or project scope

`--scope user` registers the server across all your projects, which is usually what you want for a personal knowledge base. Drop it to fall back to the default local scope, available only to you in the current project. This works the same with either auth method:

```bash
claude mcp add trilium --transport http \
  https://trilium-mcp.example.com/mcp
```

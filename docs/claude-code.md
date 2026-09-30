# Claude Code

Register trilium-mcp with `claude mcp add`. Pick the [auth method](connecting.md#choosing-an-auth-method) per connection.

## OAuth

Register the URL with no header. The client opens the login page on first use:

```bash
claude mcp add trilium --scope user --transport http \
  https://trilium-mcp.example.com/mcp
```

In Claude Code, run `/mcp` and pick the server to authenticate.

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

Add one connection per trilium-mcp container under its own name, such as `trilium-home` and `trilium-work`. See [Multiple Trilium instances](multiple-instances.md).

## User or project scope

`--scope user` registers the server across all your projects, which is usually what you want for a personal knowledge base. Drop it to fall back to the default local scope, available only to you in the current project. This works the same with either auth method:

```bash
claude mcp add trilium --transport http \
  https://trilium-mcp.example.com/mcp
```

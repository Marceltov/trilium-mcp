# Multiple Trilium instances

One trilium-mcp container serves exactly one Trilium, the one in its `TRILIUM_SERVER_URL`. To reach several (say a personal and a work Trilium), run one container per instance and add each to your client under its own name. The name keeps them apart: Claude sees `trilium-home` and `trilium-work` as separate servers with separate tools, so you can say which notes you mean.

## 1. One container per Trilium

Give each container its own name, env file, OAuth volume and host port:

```yaml
services:
  trilium-mcp-home:
    image: ghcr.io/marceltov/trilium-mcp:latest
    container_name: trilium-mcp-home
    restart: unless-stopped
    env_file: trilium-mcp-home.env   # TRILIUM_SERVER_URL=http://trilium-home:8080
    volumes:
      - mcp-oauth-home:/data
    ports:
      - "8081:8081"

  trilium-mcp-work:
    image: ghcr.io/marceltov/trilium-mcp:latest
    container_name: trilium-mcp-work
    restart: unless-stopped
    env_file: trilium-mcp-work.env   # TRILIUM_SERVER_URL=http://trilium-work:8080
    volumes:
      - mcp-oauth-work:/data
    ports:
      - "8082:8081"

volumes:
  mcp-oauth-home:
  mcp-oauth-work:
```

Each env file is a copy of the one in the [compose examples](compose-examples.md). For OAuth, give each its own public URL in `MCP_BASE_URL` (for example `https://trilium-home.example.com` and `https://trilium-work.example.com`, each routed by your [reverse proxy](reverse-proxy.md)) and its own `MCP_OAUTH_SECRET`.

## 2. One named connection per container

Each connection picks its own [auth method](connecting.md#choosing-an-auth-method), so you can mix them.

=== "Claude Code"

    ```bash
    # OAuth: log in with /mcp on first use
    claude mcp add trilium-home --scope user --transport http \
      https://trilium-home.example.com/mcp

    # ETAPI token
    claude mcp add trilium-work --scope user --transport http \
      https://trilium-work.example.com/mcp \
      --header "Authorization: WORK_TOKEN"
    ```

=== "Claude.ai"

    Add one [custom connector](claude-ai.md) per container, for example `Trilium Home` with `https://trilium-home.example.com/mcp` and `Trilium Work` with `https://trilium-work.example.com/mcp`, and log in to each with that Trilium's password.

=== "ChatGPT"

    Create one [connector](chatgpt.md#web-and-desktop) per container, each with its own name and URL.

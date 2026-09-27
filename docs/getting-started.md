# Quick start

Three steps: create a token in Trilium, add one service to your compose file, and point your client at it. Connecting remote or app clients? You can skip the token and use [OAuth](connecting.md#oauth) instead.

## 1. Create an ETAPI token

In Trilium, open *Options → ETAPI → Create new ETAPI token*. This token is the only credential: trilium-mcp stores no secret and forwards the raw token straight to Trilium. Each client presents its own token per request.

![Trilium Options → ETAPI screen with the Create new ETAPI token button](create-etapi.png){ width="720" }

## 2. Add trilium-mcp to your compose file

Add one service to the `docker-compose.yaml` that runs your Trilium. It pulls the prebuilt image, so there's nothing to clone or build. Starting without Trilium, or want HTTPS set up too? Use one of the [complete compose examples](compose-examples.md) instead.

```yaml
services:
  trilium:
    # ... your existing Trilium service ...

  trilium-mcp:
    image: ghcr.io/marceltov/trilium-mcp:latest
    container_name: trilium-mcp
    restart: unless-stopped
    env_file: trilium-mcp.env
    volumes:
      # Keeps OAuth logins when the container is recreated; unused with tokens only.
      - mcp-oauth:/data
    ports:
      - "8081:8081"

volumes:
  mcp-oauth:
```

Next to it, create `trilium-mcp.env` with the settings:

```ini
# Service name of your existing Trilium on the same compose network.
TRILIUM_SERVER_URL=http://trilium:8080

# Optional: enable OAuth login (see "Choosing an auth method").
# Public HTTPS address of this server, behind your reverse proxy.
#MCP_BASE_URL=https://trilium-mcp.example.com
# Encrypts stored logins. Generate once with: openssl rand -hex 32
#MCP_OAUTH_SECRET=
```

To turn on OAuth later, uncomment the last two settings and recreate the container with `docker compose up -d trilium-mcp`. The file holds a secret once OAuth is on, so keep it private (`chmod 600 trilium-mcp.env`) and out of version control. All settings are listed under [Configuration](configuration.md).

Then start it:

```bash
docker compose up -d trilium-mcp
```

Both services share the compose network, so `trilium` resolves to your existing container. If your Trilium runs elsewhere (a separate compose project or host), point `TRILIUM_SERVER_URL` at a URL this container can reach and attach it to the right network; see [Configuration](configuration.md). The MCP endpoint listens on port 8081 at `/mcp`. To use it from other machines, put it behind a [reverse proxy](reverse-proxy.md) for an HTTPS address like `https://trilium-mcp.example.com/mcp`, or use `http://<server-ip>:8081/mcp` on a trusted local network.

Check that it's up, on the Docker host:

```bash
curl http://localhost:8081/health   # -> ok
```

## 3. Connect your MCP client

On the machine running your client, register the server's address with the token from step 1:

```bash
claude mcp add trilium --scope user --transport http \
  https://trilium-mcp.example.com/mcp \
  --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
```

Your client now has the Trilium tools. [Connect a client](connecting.md) covers remote hosts, OAuth, multiple instances and `.mcp.json`.

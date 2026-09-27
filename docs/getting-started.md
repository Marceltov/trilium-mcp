# Quick start

Three steps: create a token in Trilium, add one service to your compose file, and point your client at it. You need a running Trilium server; [don't have one yet?](compose-examples.md#dont-have-trilium-yet) Connecting remote or app clients? You can skip the token and use [OAuth](connecting.md#oauth) instead.

## 1. Create an ETAPI token

In Trilium, open *Options → ETAPI → Create new ETAPI token*. This token is the only credential: trilium-mcp stores no secret and forwards the raw token straight to Trilium. Each client presents its own token per request.

![Trilium Options → ETAPI screen with the Create new ETAPI token button](create-etapi.png){ width="720" }

## 2. Add trilium-mcp to your compose file

Add one service to the `docker-compose.yaml` that runs your Trilium. It pulls the prebuilt image, so there's nothing to clone or build:

```yaml
services:
  trilium:
    # ... your existing Trilium service ...

  trilium-mcp:
    image: ghcr.io/marceltov/trilium-mcp:latest
    restart: unless-stopped
    environment:
      TRILIUM_SERVER_URL: http://trilium:8080
    ports:
      - "8081:8081"
```

Then start it and check that it's up:

```bash
docker compose up -d trilium-mcp
curl http://localhost:8081/health   # -> ok
```

To reach it from other machines, put it behind a [reverse proxy](reverse-proxy.md) for an HTTPS address like `https://trilium-mcp.example.com/mcp`, or use `http://<server-ip>:8081/mcp` on a trusted local network. For OAuth login, an env file, or Trilium in a separate compose project, see the [compose examples](compose-examples.md).

## 3. Connect your MCP client

On the machine running your client, register the server's address with the token from step 1:

```bash
claude mcp add trilium --scope user --transport http \
  https://trilium-mcp.example.com/mcp \
  --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
```

Your client now has the Trilium tools. [Connect a client](connecting.md) covers remote hosts, OAuth, multiple instances and `.mcp.json`.

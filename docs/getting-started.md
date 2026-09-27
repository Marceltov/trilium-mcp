# Quick start

Three steps: create a token in Trilium, add one service to your compose file, and point your client at it. You need a running Trilium server; [don't have one yet?](compose-examples.md#dont-have-trilium-yet) Connecting remote or app clients? You can skip the token and use [OAuth](connecting.md#oauth) instead.

## 1. Create an ETAPI token

In Trilium, open *Options → ETAPI → Create new ETAPI token*. This token is the only credential: trilium-mcp stores no secret and forwards the raw token straight to Trilium. Each client presents its own token per request.

![Trilium Options → ETAPI screen with the Create new ETAPI token button](create-etapi.png){ width="720" }

## 2. Add trilium-mcp to your compose file

Add the `trilium-mcp` service and the `mcp-oauth` volume to the `docker-compose.yaml` that runs your Trilium. It pulls the prebuilt image, so there's nothing to clone or build. Trilium in its own compose project? Use the [separate compose project](compose-examples.md#as-a-separate-compose-project) example instead.

```yaml
--8<-- "examples/same-project/docker-compose.yaml"
```

Next to it, copy the settings to `trilium-mcp.env`:

```ini
--8<-- "examples/same-project/trilium-mcp.env.example"
```

To turn on OAuth later, fill in `MCP_BASE_URL` and `MCP_OAUTH_SECRET` and recreate the container with `docker compose up -d trilium-mcp`. The file holds a secret once OAuth is on, so keep it private (`chmod 600 trilium-mcp.env`) and out of version control. All settings are listed under [Configuration](configuration.md).

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

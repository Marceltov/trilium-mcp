# Compose examples

Two complete stacks you can copy and start from scratch. Each is a folder in the repo's [`examples/`](https://github.com/Marceltov/trilium-mcp/tree/main/examples) directory: download it, copy `.env.example` to `.env`, fill it in, and run `docker compose up -d`.

Compose reads `.env` automatically and substitutes its values into the compose file. Keep `.env` private (`chmod 600 .env`) and out of version control once it holds the OAuth secret.

## Local network, ETAPI tokens

Trilium and trilium-mcp on one host, reached over a network you trust. Clients connect to `http://<server-ip>:8081/mcp` with an [ETAPI token](connecting.md#etapi-token).

=== "docker-compose.yaml"

    ```yaml
    --8<-- "examples/lan/docker-compose.yaml"
    ```

=== ".env"

    ```ini
    --8<-- "examples/lan/.env.example"
    ```

## Public HTTPS with OAuth

Trilium and trilium-mcp behind [Caddy](https://caddyserver.com), which gets TLS certificates automatically. Trilium's web UI and the MCP server each get their own domain, and only Caddy is exposed. Clients connect to `https://trilium-mcp.example.com/mcp` with [OAuth](connecting.md#oauth) or an ETAPI token.

Before starting, point both domains' DNS records at the host and open ports 80 and 443.

=== "docker-compose.yaml"

    ```yaml
    --8<-- "examples/caddy/docker-compose.yaml"
    ```

=== ".env"

    ```ini
    --8<-- "examples/caddy/.env.example"
    ```

=== "Caddyfile"

    ```
    --8<-- "examples/caddy/Caddyfile"
    ```

`MCP_ALLOWED_HOSTS` is set to the MCP domain, so the server rejects requests for any other host name. Compose refuses to start if `MCP_DOMAIN`, `TRILIUM_DOMAIN` or `MCP_OAUTH_SECRET` is empty.

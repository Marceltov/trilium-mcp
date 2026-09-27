# Compose examples

trilium-mcp runs next to a Trilium server you already have. Pick the example that matches how Trilium is deployed: in the same compose file, or as its own compose project. Both are in the repo's [`examples/`](https://github.com/Marceltov/trilium-mcp/tree/main/examples) directory.

## Don't have Trilium yet?

trilium-mcp connects to an existing Trilium server. To set one up, follow Trilium's own guide to [running Trilium with Docker](https://docs.triliumnotes.org/user-guide/setup/server/installation/docker), then come back here. Trilium's [documentation](https://docs.triliumnotes.org/) covers the other ways to install it.

## In Trilium's compose file

Add the `trilium-mcp` service and the `mcp-oauth` volume to the `docker-compose.yaml` that runs Trilium. Its settings go in a separate `trilium-mcp.env`, so they don't mix with the `.env` Trilium may already use. Copy `trilium-mcp.env.example` to `trilium-mcp.env` next to the compose file, adjust it, and run `docker compose up -d trilium-mcp`.

=== "docker-compose.yaml"

    ```yaml
    --8<-- "examples/same-project/docker-compose.yaml"
    ```

=== "trilium-mcp.env"

    ```ini
    --8<-- "examples/same-project/trilium-mcp.env.example"
    ```

Both services share the compose network, so `trilium` resolves to your Trilium container.

## As a separate compose project

Use this when you'd rather keep trilium-mcp out of Trilium's compose file. It joins the Docker network Trilium is already on. Put the files in their own folder, copy `.env.example` to `.env`, adjust it, and run `docker compose up -d`.

=== "docker-compose.yaml"

    ```yaml
    --8<-- "examples/separate-project/docker-compose.yaml"
    ```

=== ".env"

    ```ini
    --8<-- "examples/separate-project/.env.example"
    ```

To find `TRILIUM_NETWORK`, run `docker network ls`, or `docker inspect <trilium container>` to see which network Trilium is on. `TRILIUM_SERVER_URL` uses Trilium's service or container name on that network.

## Turning on OAuth

In either example, fill in `MCP_BASE_URL` and `MCP_OAUTH_SECRET` in the env file and recreate the container with `docker compose up -d`. Once the file holds the secret, keep it private (`chmod 600`) and out of version control. Every setting is described under [Configuration](configuration.md).

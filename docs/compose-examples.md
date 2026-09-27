# Compose example

A standalone compose project for trilium-mcp that joins the Docker network of the Trilium you already run. Use it when Trilium lives in its own compose project; if you'd rather add one service to Trilium's compose file, follow the [quick start](getting-started.md) instead.

The files are in the repo's [`examples/`](https://github.com/Marceltov/trilium-mcp/tree/main/examples) directory. Put them in a folder, copy `.env.example` to `.env`, adjust it, and run `docker compose up -d`.

=== "docker-compose.yaml"

    ```yaml
    --8<-- "examples/docker-compose.yaml"
    ```

=== ".env"

    ```ini
    --8<-- "examples/.env.example"
    ```

To find `TRILIUM_NETWORK`, run `docker network ls`, or `docker inspect <trilium container>` to see which network Trilium is on. `TRILIUM_SERVER_URL` uses Trilium's service or container name on that network.

To turn on OAuth, fill in `MCP_BASE_URL` and `MCP_OAUTH_SECRET` and recreate the container with `docker compose up -d`. Once `.env` holds the secret, keep it private (`chmod 600 .env`) and out of version control. Every setting is described under [Configuration](configuration.md).

## Don't have Trilium yet?

trilium-mcp connects to an existing Trilium server. To set one up, follow Trilium's own guide to [running Trilium with Docker](https://docs.triliumnotes.org/user-guide/setup/server/installation/docker), then come back here. Trilium's [documentation](https://docs.triliumnotes.org/) covers the other ways to install it.

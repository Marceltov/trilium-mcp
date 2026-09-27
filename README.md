<p align="center">
  <img src="docs/trilium.svg" alt="Trilium logo" width="96">
</p>

<h1 align="center"><a href="https://github.com/Marceltov/trilium-mcp">Trilium ETAPI MCP server</a></h1>

<p align="center">
  <a href="https://marceltov.github.io/trilium-mcp/">
    <img alt="Documentation" src="https://img.shields.io/badge/docs-marceltov.github.io-2f7a27">
  </a>
  <a href="https://github.com/Marceltov/trilium-mcp/pkgs/container/trilium-mcp">
    <img alt="GHCR image" src="https://img.shields.io/github/v/release/Marceltov/trilium-mcp?logo=docker&logoColor=white&label=ghcr.io%2Fmarceltov%2Ftrilium-mcp&color=2496ED">
  </a>
  <a href="LICENSE">
    <img alt="License: AGPL v3" src="https://img.shields.io/badge/License-AGPL_v3-blue.svg">
  </a>
  <a href="https://github.com/Marceltov/trilium-plugin">
    <img alt="Claude Code plugin: trilium-plugin" src="https://img.shields.io/badge/Claude_Code_plugin-trilium--plugin-8A2BE2">
  </a>
</p>

A standalone [MCP](https://modelcontextprotocol.io) server that exposes the
[Trilium](https://triliumnotes.org) [ETAPI](https://github.com/TriliumNext/Trilium)
(External API) as MCP tools. It runs as a **container sidecar** next to your Trilium
instance: nearly every documented ETAPI endpoint is turned into an MCP tool at startup
via `FastMCP.from_openapi` (**all 38 tools** — `createNote`, `getNoteById`, `searchNotes`,
`exportNoteSubtree`, …; the auth session endpoints `login`/`logout` are excluded),
served over streamable **HTTP** so any MCP client connects to it by URL.

> [!IMPORTANT]
> If your client is [Claude Code](https://code.claude.com), this is best used together with [`trilium-plugin`](https://github.com/Marceltov/trilium-plugin) — the client-side counterpart to this repo, bundling the `.mcp.json` wiring plus ready-made skills (create/delete/move/rename/search notes, manage attributes, work with templates and journal notes, export a subtree) that call these tools, so you get a working Trilium client without writing any of the tool-call glue yourself.

## Documentation

**Full documentation: [marceltov.github.io/trilium-mcp](https://marceltov.github.io/trilium-mcp/)**

- [Quick start](https://marceltov.github.io/trilium-mcp/getting-started/): create a token, add the container, connect a client
- [Connect a client](https://marceltov.github.io/trilium-mcp/connecting/): OAuth or ETAPI token, multiple instances, `.mcp.json`
- [ChatGPT on Android](https://marceltov.github.io/trilium-mcp/chatgpt/): the Custom GPT Action stopgap
- [Configuration](https://marceltov.github.io/trilium-mcp/configuration/), [reverse proxy and TLS](https://marceltov.github.io/trilium-mcp/reverse-proxy/) and [security](https://marceltov.github.io/trilium-mcp/security/)
- [How it works](https://marceltov.github.io/trilium-mcp/how-it-works/): architecture and request flows
- [Alternatives](https://marceltov.github.io/trilium-mcp/alternatives/): other Trilium MCP servers compared

## Quick start

Add the service next to your Trilium in `docker-compose.yaml`:

```yaml
  trilium-mcp:
    image: ghcr.io/marceltov/trilium-mcp:latest
    restart: unless-stopped
    environment:
      TRILIUM_SERVER_URL: http://trilium:8080
    ports:
      - "8081:8081"
```

Then create an ETAPI token in Trilium (*Options → ETAPI*) and connect your client:

```bash
docker compose up -d trilium-mcp
claude mcp add trilium --scope user --transport http \
  http://localhost:8081/mcp \
  --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
```

See the [quick start](https://marceltov.github.io/trilium-mcp/getting-started/) for OAuth login and running Trilium elsewhere.

## Contributing

For local development there's a ready-to-run stack: a throwaway Trilium seeded with the default demo notes plus the MCP server built from local source (`docker compose up -d --build`). See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, seed-instance credentials, and how to run the tests. The documentation site is built from [`docs/`](docs/) with Material for MkDocs.

## License

Copyright © 2026 Marcel Bruckner.

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later). You may use, modify, and redistribute it, but any modified version — **including one you run as a network service** — must be released under the same license with its source made available to its users, and the original copyright notice preserved. See [LICENSE](LICENSE) for the full terms.

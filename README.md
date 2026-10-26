<p align="center">
  <img src="docs/trilium.svg" alt="Trilium logo" width="96">
</p>

<h1 align="center"><a href="https://github.com/Marceltov/trilium-mcp">Trilium Notes ETAPI MCP server</a></h1>

<p align="center">
  <a href="https://trilium-mcp.marceltov.de/">
    <img alt="Documentation" src="https://img.shields.io/badge/docs-trilium--mcp.marceltov.de-2f7a27">
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

> [!WARNING]
> **This project is archived and no longer maintained.** Trilium Notes 0.106+ ships its own
> [MCP](https://modelcontextprotocol.io) server at `/mcp` (enable it under
> *Options → AI / LLM → MCP server*). Use that instead of this sidecar.
>
> To connect a client to it directly, create a token under *Options → ETAPI* and put it in the
> client's MCP configuration as `Authorization: Bearer <token>`.
>
> **For convenience, add [trilium-mcp-proxy](https://github.com/Marceltov/trilium-mcp-proxy).**
> It puts an OAuth login in front of the built-in server: you add the URL to any MCP client
> (claude.ai, Claude Code, the Claude apps, …) and log in once with your Trilium password. You don't
> have to create, paste or rotate a token, and every request goes unchanged to Trilium's own tools.
>
> The proxy runs on your own server next to Trilium, and the login page is its own. Your password
> goes only from your browser to that page and on to your Trilium, which trades it for an ETAPI
> token; the proxy never stores or logs it. The MCP client (claude.ai included) never sees the
> password, only opaque OAuth tokens it can't use anywhere but your proxy.
> The login is [mcp-login-oauth](https://github.com/Marceltov/mcp-login-oauth), the same one this
> server used.
>
> The image `ghcr.io/marceltov/trilium-mcp` stays available, and the rest of this README
> describes it as it was at its last release.

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

**Full documentation: [trilium-mcp.marceltov.de](https://trilium-mcp.marceltov.de/)**

- [Quick start](https://trilium-mcp.marceltov.de/getting-started/): create a token, add the container, connect a client
- [Connect a client](https://trilium-mcp.marceltov.de/connecting/): OAuth or ETAPI token, multiple instances, `.mcp.json`
- [ChatGPT on Android](https://trilium-mcp.marceltov.de/chatgpt/): the Custom GPT Action stopgap
- [Configuration](https://trilium-mcp.marceltov.de/configuration/), [reverse proxy and TLS](https://trilium-mcp.marceltov.de/reverse-proxy/) and [security](https://trilium-mcp.marceltov.de/security/)
- [How it works](https://trilium-mcp.marceltov.de/how-it-works/): architecture and request flows
- [Alternatives](https://trilium-mcp.marceltov.de/alternatives/): other Trilium MCP servers compared

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
  https://trilium-mcp.example.com/mcp \
  --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
```

See the [quick start](https://trilium-mcp.marceltov.de/getting-started/) for OAuth login and running Trilium elsewhere.

## Contributing

For local development there's a ready-to-run stack: a throwaway Trilium seeded with the default demo notes plus the MCP server built from local source (`docker compose up -d --build`). See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, seed-instance credentials, and how to run the tests. The documentation site is built from [`docs/`](docs/) with Material for MkDocs.

## License

Copyright © 2026 Marcel Bruckner.

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later). You may use, modify, and redistribute it, but any modified version — **including one you run as a network service** — must be released under the same license with its source made available to its users, and the original copyright notice preserved. See [LICENSE](LICENSE) for the full terms.

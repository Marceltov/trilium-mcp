---
hide:
  - toc
---

<div class="tm-hero" markdown>

# Your Trilium notes, as tools for Claude

<p class="tm-hero__lead">trilium-mcp runs next to your Trilium server and lets Claude, IDEs and other MCP clients search, read and write your notes from anywhere, through every documented ETAPI endpoint.</p>

[Set it up](getting-started.md){ .md-button .md-button--primary } [Connect a client](connecting.md){ .md-button }

</div>

Once the container is reachable, connecting Claude Code from any machine takes one command:

```bash
claude mcp add trilium --scope user --transport http \
  https://trilium-mcp.example.com/mcp \
  --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
```

## What it does

- **Works from any device.** Trilium's built-in MCP server only answers on `localhost`, so your client has to run on the Trilium machine. trilium-mcp is served over HTTP, so Claude on your laptop, phone or the web can reach it through a reverse proxy.
- **Covers the whole ETAPI.** All 38 tools (`createNote`, `getNoteById`, `searchNotes`, `exportNoteSubtree`, …) are generated at startup from Trilium's OpenAPI spec, so nothing is hand-picked or left out.
- **Runs as a sidecar.** One small container on the same Docker network as Trilium. Only trilium-mcp is exposed; Trilium's ETAPI never has to be reachable on its own.
- **Two ways to sign in.** Log in once in the browser with your Trilium password (OAuth, for remote and app clients), or send an ETAPI token with each request (for scripts and the local network). See [Choosing an auth method](connecting.md#choosing-an-auth-method).
- **Stores nothing in token mode.** Each client's token is forwarded to Trilium per request, so one sidecar serves many clients.

![Architecture: MCP clients → trilium-mcp → Trilium, on the Docker network](architecture.png){ width="720" }

!!! tip "Using Claude Code?"

    Pair this server with [`trilium-plugin`](https://github.com/Marceltov/trilium-plugin), the client-side counterpart. It bundles the `.mcp.json` wiring plus ready-made skills (create, move, rename and search notes, manage attributes, work with templates and journal notes, export a subtree) that call these tools for you.

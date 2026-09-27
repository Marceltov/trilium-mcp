---
hide:
  - toc
---

<div class="tm-hero" markdown>

# Your Trilium notes, as tools for Claude

<p class="tm-hero__lead">trilium-mcp runs next to your Trilium server and lets Claude, IDEs and other MCP clients search, read and write your notes through every documented ETAPI endpoint.</p>

[Set it up](getting-started.md){ .md-button .md-button--primary } [Connect a client](connecting.md){ .md-button }

</div>

Once the container is running, connecting Claude Code takes one command:

```bash
claude mcp add trilium --scope user --transport http \
  http://localhost:8081/mcp \
  --header "Authorization: YOUR_TRILIUM_ETAPI_TOKEN"
```

## What it does

- **Covers the whole ETAPI.** All 38 tools (`createNote`, `getNoteById`, `searchNotes`, `exportNoteSubtree`, …) are generated at startup from Trilium's OpenAPI spec, so nothing is hand-picked or left out.
- **Runs as a sidecar.** One small container on the same Docker network as Trilium, served over streamable HTTP, so any MCP client connects to it by URL. Trilium's ETAPI never has to be exposed on its own.
- **Two ways to sign in.** Log in once in the browser with your Trilium password (OAuth, for remote and app clients), or send an ETAPI token with each request (for scripts and the local network). See [Choosing an auth method](connecting.md#choosing-an-auth-method).
- **Stores nothing in token mode.** Each client's token is forwarded to Trilium per request, so one sidecar serves many clients.

![Architecture: MCP clients → trilium-mcp → Trilium, on the Docker network](architecture.png){ width="720" }

!!! tip "Using Claude Code?"

    Pair this server with [`trilium-plugin`](https://github.com/Marceltov/trilium-plugin), the client-side counterpart. It bundles the `.mcp.json` wiring plus ready-made skills (create, move, rename and search notes, manage attributes, work with templates and journal notes, export a subtree) that call these tools for you.

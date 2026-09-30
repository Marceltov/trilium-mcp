---
hide:
  - toc
---

<div class="tm-hero" markdown>

# Your Trilium notes, as tools for Claude

<p class="tm-hero__lead">trilium-mcp runs next to your Trilium server and turns your AI assistant into a front end for your notes: ask Claude on your phone, desktop or claude.ai, or any other MCP client, to search, write and reorganize them, through every documented ETAPI endpoint.</p>

[Set it up](getting-started.md){ .md-button .md-button--primary } [Connect a client](connecting.md){ .md-button }

</div>

Once the container is reachable, connecting Claude Code from any machine takes one command, then `/mcp` to log in with your Trilium password:

```bash
claude mcp add trilium --scope user --transport http \
  https://trilium-mcp.example.com/mcp
```

Running more than one Trilium? Add one container and one named connection per instance, see [Multiple Trilium instances](multiple-instances.md).

## What it does

- **Your assistant becomes the front end.** Instead of opening Trilium, you ask: "add this to today's journal", "what did I note about the router?". Claude reads and edits the notes for you, in the desktop and mobile apps or on claude.ai.
- **Works from any device.** trilium-mcp is served over HTTP, so Claude on your laptop, phone or the web can reach it through a reverse proxy, and app clients sign in with OAuth. It runs next to Trilium rather than inside it, so it also works with versions before Trilium's own [built-in MCP server](alternatives.md#triliums-built-in-mcp-server).
- **Covers the whole ETAPI.** All 38 tools (`createNote`, `getNoteById`, `searchNotes`, `exportNoteSubtree`, …) are generated at startup from Trilium's OpenAPI spec, so nothing is hand-picked or left out.
- **Runs as a sidecar.** One small container on the same Docker network as Trilium. Only trilium-mcp is exposed; Trilium's ETAPI never has to be reachable on its own.
- **Two ways to sign in.** Log in once in the browser with your Trilium password (OAuth, for remote and app clients), or send an ETAPI token with each request (for scripts and the local network). See [Choosing an auth method](connecting.md#choosing-an-auth-method).
- **Stores nothing in token mode.** Each client's token is forwarded to Trilium per request, so one sidecar serves many clients.

```mermaid
--8<-- "docs/diagrams/architecture.mmd"
```

!!! tip "Using Claude Code?"

    Pair this server with [`trilium-plugin`](https://trilium-plugin.marceltov.de/), the client-side counterpart. A skill registers your Trilium instances with Claude Code, and ready-made skills (create, move, rename and search notes, manage attributes, work with templates and journal notes, export a subtree) call these tools for you.

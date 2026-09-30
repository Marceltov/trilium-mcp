# Alternatives

## Trilium's built-in MCP server

Since v0.103, Trilium ships its own [MCP server](https://docs.triliumnotes.org/user-guide/llm/mcp). It is off by default (turn it on under *Options → AI/LLM*), marked experimental, and speaks HTTP with an ETAPI token as the Bearer credential. It exposes the same tools as Trilium's built-in AI chat, limited by the *Note access* setting.

If you only need those tools and your client can send a static token, the built-in server needs no extra container. trilium-mcp complements it where you want the assistant to be your everyday front end to Trilium, from the Claude apps and claude.ai as much as from your desk:

- **The whole ETAPI**: all 38 endpoints as tools, generated from the OpenAPI spec, including branches, attributes, attachments, revisions, journal notes and subtree export.
- **OAuth login**: claude.ai, the Claude apps and ChatGPT connectors sign in with your Trilium password instead of a pasted token, and each client gets its own revocable ETAPI token.
- **Older Trilium versions**: it talks to the ETAPI from outside, so it works with Trilium releases before v0.103.

## Other MCP servers

Other open-source Trilium/TriliumNext MCP servers exist too. Most are stdio subprocesses that connect a single local client to one Trilium using a token baked into the environment or a config file.

trilium-mcp is instead **HTTP-native** and forwards each client's token **per request**, so a single sidecar can serve many clients, each presenting its own token, and in token mode stores no secret of its own. Like the others, one sidecar fronts one Trilium, set via `TRILIUM_SERVER_URL`; run one per instance. Its tools are also **generated from the ETAPI OpenAPI spec** (full endpoint coverage) rather than hand-written.

| Project | Language | Transport | Token handling | Tools | Docker image | Latest activity |
| ------- | -------- | --------- | -------------- | ----- | ------------ | --------------- |
| **trilium-mcp** (this) | Python | Streamable **HTTP** | Per-request `Authorization` pass-through, or OAuth 2.1 login (many clients) | **38**, generated from OpenAPI | Yes (sidecar, GHCR) | active |
| [tan-yong-sheng/triliumnext-mcp](https://github.com/tan-yong-sheng/triliumnext-mcp) | TypeScript | stdio | Env var, baked in | 11, hand-written | Yes (GHCR) | Mar 2026 |
| [paerrin/trilium-mcp-server](https://codeberg.org/paerrin/trilium-mcp-server) | Node.js/TS | stdio | Config file, multi-instance | 24, hand-written | No | Jan 2026 |
| [radonx/mcp-trilium](https://github.com/radonx/mcp-trilium) | JavaScript | stdio | Env var, baked in | 4, hand-written | No | Aug 2025 |

## Maintenance

As of July 2026:

- [tan-yong-sheng/triliumnext-mcp](https://github.com/tan-yong-sheng/triliumnext-mcp) is the most active and popular (about 63 stars, last commit March 2026), though it labels itself a prototype.
- [paerrin/trilium-mcp-server](https://codeberg.org/paerrin/trilium-mcp-server) saw a short burst of releases (Dec 2025 to v0.1.7 in Jan 2026) and has been quiet since.
- [radonx/mcp-trilium](https://github.com/radonx/mcp-trilium) has had no commits since August 2025 (about 3 commits total, 1 star) and **appears abandoned**.

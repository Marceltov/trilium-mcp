# Alternatives

Other open-source Trilium/TriliumNext MCP servers exist. Most are stdio subprocesses that connect a single local client to one Trilium using a token baked into the environment or a config file.

trilium-mcp is instead **HTTP-native** and forwards each client's token **per request**, so a single sidecar can serve many clients, each presenting its own token, while storing no secret of its own. Like the others, one sidecar fronts one Trilium, set via `TRILIUM_SERVER_URL`; run one per instance. Its tools are also **generated from the ETAPI OpenAPI spec** (full endpoint coverage) rather than hand-written.

| Project | Language | Transport | Token handling | Tools | Docker image | Latest activity |
| ------- | -------- | --------- | -------------- | ----- | ------------ | --------------- |
| **trilium-mcp** (this) | Python | Streamable **HTTP** | Per-request `Authorization` pass-through, or OAuth 2.1 login (many clients) | **~40**, generated from OpenAPI | Yes (sidecar, GHCR) | active |
| [tan-yong-sheng/triliumnext-mcp](https://github.com/tan-yong-sheng/triliumnext-mcp) | TypeScript | stdio | Env var, baked in | 11, hand-written | Yes (GHCR) | Mar 2026 |
| [paerrin/trilium-mcp-server](https://codeberg.org/paerrin/trilium-mcp-server) | Node.js/TS | stdio | Config file, multi-instance | 24, hand-written | No | Jan 2026 |
| [radonx/mcp-trilium](https://github.com/radonx/mcp-trilium) | JavaScript | stdio | Env var, baked in | 4, hand-written | No | Aug 2025 |

## Maintenance

As of July 2026:

- [tan-yong-sheng/triliumnext-mcp](https://github.com/tan-yong-sheng/triliumnext-mcp) is the most active and popular (about 63 stars, last commit March 2026), though it labels itself a prototype.
- [paerrin/trilium-mcp-server](https://codeberg.org/paerrin/trilium-mcp-server) saw a short burst of releases (Dec 2025 to v0.1.7 in Jan 2026) and has been quiet since.
- [radonx/mcp-trilium](https://github.com/radonx/mcp-trilium) has had no commits since August 2025 (about 3 commits total, 1 star) and **appears abandoned**.

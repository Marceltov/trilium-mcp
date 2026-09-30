# Connect a client

## Choosing an auth method

| Method | Best for | How the client authenticates |
| ------ | -------- | ---------------------------- |
| **OAuth** | Remote access and app clients (Claude desktop, web and mobile, IDEs, anything that can open a browser) | Only the URL is configured. On first connect a browser page asks for your Trilium password once, and the server mints a dedicated ETAPI token for that client. Nothing secret is pasted into client config. |
| **ETAPI token** | Headless clients (scripts, CI, servers, agents with no browser) and the local network | The token from *Options → ETAPI* goes in the `Authorization` header on every request. |

Both work side by side in the default `both` mode once OAuth is configured (`MCP_BASE_URL` and `MCP_OAUTH_SECRET`, see [OAuth details](configuration.md#oauth-details)). Without those variables the server accepts ETAPI tokens only. OAuth needs an **HTTPS** public URL (plain `http` only for `localhost`), so it goes with a [reverse proxy](reverse-proxy.md). An ETAPI token over plain HTTP is for networks you trust.

## Pick your client

- [Claude Code](claude-code.md): one `claude mcp add` command, with OAuth or an ETAPI token.
- [Claude.ai](claude-ai.md): a custom connector on the web, which the desktop and mobile apps then use too. OAuth only.
- [ChatGPT](chatgpt.md): an MCP connector in Developer mode on the web and desktop, or a Custom GPT Action for the Android app.

For more than one Trilium, run one trilium-mcp container per instance and add each as its own named connection, for example [in Claude Code](claude-code.md#multiple-trilium-instances).

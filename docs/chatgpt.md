# ChatGPT on Android

ChatGPT connects to this server over MCP (Developer mode) only on the web and desktop. The Android app doesn't support MCP yet, but it can use a Custom GPT's **Actions**, which are plain REST calls. With `CHATGPT_ACTIONS=true` (and `MCP_BASE_URL` set to the public HTTPS URL), the server also serves:

- `GET /chatgpt/openapi.json`: the ETAPI spec trimmed to the 30 operations a GPT Action allows (no login/logout, ZIP import/export or attachments), pointed at the proxy below. It's public, like the ETAPI spec itself.
- `/chatgpt/etapi/...`: a REST proxy to Trilium that forwards only those 30 operations, with the same token handling as MCP calls. Trilium itself can stay private.

## Set up the Custom GPT

1. On chatgpt.com, open **Explore GPTs → Create → Configure → Create new action**.
2. Choose **Import from URL** and enter `https://trilium-mcp.example.com/chatgpt/openapi.json`.
3. Under **Authentication**, choose **API Key** with auth type **Bearer**, and paste an ETAPI token. Raw ETAPI tokens need the `token` or `both` [auth mode](configuration.md).
4. Save the GPT as **Only me**. It then shows up in the Android app.

!!! note "A stopgap"

    OpenAI is retiring custom GPTs (from Dec 11, 2026 for Enterprise workspaces; other plans may follow). Treat this as a bridge until ChatGPT's mobile apps support MCP. The reasoning behind it is in [the design decision](adr/0002-chatgpt-custom-gpt-action-proxy.md).

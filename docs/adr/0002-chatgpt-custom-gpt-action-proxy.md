---
status: accepted
date: 2026-09-26
---

# ChatGPT Custom GPT Action served by the MCP server, behind a flag

## Context and Problem Statement

ChatGPT connects to MCP servers (Developer mode apps/plugins) only on the web and desktop; the Android app can't use them. The Android app does run Custom GPTs, whose Actions are plain REST calls described by an OpenAPI spec, capped at 30 operations with descriptions of at most 300 characters. The ETAPI spec has 40 operations, and `putNoteContentById` takes a text/plain body that GPT Actions may not send. How should Trilium be reachable from ChatGPT on Android?

## Considered Options

* A trimmed spec plus a REST proxy served by this MCP server, enabled by `CHATGPT_ACTIONS=true`.
* A hand-trimmed spec file pointed directly at Trilium's `/etapi`, with no server change.
* Publishing to ChatGPT's Plugin Directory.
* Waiting for MCP support in ChatGPT's mobile apps.

## Decision Outcome

Chosen option: "trimmed spec plus proxy in the MCP server", because it reuses the public HTTPS endpoint and token handling that already exist, so Trilium can stay private. The spec is generated at startup from the bundled ETAPI spec, so it can't drift from it. The proxy can also fix the text/plain body: the served spec describes `putNoteContentById` as JSON `{content}`, and the proxy converts it back.

The proxy forwards only the 30 operations in the served spec. That keeps ETAPI's unauthenticated `/auth/login` off the new surface. Login/logout, ZIP import/export and the six attachment operations are dropped to stay within 30. Requests go through the same `EtapiTokenAuth` client as MCP tool calls, so every auth mode behaves as it does for MCP.

### Consequences

* Good, because ChatGPT on Android gets 30 Trilium operations with no change to Trilium and no new service.
* Good, because it's off by default and the MCP endpoint is unchanged.
* Bad, because the server now has a second public surface (REST, outside MCP) and a public spec route, exempted from `TokenCaptureMiddleware` in `token` mode.
* Bad, because OpenAI is retiring custom GPTs (from Dec 11, 2026 for Enterprise workspaces; other plans may follow). Remove this once ChatGPT's mobile apps support MCP.
* Neutral, because the GPT authenticates with a pasted ETAPI token; OAuth for the GPT (a static client registered via `/register`) is possible later without server changes.

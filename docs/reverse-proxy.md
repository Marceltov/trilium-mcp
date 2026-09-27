# Reverse proxy and TLS

The container serves plain HTTP on `:8081`. Terminate TLS at your reverse proxy, so the token never crosses an untrusted network in cleartext. OAuth requires this: its public URL must be HTTPS.

A minimal Caddyfile:

```
your-host {
    reverse_proxy trilium-mcp:8081
}
```

Then set `MCP_BASE_URL=https://your-host` if you use OAuth, and consider restricting accepted hosts with [`MCP_ALLOWED_HOSTS`](security.md#host-allowlist).

Direct `http://<lan-ip>:8081` access without a proxy is fine on a network you trust, with an ETAPI token.

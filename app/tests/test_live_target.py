"""Guard: live tests must only ever target the in-repo throwaway fixture.

The trilium plugin exports TRILIUM_MCP_URL / TRILIUM_ETAPI_TOKEN for a *real*
instance into every shell; if the live tests honored them they would create and
delete notes in someone's actual Trilium.
"""

import importlib

from tests.live import _client


def test_live_tests_ignore_real_instance_env(monkeypatch):
    monkeypatch.setenv("TRILIUM_MCP_URL", "https://real.example/mcp")
    monkeypatch.setenv("TRILIUM_ETAPI_TOKEN", "real-token")
    try:
        client = importlib.reload(_client)
        assert client.MCP_URL == "http://localhost:9091/mcp"
        assert client.TOKEN == (client.REPO_ROOT / "etapi.token").read_text().strip()
    finally:
        monkeypatch.undo()
        importlib.reload(_client)

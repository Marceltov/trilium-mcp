# Contributing

The repo ships a ready-to-run development stack: a throwaway Trilium seeded with the default demo notes, plus the MCP server built from local source.

```bash
git clone https://github.com/Marceltov/trilium-mcp
cd trilium-mcp
docker compose up -d --build
curl http://localhost:9091/health   # -> ok
```

Run the full test suite against a fresh, disposable copy of the seeded instance:

```bash
./run-tests.sh
```

[CONTRIBUTING.md](https://github.com/Marceltov/trilium-mcp/blob/main/CONTRIBUTING.md) in the repo has the details: the seeded instance's credentials, resetting the fixture, running tests by hand, and how tools are generated from the ETAPI spec.

## Documentation

This site is built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) from the `docs/` folder. Preview it locally with live reload:

```bash
uvx --with mkdocs-material mkdocs serve
```

## License

trilium-mcp is licensed under the [GNU Affero General Public License v3.0 or later](https://github.com/Marceltov/trilium-mcp/blob/main/LICENSE). You may use, modify and redistribute it, but any modified version, **including one you run as a network service**, must be released under the same license with its source made available to its users, and the original copyright notice preserved.

# Karakeep as a wiki source

If you keep an [LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) in Trilium (a *Sources* note marked `#llmWikiPart=sources`), the image can also feed it from [Karakeep](https://karakeep.app). Tag a bookmark `trilium` in Karakeep, from the browser extension or the phone's share sheet, and a sync job copies it into *Sources/&lt;year&gt;* as a source note. The wiki's ingest workflow then picks it up like any other source.

The sync uses Karakeep's REST API with one API key. It needs no MCP connection, no OAuth and no public endpoint.

## What a bookmark becomes

Each tagged bookmark becomes one text note under the current year's folder in *Sources*. The sync creates the folder, labelled `#wikiSourceGroup=<year>`, if it doesn't exist yet.

| Bookmark | Note content | Labels |
|---|---|---|
| Link, crawled | Source link, author, publisher and publish date, then the article as Karakeep extracted it | `#karakeepId`, `#sourceUrl`, `#fetchedOn` (crawl date), `#fetchedVia=karakeep` |
| Link, crawl failed | Just the source link: a *link-only source*, which ingest fetches itself | `#karakeepId`, `#sourceUrl` |
| Link, still crawling | Nothing yet; retried on the next run | |
| Text | The text, as paragraphs | `#karakeepId`, `#sourceUrl` if set |
| PDF or image | The text Karakeep extracted; the file stays in Karakeep | `#karakeepId`, `#sourceUrl` if set, `#fetchedOn`, `#fetchedVia=karakeep` |

The bookmark's own note, if you wrote one, is quoted at the top. Images in the article stay links to their original URLs.

After importing, the sync tags the bookmark `trilium-imported`, and skips bookmarks carrying that tag on later runs. A bookmark that already has a note with its `#karakeepId` is never imported twice, even if tagging it failed. Removing `trilium-imported` does not re-import a bookmark while its note exists.

## Running it

The sync ships in the trilium-mcp image. Run it as a second service with a different command, next to the Trilium the wiki lives in:

```yaml
services:
  karakeep-sync:
    image: ghcr.io/marceltov/trilium-mcp:latest
    container_name: trilium-karakeep-sync
    restart: unless-stopped
    command: ["python", "karakeep_sync.py"]
    healthcheck:
      disable: true   # the image's healthcheck probes the MCP server's /health
    environment:
      TRILIUM_SERVER_URL: http://trilium:8080
      TRILIUM_ETAPI_TOKEN: ${TRILIUM_ETAPI_TOKEN}
      KARAKEEP_API_ADDR: https://karakeep.example.com
      KARAKEEP_API_KEY: ${KARAKEEP_API_KEY}
```

Create the Karakeep API key under *Settings → API Keys*, and the ETAPI token under Trilium's *Options → ETAPI*. Keep both in a gitignored `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `TRILIUM_SERVER_URL` | `http://trilium:8080` | Trilium base URL; `/etapi` is appended |
| `TRILIUM_ETAPI_TOKEN` | required | ETAPI token the sync writes with |
| `KARAKEEP_API_ADDR` | required | Karakeep base URL, without `/api/v1` |
| `KARAKEEP_API_KEY` | required | Karakeep API key |
| `KARAKEEP_TAG` | `trilium` | Tag that marks a bookmark for import |
| `KARAKEEP_DONE_TAG` | `trilium-imported` | Tag set once a bookmark is imported |
| `SYNC_INTERVAL` | `900` | Seconds between runs; `0` runs once and exits (non-zero on failure), for cron |

A failed run is logged and retried after the interval. The sync also stops with an error if there isn't exactly one note marked `#llmWikiPart=sources`.

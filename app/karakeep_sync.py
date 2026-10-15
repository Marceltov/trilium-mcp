# SPDX-License-Identifier: AGPL-3.0-or-later
#
# trilium-mcp — Standalone MCP server exposing the Trilium ETAPI over HTTP.
# Copyright (C) 2026 Marcel Bruckner
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

"""Copy tagged Karakeep bookmarks into the LLM wiki's Sources in Trilium.

Runs from the same image as the MCP server (`python karakeep_sync.py`). Every
bookmark carrying KARAKEEP_TAG becomes one source note under
Sources/<year> (the note marked #llmWikiPart=sources), holding the article text
Karakeep already crawled, so the wiki's ingest workflow picks it up like any other
source. The bookmark then gets KARAKEEP_DONE_TAG. A #karakeepId label on the
note makes a rerun idempotent even if tagging the bookmark failed.
"""

import html
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx

from server import etapi_url

log = logging.getLogger("karakeep_sync")

KARAKEEP_ADDR_ENV = "KARAKEEP_API_ADDR"        # e.g. https://karakeep.example.com
KARAKEEP_KEY_ENV = "KARAKEEP_API_KEY"          # Karakeep API key (Settings -> API keys)
KARAKEEP_TAG_ENV = "KARAKEEP_TAG"              # bookmarks to import
KARAKEEP_DONE_TAG_ENV = "KARAKEEP_DONE_TAG"    # set on a bookmark once imported
ETAPI_TOKEN_ENV = "TRILIUM_ETAPI_TOKEN"        # token for the Trilium the wiki lives in
INTERVAL_ENV = "SYNC_INTERVAL"                 # seconds between runs; 0 = run once

DEFAULT_TAG = "trilium"
DEFAULT_DONE_TAG = "trilium-imported"
DEFAULT_INTERVAL = 900
PAGE_SIZE = 50

# Reddit serves crawlers a cookie/login wall (also for .json and old.reddit), so
# Karakeep's capture of a Reddit post is useless. The post's Atom feed still
# answers anonymously, with the post body and its comments.
REDDIT_POST = re.compile(r"^https?://(?:[a-z]+\.)?reddit\.com/r/[^/]+/(?:comments|s)/", re.I)
REDDIT_USER_AGENT = "trilium-karakeep-sync/1.0 (personal wiki importer)"
ATOM = "{http://www.w3.org/2005/Atom}"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def karakeep_client() -> httpx.Client:
    addr = _required_env(KARAKEEP_ADDR_ENV).rstrip("/")
    return httpx.Client(
        base_url=f"{addr}/api/v1",
        headers={"Authorization": f"Bearer {_required_env(KARAKEEP_KEY_ENV)}"},
        timeout=30,
    )


def trilium_client() -> httpx.Client:
    return httpx.Client(
        base_url=etapi_url(),
        headers={"Authorization": _required_env(ETAPI_TOKEN_ENV)},
        timeout=30,
    )


# ---- Karakeep side ----

def find_tag_id(kk: httpx.Client, name: str) -> str | None:
    cursor = None
    while True:
        params = {"nameContains": name}
        if cursor:
            params["cursor"] = cursor
        page = kk.get("/tags", params=params).raise_for_status().json()
        for tag in page["tags"]:
            if tag["name"] == name:
                return tag["id"]
        cursor = page.get("nextCursor")
        if not cursor:
            return None


def tagged_bookmarks(kk: httpx.Client, tag_id: str):
    cursor = None
    while True:
        params = {"includeContent": "true", "limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        page = kk.get(f"/tags/{tag_id}/bookmarks", params=params).raise_for_status().json()
        yield from page["bookmarks"]
        cursor = page.get("nextCursor")
        if not cursor:
            return


def mark_done(kk: httpx.Client, bookmark_id: str, done_tag: str) -> None:
    kk.post(
        f"/bookmarks/{bookmark_id}/tags", json={"tags": [{"tagName": done_tag}]}
    ).raise_for_status()


# ---- Reddit ----

def reddit_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": REDDIT_USER_AGENT}, timeout=30)


def _render_reddit_feed(feed_xml: str) -> str:
    entries = ET.fromstring(feed_xml).findall(f"{ATOM}entry")
    if not entries:
        raise ValueError("Reddit feed has no entries")
    parts = []
    for i, entry in enumerate(entries):
        author = entry.findtext(f"{ATOM}author/{ATOM}name") or "[deleted]"
        body = entry.findtext(f"{ATOM}content") or ""
        if i == 0:
            parts.append(f"<h2>Post by {html.escape(author)}</h2>{body}")
            if len(entries) > 1:
                parts.append("<h2>Comments</h2>")
        else:
            parts.append(f"<h3>{html.escape(author)}</h3>{body}")
    return "".join(parts)


def reddit_capture(rd: httpx.Client, url: str) -> str | None:
    """The post and its comments as HTML from Reddit's feed, or None on failure."""
    try:
        if "/s/" in url:  # app share link: resolve to the canonical post URL
            resp = rd.get(url, follow_redirects=False)
            url = resp.headers.get("location", "")
            if not REDDIT_POST.match(url):
                raise ValueError(f"share link did not resolve to a post: {resp.status_code}")
        feed_url = url.split("?")[0].rstrip("/") + "/.rss"
        resp = rd.get(feed_url, follow_redirects=True)
        if resp.status_code == 429:  # small per-IP budget that resets within a minute
            time.sleep(min(int(resp.headers.get("x-ratelimit-reset", "30") or 30), 60) + 1)
            resp = rd.get(feed_url, follow_redirects=True)
        resp.raise_for_status()
        return _render_reddit_feed(resp.text)
    except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
        log.warning("Reddit feed for %s unavailable: %s", url, exc)
        return None


# ---- Bookmark -> source note ----

def _day(timestamp: str | None) -> str:
    if not timestamp:
        return date.today().isoformat()
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()


def _paragraphs(text: str) -> str:
    blocks = [b.strip() for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    return "".join(
        f"<p>{html.escape(b).replace(chr(10), '<br>')}</p>" for b in blocks
    )


def _link(url: str) -> str:
    u = html.escape(url, quote=True)
    return f'<a href="{u}">{html.escape(url)}</a>'


def render_source(
    bookmark: dict, rd: httpx.Client | None = None
) -> tuple[str, str, list[tuple[str, str]]] | None:
    """(title, html, labels) for a bookmark, or None if it isn't ready yet.

    A link whose crawl is still pending is retried on the next run. A link whose
    crawl produced no article becomes a link-only source, which the wiki's ingest
    workflow knows how to collect. A Reddit post is taken from Reddit's feed
    (via `rd`) instead of Karakeep's capture; if Reddit refuses, the bookmark
    waits for the next run.
    """
    content = bookmark.get("content") or {}
    kind = content.get("type")
    labels = [("karakeepId", bookmark["id"])]
    header = []
    if bookmark.get("note"):
        header.append(
            f"<blockquote><p><strong>Note from the bookmark:</strong></p>"
            f"{_paragraphs(bookmark['note'])}</blockquote>"
        )

    if kind == "link":
        if content.get("crawlStatus") == "pending":
            return None
        url = content["url"]
        title = bookmark.get("title") or content.get("title") or url
        labels.append(("sourceUrl", url))
        meta = [f"Source: {_link(url)}"]
        for key, label in (("author", "Author"), ("publisher", "Publisher")):
            if content.get(key):
                meta.append(f"{label}: {html.escape(content[key])}")
        if content.get("datePublished"):
            meta.append(f"Published: {_day(content['datePublished'])}")
        if REDDIT_POST.match(url) and rd is not None:
            header.append(f"<p>{'<br>'.join(meta[:1])}</p>")  # Karakeep's author/publisher are the login wall's
            article = reddit_capture(rd, url)
            if article:
                labels += [("fetchedOn", date.today().isoformat()), ("fetchedVia", "reddit-rss")]
                return title, "".join(header) + "<hr>" + article, labels
            return None
        header.append(f"<p>{'<br>'.join(meta)}</p>")
        article = content.get("htmlContent")
        if article:
            labels += [
                ("fetchedOn", _day(content.get("crawledAt"))),
                ("fetchedVia", "karakeep"),
            ]
            return title, "".join(header) + "<hr>" + article, labels
        return title, "".join(header), labels

    if kind == "text":
        text = content.get("text") or ""
        title = bookmark.get("title") or text.strip().split("\n", 1)[0][:80] or "Karakeep note"
        if content.get("sourceUrl"):
            labels.append(("sourceUrl", content["sourceUrl"]))
            header.append(f"<p>Source: {_link(content['sourceUrl'])}</p>")
        return title, "".join(header) + _paragraphs(text), labels

    if kind == "asset":
        title = bookmark.get("title") or content.get("fileName") or "Karakeep asset"
        if content.get("sourceUrl"):
            labels.append(("sourceUrl", content["sourceUrl"]))
            header.append(f"<p>Source: {_link(content['sourceUrl'])}</p>")
        name = html.escape(content.get("fileName") or content.get("assetType") or "file")
        header.append(f"<p>Extracted text of {name} (the file itself stays in Karakeep).</p>")
        labels += [("fetchedOn", _day(bookmark.get("createdAt"))), ("fetchedVia", "karakeep")]
        return title, "".join(header) + "<hr>" + _paragraphs(content.get("content") or ""), labels

    log.warning("bookmark %s has unsupported content type %r; skipped", bookmark["id"], kind)
    return None


# ---- Trilium side ----

def search(tr: httpx.Client, query: str, **params) -> list[dict]:
    resp = tr.get("/notes", params={"search": query, **params}).raise_for_status()
    return resp.json()["results"]


def sources_root(tr: httpx.Client) -> str:
    found = search(tr, "#llmWikiPart=sources")
    if len(found) != 1:
        raise RuntimeError(f"expected one note labelled #llmWikiPart=sources, found {len(found)}")
    return found[0]["noteId"]


def add_label(tr: httpx.Client, note_id: str, name: str, value: str = "") -> None:
    tr.post(
        "/attributes", json={"noteId": note_id, "type": "label", "name": name, "value": value}
    ).raise_for_status()


def create_note(tr: httpx.Client, parent_id: str, title: str, content: str) -> str:
    resp = tr.post(
        "/create-note",
        json={"parentNoteId": parent_id, "title": title, "type": "text", "content": content},
    ).raise_for_status()
    return resp.json()["note"]["noteId"]


def year_folder(tr: httpx.Client, root_id: str, year: str) -> str:
    found = [
        n for n in search(tr, f"#wikiSourceGroup={year}", ancestorNoteId=root_id)
        if root_id in n["parentNoteIds"]
    ]
    if found:
        return found[0]["noteId"]
    note_id = create_note(tr, root_id, year, "")
    add_label(tr, note_id, "wikiSourceGroup", year)
    add_label(tr, note_id, "iconClass", "bx bx-folder")
    log.info("created year folder %s (%s)", year, note_id)
    return note_id


def already_imported(tr: httpx.Client, root_id: str, bookmark_id: str) -> bool:
    return bool(search(tr, f'#karakeepId="{bookmark_id}"', ancestorNoteId=root_id))


# ---- One run ----

def sync_once(
    kk: httpx.Client, tr: httpx.Client, tag: str, done_tag: str, rd: httpx.Client | None = None
) -> int:
    """Import every pending bookmark; return how many notes were created."""
    tag_id = find_tag_id(kk, tag)
    if tag_id is None:
        log.info("no Karakeep tag %r yet; nothing to import", tag)
        return 0
    root_id = sources_root(tr)
    created = 0
    for bookmark in tagged_bookmarks(kk, tag_id):
        if any(t["name"] == done_tag for t in bookmark.get("tags", [])):
            continue
        if already_imported(tr, root_id, bookmark["id"]):
            mark_done(kk, bookmark["id"], done_tag)
            continue
        rendered = render_source(bookmark, rd)
        if rendered is None:
            continue
        title, content, labels = rendered
        folder = year_folder(tr, root_id, str(date.today().year))
        note_id = create_note(tr, folder, title, content)
        for name, value in labels:
            add_label(tr, note_id, name, value)
        mark_done(kk, bookmark["id"], done_tag)
        created += 1
        log.info("imported %r as %s", title, note_id)
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tag = os.environ.get(KARAKEEP_TAG_ENV, DEFAULT_TAG)
    done_tag = os.environ.get(KARAKEEP_DONE_TAG_ENV, DEFAULT_DONE_TAG)
    interval = int(os.environ.get(INTERVAL_ENV, DEFAULT_INTERVAL))
    with karakeep_client() as kk, trilium_client() as tr, reddit_client() as rd:
        while True:
            try:
                count = sync_once(kk, tr, tag, done_tag, rd)
                log.info("run finished: %d new source(s)", count)
            except (httpx.HTTPError, RuntimeError) as exc:
                log.error("run failed: %s", exc)
                if interval == 0:
                    sys.exit(1)
            if interval == 0:
                return
            time.sleep(interval)


if __name__ == "__main__":
    main()

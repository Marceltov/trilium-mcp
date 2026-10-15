"""karakeep_sync against in-memory fakes of the Karakeep and Trilium APIs."""

import json
from datetime import date

import httpx
import pytest

import karakeep_sync as ks

SOURCES = "srcRoot"
YEAR = str(date.today().year)


def link_bookmark(bid, **content):
    return {
        "id": bid,
        "title": None,
        "note": None,
        "tags": [{"id": "t-wiki", "name": "wiki", "attachedBy": "human"}],
        "createdAt": "2026-10-01T08:00:00.000Z",
        "content": {
            "type": "link",
            "url": f"https://example.com/{bid}",
            "title": f"Article {bid}",
            "crawlStatus": "success",
            "crawledAt": "2026-10-02T09:30:00.000Z",
            "htmlContent": f"<p>Body of {bid}</p>",
            **content,
        },
    }


class FakeKarakeep:
    def __init__(self, bookmarks, tags=("wiki",)):
        self.bookmarks = bookmarks
        self.tags = [{"id": f"t-{n}", "name": n} for n in tags]
        self.attached = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer kk-key"
        path = request.url.path.removeprefix("/api/v1")
        if path == "/tags":
            needle = request.url.params["nameContains"]
            return httpx.Response(200, json={
                "tags": [t for t in self.tags if needle in t["name"]], "nextCursor": None,
            })
        if path == "/tags/t-wiki/bookmarks":
            if request.url.params.get("cursor") == "p2":
                return httpx.Response(200, json={"bookmarks": self.bookmarks[1:], "nextCursor": None})
            return httpx.Response(200, json={"bookmarks": self.bookmarks[:1], "nextCursor": "p2"})
        if request.method == "POST" and path.endswith("/tags"):
            bid = path.split("/")[2]
            self.attached.append((bid, json.loads(request.content)["tags"][0]["tagName"]))
            return httpx.Response(200, json={"attached": []})
        return httpx.Response(404)


class FakeTrilium:
    def __init__(self, with_year=True):
        self.notes = {SOURCES: {"title": "Sources", "parent": None, "labels": [("llmWikiPart", "sources")], "content": ""}}
        if with_year:
            self.notes["year1"] = {"title": YEAR, "parent": SOURCES, "labels": [("wikiSourceGroup", YEAR)], "content": ""}
        self.counter = 0

    def _matches(self, query, labels):
        name, _, value = query.lstrip("#").partition("=")
        return (name, value.strip('"')) in labels

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "etapi-token"
        path = request.url.path.removeprefix("/etapi")
        if path == "/notes":
            hits = [
                {"noteId": nid, "parentNoteIds": [n["parent"]]}
                for nid, n in self.notes.items()
                if self._matches(request.url.params["search"], n["labels"])
            ]
            return httpx.Response(200, json={"results": hits})
        body = json.loads(request.content)
        if path == "/create-note":
            self.counter += 1
            nid = f"new{self.counter}"
            self.notes[nid] = {"title": body["title"], "parent": body["parentNoteId"], "labels": [], "content": body["content"]}
            return httpx.Response(201, json={"note": {"noteId": nid}})
        if path == "/attributes":
            self.notes[body["noteId"]]["labels"].append((body["name"], body["value"]))
            return httpx.Response(201, json={})
        return httpx.Response(404)

    def created(self):
        return {nid: n for nid, n in self.notes.items() if nid.startswith("new")}


def run(kk_fake, tr_fake):
    kk = httpx.Client(base_url="http://kk/api/v1", headers={"Authorization": "Bearer kk-key"},
                      transport=httpx.MockTransport(kk_fake.handler))
    tr = httpx.Client(base_url="http://trilium/etapi", headers={"Authorization": "etapi-token"},
                      transport=httpx.MockTransport(tr_fake.handler))
    return ks.sync_once(kk, tr, "wiki", "wiki-imported")


def test_imports_link_bookmarks_across_pages_into_year_folder():
    kk = FakeKarakeep([link_bookmark("b1"), link_bookmark("b2")])
    tr = FakeTrilium()
    assert run(kk, tr) == 2
    notes = tr.created()
    assert {n["title"] for n in notes.values()} == {"Article b1", "Article b2"}
    note = next(n for n in notes.values() if n["title"] == "Article b1")
    assert note["parent"] == "year1"
    assert "<p>Body of b1</p>" in note["content"]
    assert 'href="https://example.com/b1"' in note["content"]
    assert ("karakeepId", "b1") in note["labels"]
    assert ("sourceUrl", "https://example.com/b1") in note["labels"]
    assert ("fetchedOn", "2026-10-02") in note["labels"]
    assert ("fetchedVia", "karakeep") in note["labels"]
    assert sorted(kk.attached) == [("b1", "wiki-imported"), ("b2", "wiki-imported")]


def test_rerun_is_idempotent():
    kk = FakeKarakeep([link_bookmark("b1")])
    tr = FakeTrilium()
    run(kk, tr)
    kk.attached.clear()
    assert run(kk, tr) == 0
    assert len(tr.created()) == 1
    # Already in Trilium but not yet tagged in Karakeep: tag it, don't duplicate.
    assert kk.attached == [("b1", "wiki-imported")]


def test_skips_bookmarks_already_tagged_done():
    bm = link_bookmark("b1")
    bm["tags"].append({"id": "t-done", "name": "wiki-imported", "attachedBy": "human"})
    kk = FakeKarakeep([bm])
    tr = FakeTrilium()
    assert run(kk, tr) == 0
    assert kk.attached == []


def test_pending_crawl_waits_for_next_run():
    kk = FakeKarakeep([link_bookmark("b1", crawlStatus="pending", htmlContent=None)])
    tr = FakeTrilium()
    assert run(kk, tr) == 0
    assert kk.attached == []


def test_failed_crawl_becomes_link_only_source():
    kk = FakeKarakeep([link_bookmark("b1", crawlStatus="failure", htmlContent=None)])
    tr = FakeTrilium()
    assert run(kk, tr) == 1
    (note,) = tr.created().values()
    assert 'href="https://example.com/b1"' in note["content"]
    assert not any(name == "fetchedVia" for name, _ in note["labels"])


def test_creates_year_folder_when_missing():
    kk = FakeKarakeep([link_bookmark("b1")])
    tr = FakeTrilium(with_year=False)
    run(kk, tr)
    folder = next(n for n in tr.created().values() if n["title"] == YEAR)
    assert folder["parent"] == SOURCES
    assert ("wikiSourceGroup", YEAR) in folder["labels"]
    article = next(n for n in tr.created().values() if n["title"] == "Article b1")
    assert tr.notes[article["parent"]] is folder


def test_missing_tag_is_a_no_op():
    kk = FakeKarakeep([link_bookmark("b1")], tags=("other",))
    tr = FakeTrilium()
    assert run(kk, tr) == 0
    assert tr.created() == {}


def test_text_bookmark_is_escaped():
    bm = {"id": "t1", "title": None, "note": "why I saved it", "tags": [],
          "content": {"type": "text", "text": "First line <b>\n\nSecond para"}}
    title, content, labels = ks.render_source(bm)
    assert title == "First line <b>"
    assert "&lt;b&gt;" in content and "<p>Second para</p>" in content
    assert "why I saved it" in content
    assert labels == [("karakeepId", "t1")]


def test_asset_bookmark_uses_extracted_text():
    bm = {"id": "a1", "title": None, "note": None, "tags": [], "createdAt": "2026-09-01T00:00:00Z",
          "content": {"type": "asset", "assetType": "pdf", "assetId": "x", "fileName": "paper.pdf",
                      "content": "Extracted text"}}
    title, content, labels = ks.render_source(bm)
    assert title == "paper.pdf"
    assert "<p>Extracted text</p>" in content
    assert ("fetchedOn", "2026-09-01") in labels


def test_unknown_content_type_skipped():
    assert ks.render_source({"id": "u1", "content": {"type": "unknown"}}) is None


def test_sources_root_must_be_unique():
    tr = FakeTrilium()
    tr.notes["dup"] = {"title": "Sources 2", "parent": None, "labels": [("llmWikiPart", "sources")], "content": ""}
    kk = FakeKarakeep([link_bookmark("b1")])
    with pytest.raises(RuntimeError, match="found 2"):
        run(kk, tr)


REDDIT_FEED = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>A post : selfhosted</title>
<entry><author><name>/u/op</name></author><content type="html">&lt;div class="md"&gt;&lt;p&gt;Post body&lt;/p&gt;&lt;/div&gt;</content></entry>
<entry><author><name>/u/commenter</name></author><content type="html">&lt;p&gt;Nice &amp;amp; useful&lt;/p&gt;</content></entry>
</feed>"""
POST_URL = "https://www.reddit.com/r/selfhosted/comments/abc123/a_post/"


def reddit(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def reddit_bookmark(url=POST_URL):
    return link_bookmark("r1", url=url, title="A post", author="Log In", publisher="Log In",
                         htmlContent="<p>Let us know your cookie preferences</p>")


def test_reddit_post_comes_from_its_feed_not_the_login_wall():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        assert "Authorization" not in request.headers
        return httpx.Response(200, text=REDDIT_FEED)

    title, content, labels = ks.render_source(reddit_bookmark(), reddit(handler))
    assert seen == ["https://www.reddit.com/r/selfhosted/comments/abc123/a_post/.rss"]
    assert "cookie preferences" not in content and "Log In" not in content
    assert '<h2>Post by /u/op</h2><div class="md"><p>Post body</p></div>' in content
    assert "<h3>/u/commenter</h3><p>Nice &amp; useful</p>" in content
    assert ("fetchedVia", "reddit-rss") in labels


def test_reddit_share_link_is_resolved_first():
    def handler(request):
        if "/s/" in request.url.path:
            return httpx.Response(301, headers={"location": POST_URL + "?share_id=x&utm_source=share"})
        assert str(request.url) == POST_URL + ".rss"
        return httpx.Response(200, text=REDDIT_FEED)

    _, content, _ = ks.render_source(
        reddit_bookmark("https://www.reddit.com/r/selfhosted/s/clJwh8lJvL"), reddit(handler))
    assert "Post body" in content


def test_reddit_refusal_waits_for_next_run():
    rd = reddit(lambda request: httpx.Response(403, text="blocked"))
    assert ks.render_source(reddit_bookmark(), rd) is None


def test_reddit_rate_limit_is_retried_once(monkeypatch):
    monkeypatch.setattr(ks.time, "sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"x-ratelimit-reset": "5"})
        return httpx.Response(200, text=REDDIT_FEED)

    _, content, _ = ks.render_source(reddit_bookmark(), reddit(handler))
    assert len(calls) == 2 and "Post body" in content

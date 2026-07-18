"""Signal sources. Standard-library only (urllib + xml) so there are no
third-party dependencies to bundle for Lambda.

Every source returns a list of normalized dicts:
    {"id", "title", "url", "source", "published", "summary"}
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
import hashlib
import re
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import config

_UA = {"User-Agent": "sift-agent/1.0 (+https://builder.aws.com)"}
_TIMEOUT = 12


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _get_json(url: str):
    return json.loads(_get(url).decode("utf-8", "replace"))


def _item_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]


def _clean(text: str, limit: int = 400) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fetch_hackernews(limit: int) -> list[dict]:
    """Top Hacker News stories via the public Firebase API (no key)."""
    out: list[dict] = []
    try:
        ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json")[: limit * 2]
        for sid in ids:
            if len(out) >= limit:
                break
            try:
                it = _get_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            except Exception:
                continue
            if not it or it.get("type") != "story" or not it.get("title"):
                continue
            url = it.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            out.append({
                "id": _item_id(url, it["title"]),
                "title": it["title"],
                "url": url,
                "source": "hackernews",
                "published": datetime.fromtimestamp(it.get("time", 0), timezone.utc).isoformat(),
                "summary": f"{it.get('score', 0)} points, {it.get('descendants', 0)} comments",
            })
    except Exception as e:  # pragma: no cover - network best effort
        return [{"id": "hn-error", "title": "(hackernews fetch failed)", "url": "",
                 "source": "hackernews", "published": "", "summary": str(e), "error": True}]
    return out


def fetch_rss(url: str, limit: int) -> list[dict]:
    """Parse an RSS 2.0 or Atom feed with the stdlib XML parser."""
    out: list[dict] = []
    try:
        root = ET.fromstring(_get(url))
    except Exception as e:  # pragma: no cover
        return [{"id": f"rss-error-{_item_id(url, '')}", "title": f"(rss fetch failed: {url})",
                 "url": url, "source": "rss", "published": "", "summary": str(e), "error": True}]

    # RSS 2.0
    items = root.findall(".//item")
    if items:
        for it in items[:limit]:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or ""
            pub = it.findtext("pubDate") or ""
            if not title:
                continue
            out.append({
                "id": _item_id(link, title), "title": title, "url": link,
                "source": _feed_name(url), "published": pub, "summary": _clean(desc),
            })
        return out

    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for it in root.findall(".//a:entry", ns)[:limit]:
        title = (it.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = it.find("a:link", ns)
        link = link_el.get("href") if link_el is not None else ""
        summ = it.findtext("a:summary", default="", namespaces=ns) or ""
        pub = it.findtext("a:updated", default="", namespaces=ns) or ""
        if not title:
            continue
        out.append({
            "id": _item_id(link, title), "title": title, "url": link,
            "source": _feed_name(url), "published": pub, "summary": _clean(summ),
        })
    return out


def _feed_name(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    return f"rss:{host}"


def fetch_google_news(topics: list[str], limit: int) -> list[dict]:
    """Topic-driven news across the whole web via Google News RSS search.

    This is what makes each user's brief actually follow the topics they picked,
    instead of being confined to a fixed handful of feeds. One query, any source
    Google indexes (Reuters, Bloomberg, trade press, blogs, ...).
    """
    topics = [t for t in (topics or []) if t.strip()]
    if not topics:
        return []
    query = " OR ".join(f'"{t.strip()}"' for t in topics[:8])
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    items = fetch_rss(url, limit)
    for it in items:
        if not it.get("error"):
            it["source"] = "google-news"
    return items


def fetch_github_trending(days: int, limit: int) -> list[dict]:
    """Recently created, fast-rising repos via the GitHub search API (no auth)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = urllib.parse.quote(f"created:>{since}")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={limit}"
    out: list[dict] = []
    try:
        data = _get_json(url)
        for repo in data.get("items", [])[:limit]:
            out.append({
                "id": _item_id(repo["html_url"], repo["full_name"]),
                "title": f"{repo['full_name']} — {repo.get('description') or ''}".strip(" —"),
                "url": repo["html_url"],
                "source": "github-trending",
                "published": repo.get("created_at", ""),
                "summary": f"{repo.get('stargazers_count', 0)}★ new, lang={repo.get('language')}",
            })
    except Exception as e:  # pragma: no cover
        return [{"id": "gh-error", "title": "(github fetch failed)", "url": "",
                 "source": "github-trending", "published": "", "summary": str(e), "error": True}]
    return out


def gather_all() -> list[dict]:
    """Pull every configured source and return a de-duplicated, clean list."""
    items: list[dict] = []
    items += fetch_hackernews(config.PER_SOURCE_LIMIT)
    items += fetch_google_news(config.TOPICS, config.PER_SOURCE_LIMIT * 2)
    for feed in config.RSS_FEEDS:
        items += fetch_rss(feed, config.PER_SOURCE_LIMIT)
    items += fetch_github_trending(config.GITHUB_TRENDING_DAYS, config.PER_SOURCE_LIMIT)

    seen: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        # Drop dead-feed error markers so a flaky source never pollutes a brief.
        if it.get("error") or not it.get("url"):
            continue
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        deduped.append(it)
    return deduped

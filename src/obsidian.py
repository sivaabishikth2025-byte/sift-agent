"""Obsidian integration via a Git-synced vault (the standard cloud-friendly way).

A user connects a GitHub repo that their Obsidian vault syncs to (via the
"Obsidian Git" community plugin). Sift then:
  * uses a small JSON index in the vault as its long-term MEMORY,
  * writes human-readable Markdown notes into the vault (one note per story,
    one note per daily brief) with YAML frontmatter and [[wikilinks]],
  * tracks each story over time so it only surfaces NEW stories or MATERIAL
    UPDATES to a story it already knows — and stays silent otherwise.

Reads/writes go through the GitHub Contents API (stdlib urllib only), so it runs
in Lambda with no git binary and no extra dependencies.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

import config


def content_hash(title: str, summary: str) -> str:
    # Hash the stable story identity only. We deliberately drop volatile bits
    # like Hacker News point/comment counts so a score bump is NOT mistaken for
    # a material update — a story is "updated" only if its substance changes.
    stable = re.sub(r"\d+\s*(points?|comments?)", "", summary or "", flags=re.I)
    stable = re.sub(r"\s+", " ", stable).strip()
    return hashlib.sha1(f"{title}|{stable}".encode("utf-8")).hexdigest()[:12]


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "untitled"


class GitHubVault:
    """Minimal GitHub Contents API client for a repo that backs an Obsidian vault."""

    def __init__(self, repo: str, token: str, branch: str = "main", base: str = "Sift"):
        self.repo = repo
        self.token = token
        self.branch = branch
        self.base = base.strip("/")
        self._api = f"https://api.github.com/repos/{repo}/contents"

    def _request(self, method: str, path: str, data: dict | None = None):
        url = f"{self._api}/{path}"
        if method == "GET":
            url += f"?ref={self.branch}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "sift-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def read(self, path: str) -> tuple[str | None, str | None]:
        resp = self._request("GET", path)
        if not resp or "content" not in resp:
            return None, None
        text = base64.b64decode(resp["content"]).decode("utf-8", "replace")
        return text, resp["sha"]

    def write(self, path: str, text: str, message: str):
        _, sha = self.read(path)
        data = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            data["sha"] = sha
        self._request("PUT", path, data)


class ObsidianMemory:
    """Long-term memory + note writer backed by an Obsidian (GitHub) vault."""

    def __init__(self, vault: GitHubVault):
        self.vault = vault
        self.index_path = f"{vault.base}/.sift-index.json"
        text, _ = vault.read(self.index_path)
        self._data = json.loads(text) if text else {"stories": {}, "theses": []}

    # -- memory interface ----------------------------------------------------
    def known_ids(self) -> set[str]:
        return set(self._data["stories"].keys())

    def known_index(self) -> dict[str, str]:
        """id -> last-seen content hash, for detecting material updates."""
        return {sid: s.get("hash", "") for sid, s in self._data["stories"].items()}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        q = (query or "").lower()
        scored = []
        for s in self._data["stories"].values():
            hay = f"{s.get('title','')} {s.get('note','')}".lower()
            score = sum(1 for w in q.split() if w and w in hay)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    def recent_theses(self, limit: int = 3) -> list[dict]:
        return self._data["theses"][-limit:]

    def remember_items(self, items: list[dict]):
        now = int(time.time())
        for it in items:
            sid = it["id"]
            existing = self._data["stories"].get(sid)
            h = it.get("hash") or content_hash(it.get("title", ""), it.get("note", ""))
            if existing:
                existing["hash"] = h
                existing["last_update"] = now
                existing["updates"] = existing.get("updates", 0) + 1
            else:
                self._data["stories"][sid] = {
                    "id": sid, "title": it.get("title", ""), "url": it.get("url", ""),
                    "note": it.get("note", ""), "hash": h,
                    "first_seen": now, "last_update": now, "updates": 0,
                }
            self._write_story_note(self._data["stories"][sid])
        self._save()

    def remember_thesis(self, thesis: str, confidence: str):
        self._data["theses"].append(
            {"ts": int(time.time()), "thesis": thesis, "confidence": confidence})
        self._save()

    def mark_seen(self, items: list[dict]):
        """Record every item the agent has SEEN (not just featured) so a story
        is never resurfaced. Does not write story notes for these."""
        now = int(time.time())
        changed = False
        for it in items:
            sid = it["id"]
            if sid in self._data["stories"]:
                continue
            self._data["stories"][sid] = {
                "id": sid, "title": it.get("title", ""), "url": it.get("url", ""),
                "note": it.get("note") or it.get("summary", ""),
                "hash": it.get("hash", ""), "first_seen": now, "last_update": now,
                "updates": 0, "seen_only": True,
            }
            changed = True
        if changed:
            self._save()

    # -- note writing --------------------------------------------------------
    def write_brief_note(self, title: str, markdown_body: str):
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"{self.vault.base}/Briefs/{date}.md"
        front = (f"---\ntitle: \"{title}\"\ndate: {date}\ntags: [sift, brief]\n---\n\n")
        self.vault.write(path, front + markdown_body + "\n", f"sift: brief {date}")

    def _write_story_note(self, s: dict):
        path = f"{self.vault.base}/Stories/{_slug(s['title'])}.md"
        existing_text, _ = self.vault.read(path)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if existing_text:
            updated = re.sub(r"updates: \d+", f"updates: {s.get('updates', 0)}", existing_text)
            updated += f"\n- {stamp}: seen again — {s.get('note','')}"
            self.vault.write(path, updated, f"sift: update story {s['title'][:40]}")
        else:
            front = (f"---\ntitle: \"{s['title']}\"\nurl: {s.get('url','')}\n"
                     f"first_seen: {s.get('first_seen')}\nupdates: {s.get('updates',0)}\n"
                     f"tags: [sift, story]\n---\n\n")
            body = (f"# {s['title']}\n\n[Source]({s.get('url','')})\n\n"
                    f"## Timeline\n- {stamp}: first reported — {s.get('note','')}\n")
            self.vault.write(path, front + body, f"sift: new story {s['title'][:40]}")

    def _save(self):
        self.vault.write(self.index_path, json.dumps(self._data, indent=2),
                         "sift: update memory index")


def get_vault() -> GitHubVault | None:
    if config.OBSIDIAN_REPO and config.GITHUB_TOKEN:
        return GitHubVault(config.OBSIDIAN_REPO, config.GITHUB_TOKEN,
                           branch=config.OBSIDIAN_BRANCH, base=config.OBSIDIAN_BASE)
    return None

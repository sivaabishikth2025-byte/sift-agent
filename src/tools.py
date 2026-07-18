"""The agent's tools, in Amazon Bedrock Converse `toolSpec` format, plus a
dispatcher that executes them against a live run context (sources, memory,
and the report publisher).

The model decides which tools to call and in what order; this module just
makes the capabilities available and safe.
"""
from __future__ import annotations

import sources
import report


# --- Tool schemas exposed to the model -------------------------------------
TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "fetch_signals",
            "description": (
                "Pull the latest items from all configured public sources "
                "(Hacker News, RSS/Atom feeds, GitHub trending). Returns a "
                "de-duplicated list with an 'is_new' flag indicating whether "
                "the item has been seen in a previous run."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max items to return (<=40)."}
                },
            }},
        }
    },
    {
        "toolSpec": {
            "name": "recall_memory",
            "description": (
                "Search the analyst's long-term memory for previously seen "
                "items and read the most recent theses. Use this to judge what "
                "is genuinely new and how the picture is evolving."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search memory for."}
                },
                "required": ["query"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "save_findings",
            "description": (
                "Persist which item ids have now been reported, plus today's "
                "one-line thesis and your confidence. This is how the analyst "
                "compounds knowledge so it never repeats itself."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "new_item_ids": {"type": "array", "items": {"type": "string"},
                                     "description": "Item ids you are reporting as new."},
                    "thesis": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["thesis", "confidence"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "publish_brief",
            "description": (
                "Publish the final brief (Markdown) as a dated HTML page the "
                "user will find waiting for them. Call this exactly once, last."
            ),
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "markdown_body": {"type": "string"},
                },
                "required": ["title", "markdown_body"],
            }},
        }
    },
]


class ToolContext:
    """Holds live handles + a cache of what was fetched this run."""

    def __init__(self, memory, reporter):
        self.memory = memory
        self.reporter = reporter
        self.fetched: dict[str, dict] = {}
        self.published_location: str | None = None
        self.stats: dict = {}

    # -- tool implementations ------------------------------------------------
    def fetch_signals(self, limit: int = 30) -> dict:
        limit = max(1, min(int(limit or 30), 40))
        known = self.memory.known_ids()
        items = sources.gather_all()
        result = []
        for it in items[:limit]:
            self.fetched[it["id"]] = it
            result.append({
                "id": it["id"], "title": it["title"], "url": it["url"],
                "source": it["source"], "summary": it["summary"],
                "is_new": it["id"] not in known,
            })
        new_count = sum(1 for r in result if r["is_new"])
        self.stats = {"scanned": len(result), "new": new_count, "in_memory": len(known)}
        return {"count": len(result), "new_count": new_count, "items": result}

    def recall_memory(self, query: str) -> dict:
        hits = self.memory.search(query, limit=10)
        theses = self.memory.recent_theses(limit=3)
        return {
            "matches": [{"title": h.get("title", ""), "url": h.get("url", ""),
                         "note": h.get("note", "")} for h in hits],
            "recent_theses": [{"thesis": t.get("thesis", ""),
                               "confidence": t.get("confidence", "")} for t in theses],
        }

    def save_findings(self, thesis: str, confidence: str, new_item_ids: list | None = None) -> dict:
        new_item_ids = new_item_ids or []
        to_store = []
        for iid in new_item_ids:
            it = self.fetched.get(iid)
            if it:
                to_store.append({"id": it["id"], "title": it["title"],
                                 "url": it["url"], "note": it["summary"]})
        if to_store:
            self.memory.remember_items(to_store)
        self.memory.remember_thesis(thesis, confidence)
        return {"stored_items": len(to_store), "thesis_saved": True}

    def publish_brief(self, title: str, markdown_body: str) -> dict:
        location = self.reporter.publish(title, markdown_body, stats=self.stats)
        self.published_location = location
        return {"published": True, "location": location}

    # -- dispatch ------------------------------------------------------------
    def dispatch(self, name: str, args: dict) -> dict:
        fn = {
            "fetch_signals": self.fetch_signals,
            "recall_memory": self.recall_memory,
            "save_findings": self.save_findings,
            "publish_brief": self.publish_brief,
        }.get(name)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            return fn(**(args or {}))
        except TypeError as e:
            return {"error": f"bad arguments for {name}: {e}"}

"""Persistent memory so the analyst compounds knowledge across runs.

This is what separates Sift from a "resummarize the headlines every day" bot:
it records which items it has already reported, and the thesis it held last
time, so each run only surfaces genuinely new signal and can explain how the
picture is evolving.

Two interchangeable backends:
  * DynamoDBMemory  - used in AWS (when SIFT_MEMORY_TABLE is set)
  * LocalMemory     - a JSON file on disk (used for local dev / demos)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import config


class LocalMemory:
    def __init__(self, root: Path):
        self.path = root / "memory.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._data = json.loads(self.path.read_text("utf-8"))
        else:
            self._data = {"items": {}, "theses": []}

    def _flush(self):
        self.path.write_text(json.dumps(self._data, indent=2), "utf-8")

    def known_ids(self) -> set[str]:
        return set(self._data["items"].keys())

    def search(self, query: str, limit: int = 10) -> list[dict]:
        q = (query or "").lower()
        scored = []
        for item in self._data["items"].values():
            hay = f"{item.get('title','')} {item.get('note','')}".lower()
            score = sum(1 for w in q.split() if w and w in hay)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in scored[:limit]]

    def recent_theses(self, limit: int = 3) -> list[dict]:
        return self._data["theses"][-limit:]

    def remember_items(self, items: list[dict]):
        now = int(time.time())
        for it in items:
            self._data["items"][it["id"]] = {
                "id": it["id"], "title": it.get("title", ""),
                "url": it.get("url", ""), "note": it.get("note", ""),
                "first_seen": now,
            }
        self._flush()

    def remember_thesis(self, thesis: str, confidence: str):
        self._data["theses"].append(
            {"ts": int(time.time()), "thesis": thesis, "confidence": confidence}
        )
        self._flush()


class DynamoDBMemory:
    def __init__(self, table_name: str):
        import boto3
        self._ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        self._t = self._ddb.Table(table_name)

    def known_ids(self) -> set[str]:
        ids: set[str] = set()
        kwargs = {"ProjectionExpression": "pk"}
        while True:
            resp = self._t.scan(**kwargs)
            ids.update(i["pk"] for i in resp.get("Items", []) if i["pk"].startswith("item#"))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return {i.split("item#", 1)[1] for i in ids}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        q = (query or "").lower()
        resp = self._t.scan(
            FilterExpression="begins_with(pk, :p)",
            ExpressionAttributeValues={":p": "item#"},
        )
        scored = []
        for item in resp.get("Items", []):
            hay = f"{item.get('title','')} {item.get('note','')}".lower()
            score = sum(1 for w in q.split() if w and w in hay)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in scored[:limit]]

    def recent_theses(self, limit: int = 3) -> list[dict]:
        # Theses are stored with pk="thesis#<ts>"; a scan is fine at this scale.
        resp = self._t.scan(
            FilterExpression="begins_with(pk, :p)",
            ExpressionAttributeValues={":p": "thesis#"},
        )
        items = sorted(resp.get("Items", []), key=lambda x: x.get("ts", 0))
        return items[-limit:]

    def remember_items(self, items: list[dict]):
        now = int(time.time())
        with self._t.batch_writer() as bw:
            for it in items:
                bw.put_item(Item={
                    "pk": f"item#{it['id']}", "title": it.get("title", ""),
                    "url": it.get("url", ""), "note": it.get("note", ""),
                    "first_seen": now,
                })

    def remember_thesis(self, thesis: str, confidence: str):
        ts = int(time.time())
        self._t.put_item(Item={
            "pk": f"thesis#{ts}", "ts": ts, "thesis": thesis, "confidence": confidence,
        })


def get_memory():
    if config.MEMORY_TABLE:
        return DynamoDBMemory(config.MEMORY_TABLE)
    return LocalMemory(config.LOCAL_ROOT)

"""Per-user preferences API (HTTP API v2 + Cognito JWT authorizer).

Routes:
  GET  /prefs  -> return the signed-in user's preferences (or sensible defaults)
  PUT  /prefs  -> save the signed-in user's preferences

The user identity comes from the verified Cognito JWT claims, so a user can only
ever read/write their own row. Preferences drive each user's personal brief.
"""
from __future__ import annotations

import json
import os
import time

import boto3

TABLE = os.environ["USERS_TABLE"]
_ddb = boto3.resource("dynamodb")
_t = _ddb.Table(TABLE)

DEFAULTS = {
    "topics": "AI agents, AWS, serverless, developer tooling, LLMs",
    "feeds": "https://aws.amazon.com/blogs/aws/feed/,https://hnrss.org/frontpage",
    "schedule": "06:00",
    "obsidian_repo": "",
    "enabled": True,
}

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type,authorization",
    "Access-Control-Allow-Methods": "GET,PUT,OPTIONS",
    "Content-Type": "application/json",
}


def _resp(code: int, body: dict):
    return {"statusCode": code, "headers": _CORS, "body": json.dumps(body)}


def _claims(event: dict) -> dict:
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]
    except KeyError:
        return {}


def lambda_handler(event, context):
    route = event.get("routeKey", "")
    if route.startswith("OPTIONS"):
        return _resp(200, {})

    claims = _claims(event)
    user_id = claims.get("sub")
    email = claims.get("email", "")
    if not user_id:
        return _resp(401, {"error": "unauthenticated"})

    if route == "GET /prefs":
        item = _t.get_item(Key={"userId": user_id}).get("Item")
        prefs = {**DEFAULTS, **(item or {})}
        prefs.pop("userId", None)
        prefs["email"] = email
        return _resp(200, prefs)

    if route == "PUT /prefs":
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return _resp(400, {"error": "invalid json"})
        item = {
            "userId": user_id,
            "email": email,
            "topics": str(body.get("topics", DEFAULTS["topics"]))[:500],
            "feeds": str(body.get("feeds", DEFAULTS["feeds"]))[:1000],
            "schedule": str(body.get("schedule", DEFAULTS["schedule"]))[:5],
            "obsidian_repo": str(body.get("obsidian_repo", ""))[:120],
            "enabled": bool(body.get("enabled", True)),
            "updated_at": int(time.time()),
        }
        _t.put_item(Item=item)
        item.pop("userId", None)
        return _resp(200, {"saved": True, "prefs": item})

    return _resp(404, {"error": f"no route {route}"})

"""Lambda entry point. Orchestrates one full autonomous run:

    EventBridge Scheduler (or an event) -> this handler -> agent loop -> brief

Also runnable directly (`python src/handler.py`) for local testing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import config
import agent
import tools
import notify
from llm import get_llm
from memory import get_memory
from report import Reporter

log = logging.getLogger()
log.setLevel(logging.INFO)


def _apply_user_prefs(user: dict) -> tuple[str, str, str]:
    """Override the global config with one signed-up user's preferences.

    Returns (prefix, to_email, user_id) for per-user brief output + delivery.
    """
    uid = user.get("userId") or user.get("sub") or "user"
    if user.get("topics"):
        config.TOPICS = [t.strip() for t in str(user["topics"]).split(",") if t.strip()]
    if user.get("feeds"):
        config.RSS_FEEDS = [u.strip() for u in str(user["feeds"]).split(",") if u.strip()]
    config.MEMORY_NS = f"u/{uid}#"
    return f"u/{uid}", user.get("email", ""), uid


def run_once(event: dict | None = None) -> dict:
    event = event or {}
    user = event.get("user") or {}
    prefix, to_email = "", None
    if user:
        prefix, to_email, uid = _apply_user_prefs(user)
        log.info("Per-user run for %s (%s)", uid, to_email)
    log.info("Sift run starting: %s", json.dumps(config.summary()))

    llm = get_llm()
    memory = get_memory()
    reporter = Reporter(prefix=prefix)
    ctx = tools.ToolContext(memory, reporter)

    now = datetime.now(timezone.utc).strftime("%A %Y-%m-%d %H:%M UTC")
    trigger = event.get("trigger", "schedule")
    user_prompt = (
        f"It is {now}. This is an unattended '{trigger}' run. "
        f"Produce today's brief for these topics: {', '.join(config.TOPICS)}. "
        "Follow your standard procedure and publish exactly one brief."
    )

    result = agent.run(llm, ctx, tools.TOOL_SPECS, user_prompt)

    # Record everything seen this run (not just featured items) so no story is
    # ever resurfaced. This is what makes the watch go quiet when nothing's new.
    if ctx.fetched and hasattr(memory, "mark_seen"):
        try:
            memory.mark_seen(list(ctx.fetched.values()))
        except Exception as e:
            log.warning("mark_seen failed: %s", e)

    log.info("Sift run complete. Published to: %s", result.get("published"))

    if result.get("published"):
        try:
            title = result.get("title") or "Your Sift brief is ready"
            summary = result.get("thesis") or "A new brief is ready."
            notif = notify.send(
                subject=title,
                summary=summary,
                location=result.get("published"),
                to_email=to_email,
                prefix=prefix,
            )
            result["notified"] = notif
            log.info("Notification: %s", notif)
        except Exception as e:  # never fail a run because notification failed
            log.warning("Notification failed: %s", e)
            result["notified"] = {"sent": False, "error": str(e)}
    return result


def lambda_handler(event, context):
    result = run_once(event)
    return {
        "statusCode": 200,
        "published": result.get("published"),
        "summary": result.get("final_text"),
        "turns": len(result.get("trace", [])),
    }


def fanout_handler(event, context):
    """Scheduled entry: run one personal brief per signed-up user.

    Scans the users table and asynchronously invokes this stack's agent function
    once per enabled user (passing their saved preferences), plus one public
    demo run. Each invocation is isolated, so one user's failure never blocks
    another's brief.
    """
    import os
    import boto3

    users_table = os.environ["USERS_TABLE"]
    target = os.environ["TARGET_FUNCTION"]
    lam = boto3.client("lambda")
    ddb = boto3.resource("dynamodb")
    table = ddb.Table(users_table)

    def _invoke(payload: dict):
        lam.invoke(FunctionName=target, InvocationType="Event",
                   Payload=json.dumps(payload).encode("utf-8"))

    # 1) Public demo brief (the always-on dashboard).
    _invoke({"trigger": "schedule"})

    # 2) One personalized brief per enabled user.
    count = 0
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        for u in resp.get("Items", []):
            if u.get("enabled") is False:
                continue
            _invoke({"trigger": "fanout", "user": {
                "userId": u.get("userId"), "email": u.get("email", ""),
                "topics": u.get("topics", ""), "feeds": u.get("feeds", ""),
            }})
            count += 1
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    log.info("Fan-out dispatched %d personal runs", count)
    return {"statusCode": 200, "dispatched": count}


if __name__ == "__main__":
    out = run_once({"trigger": "local-cli"})
    print("\n=== TRACE ===")
    for step in out["trace"]:
        print(json.dumps(step, default=str))
    print("\n=== PUBLISHED ===")
    print(out.get("published"))
    print("\n=== SUMMARY ===")
    print(out.get("final_text"))

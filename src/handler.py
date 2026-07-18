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


def run_once(event: dict | None = None) -> dict:
    event = event or {}
    log.info("Sift run starting: %s", json.dumps(config.summary()))

    llm = get_llm()
    memory = get_memory()
    reporter = Reporter()
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


if __name__ == "__main__":
    out = run_once({"trigger": "local-cli"})
    print("\n=== TRACE ===")
    for step in out["trace"]:
        print(json.dumps(step, default=str))
    print("\n=== PUBLISHED ===")
    print(out.get("published"))
    print("\n=== SUMMARY ===")
    print(out.get("final_text"))

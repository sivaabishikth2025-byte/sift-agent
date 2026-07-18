"""Active notification: ping the user when a brief is ready.

Default channel is Amazon SNS (email/SMS) because it is universal and free-tier
friendly — you just confirm one email subscription. A webhook channel (Slack /
Discord / Telegram) is a drop-in alternative: set SIFT_WEBHOOK_URL instead.

If neither is configured, notification is a no-op (the brief still lands in S3),
so the agent never fails just because notifications aren't set up.
"""
from __future__ import annotations

import json
import logging
import urllib.request

import config

log = logging.getLogger()


def _public_link(prefix: str = "") -> str | None:
    """A stable, public https link to the latest brief on the S3 website bucket."""
    if not config.BRIEF_BUCKET:
        return None
    p = (prefix.rstrip("/") + "/") if prefix else ""
    return f"https://{config.BRIEF_BUCKET}.s3.{config.AWS_REGION}.amazonaws.com/{p}latest.html"


def send(subject: str, summary: str, location: str | None,
         to_email: str | None = None, prefix: str = "") -> dict:
    link = _public_link(prefix) or (location or "")
    body = f"{summary}\n\nRead your full brief: {link}\n\n— Sift"

    # Per-user delivery: email this one signed-up user via Amazon SES.
    if to_email and config.SES_FROM:
        import boto3
        boto3.client("ses", region_name=config.AWS_REGION).send_email(
            Source=config.SES_FROM,
            Destination={"ToAddresses": [to_email]},
            Message={"Subject": {"Data": subject[:100]},
                     "Body": {"Text": {"Data": body}}})
        log.info("Notified %s via SES", to_email)
        return {"channel": "ses", "sent": True, "to": to_email}

    if config.SNS_TOPIC_ARN:
        import boto3
        boto3.client("sns", region_name=config.AWS_REGION).publish(
            TopicArn=config.SNS_TOPIC_ARN, Subject=subject[:100], Message=body)
        log.info("Notified via SNS: %s", config.SNS_TOPIC_ARN)
        return {"channel": "sns", "sent": True}

    if config.WEBHOOK_URL:
        payload = json.dumps({"text": f"*{subject}*\n{body}"}).encode("utf-8")
        req = urllib.request.Request(
            config.WEBHOOK_URL, data=payload,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        log.info("Notified via webhook")
        return {"channel": "webhook", "sent": True}

    log.info("No notification channel configured; brief is at %s", link)
    return {"channel": "none", "sent": False, "link": link}

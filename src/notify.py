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


def _presigned_link() -> str | None:
    """A temporary, clickable link to the latest brief in a private S3 bucket."""
    if not config.BRIEF_BUCKET:
        return None
    try:
        import boto3
        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": config.BRIEF_BUCKET, "Key": "latest.html"},
            ExpiresIn=7 * 24 * 3600,
        )
    except Exception as e:  # pragma: no cover
        log.warning("presign failed: %s", e)
        return None


def send(subject: str, summary: str, location: str | None) -> dict:
    link = _presigned_link() or (location or "")
    body = f"{summary}\n\nYour brief: {link}\n\n— Sift (this ran on its own)"

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

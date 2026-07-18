"""Central configuration, driven by environment variables.

Everything has a sensible local-dev default so the agent runs on a laptop
with zero AWS setup, and switches to real AWS resources automatically when
the corresponding environment variables are present (as they are in Lambda).
"""
from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- Runtime mode -----------------------------------------------------------
# "stub"  -> deterministic fake model, no AWS creds needed (great for demos/tests)
# "bedrock" -> real Amazon Bedrock Nova via the Converse API
LLM_MODE = _env("SIFT_LLM", "bedrock").lower()

# Amazon Bedrock model id. Nova Lite is fast + cheap and supports tool use.
MODEL_ID = _env("SIFT_MODEL_ID", "amazon.nova-lite-v1:0")
AWS_REGION = _env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1"))

# Max reasoning/tool turns before we force the agent to wrap up.
MAX_TURNS = int(_env("SIFT_MAX_TURNS", "8"))

# --- Storage ----------------------------------------------------------------
# When MEMORY_TABLE is set we use DynamoDB; otherwise a local JSON file.
MEMORY_TABLE = _env("SIFT_MEMORY_TABLE")
# When BRIEF_BUCKET is set we publish briefs to S3; otherwise the local disk.
BRIEF_BUCKET = _env("SIFT_BRIEF_BUCKET")
# Namespace for memory (set per user on fan-out runs so dedup is per-account).
MEMORY_NS = _env("SIFT_MEMORY_NS")

# --- Obsidian (Git-synced vault) --------------------------------------------
# Connect a GitHub repo that your Obsidian vault syncs to (Obsidian Git plugin).
# When set, Sift uses the vault as its memory and writes notes into it.
OBSIDIAN_REPO = _env("SIFT_OBSIDIAN_REPO")     # e.g. "user/my-vault"
OBSIDIAN_BRANCH = _env("SIFT_OBSIDIAN_BRANCH", "main")
OBSIDIAN_BASE = _env("SIFT_OBSIDIAN_BASE", "Sift")  # folder inside the vault
GITHUB_TOKEN = _env("SIFT_GITHUB_TOKEN") or _env("GITHUB_TOKEN")

# --- Notifications ----------------------------------------------------------
# Set one of these to get pinged when a brief is ready. If neither is set,
# notification is a no-op (the brief still publishes).
SNS_TOPIC_ARN = _env("SIFT_SNS_TOPIC_ARN")   # Amazon SNS (email/SMS)
WEBHOOK_URL = _env("SIFT_WEBHOOK_URL")        # Slack / Discord / Telegram webhook
# Verified Amazon SES sender, used for per-user branded emails on fan-out runs.
SES_FROM = _env("SIFT_SES_FROM")

# Local storage root (used for memory + briefs when not on AWS).
# In Lambda the only writable path is /tmp.
_default_root = "/tmp/sift" if _env("AWS_LAMBDA_FUNCTION_NAME") else str(Path.cwd() / ".sift")
LOCAL_ROOT = Path(_env("SIFT_LOCAL_ROOT", _default_root))

# --- What to watch ----------------------------------------------------------
# Topics steer the analyst's judgement about what is "signal" for you.
TOPICS = [t.strip() for t in _env(
    "SIFT_TOPICS",
    "AI agents, AWS, serverless, developer tooling, LLMs",
).split(",") if t.strip()]

# RSS/Atom feeds to pull. Comma-separated. All public, no API keys.
RSS_FEEDS = [u.strip() for u in _env(
    "SIFT_RSS_FEEDS",
    "https://aws.amazon.com/blogs/aws/feed/,https://hnrss.org/frontpage",
).split(",") if u.strip()]

# How many items to pull per source.
PER_SOURCE_LIMIT = int(_env("SIFT_PER_SOURCE_LIMIT", "12"))

# How many days back GitHub "trending" repos are considered.
GITHUB_TRENDING_DAYS = int(_env("SIFT_GITHUB_DAYS", "3"))


def summary() -> dict:
    """A redacted snapshot of config for logging."""
    return {
        "llm_mode": LLM_MODE,
        "model_id": MODEL_ID,
        "region": AWS_REGION,
        "memory": "obsidian" if OBSIDIAN_REPO else ("dynamodb" if MEMORY_TABLE else "local-json"),
        "briefs": "s3" if BRIEF_BUCKET else "local-disk",
        "obsidian": OBSIDIAN_REPO or "off",
        "notify": "sns" if SNS_TOPIC_ARN else ("webhook" if WEBHOOK_URL else "none"),
        "topics": TOPICS,
        "rss_feeds": RSS_FEEDS,
    }

#!/usr/bin/env python3
"""Run one full Sift cycle locally and open the resulting brief.

Usage:
    python scripts/run_local.py            # real Bedrock if creds present
    SIFT_LLM=stub python scripts/run_local.py   # no AWS creds needed

Everything is written under ./.sift (memory.json + briefs/).
"""
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SIFT_LOCAL_ROOT", str(ROOT / ".sift"))

import handler  # noqa: E402

if __name__ == "__main__":
    result = handler.run_once({"trigger": "local-cli"})
    published = result.get("published")
    print(f"\nBrief published to: {published}")
    print(f"Summary: {result.get('final_text')}")
    if published and Path(published).exists():
        webbrowser.open(Path(published).as_uri())

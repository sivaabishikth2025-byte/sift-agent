"""Proof that Sift's memory actually dedupes.

Runs the real fetch + classify pipeline twice against a FRESH local memory:

  Run A (empty memory)  -> everything is "new"
  ... persist what was seen (exactly what a real run does via mark_seen) ...
  Run B (warm memory)   -> the same items are recognized, "new" collapses to ~0

No AWS credentials needed. Screenshot the table it prints for the article.

    python scripts/prove_memory.py
"""
import os
import sys
import tempfile
from pathlib import Path

# Force a clean, local-only memory BEFORE importing config.
_tmp = Path(tempfile.mkdtemp(prefix="sift-proof-"))
os.environ["SIFT_LOCAL_ROOT"] = str(_tmp)
os.environ.pop("SIFT_MEMORY_TABLE", None)
os.environ.pop("SIFT_OBSIDIAN_REPO", None)
os.environ["SIFT_LLM"] = "stub"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tools          # noqa: E402
from memory import get_memory   # noqa: E402
from report import Reporter     # noqa: E402


def one_run(memory) -> dict:
    ctx = tools.ToolContext(memory, Reporter())
    ctx.fetch_signals(limit=40)
    # A real run records EVERY fetched item as seen, not just featured ones.
    memory.mark_seen(list(ctx.fetched.values()))
    return ctx.stats


def main():
    memory = get_memory()
    print("Using fresh local memory at:", _tmp, "\n")

    a = one_run(memory)
    b = one_run(memory)

    print("+---------+-----------+---------+-----------+-------------+")
    print("|  Run    |  scanned  |   NEW   |  updates  |  in_memory  |")
    print("+---------+-----------+---------+-----------+-------------+")
    for name, s in (("Run A", a), ("Run B", b)):
        print("| {:<7} | {:>9} | {:>7} | {:>9} | {:>11} |".format(
            name, s.get("scanned", 0), s.get("new", 0),
            s.get("updates", 0), s.get("in_memory", 0)))
    print("+---------+-----------+---------+-----------+-------------+")

    drop = a.get("new", 0) - b.get("new", 0)
    print(f"\n=> memory dedupe: NEW dropped from {a.get('new',0)} to "
          f"{b.get('new',0)} (-{drop}). The agent won't repeat those stories.")


if __name__ == "__main__":
    main()

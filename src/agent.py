"""The agentic loop: drive the model through repeated Converse turns, executing
whatever tools it asks for, until it stops calling tools or we hit the turn cap.

This is model-agnostic — it works identically with real Bedrock Nova and with
the local StubLLM.
"""
from __future__ import annotations

import json

import config


SYSTEM_PROMPT = """You are Sift, an always-on personal signal analyst that runs \
unattended on a schedule. Your job each run:

1. Call fetch_signals to pull the latest items from the user's sources.
2. Call recall_memory to see what you already reported and your recent theses.
3. Decide what is GENUINELY NEW and relevant to the user's topics: {topics}.
   Ignore items already in memory unless there is a meaningful development.
4. Call save_findings with the ids of the items you are reporting as new, a
   single sharp one-line thesis for today, and your confidence.
5. Call publish_brief exactly once. Pass title="Daily Brief - <weekday>, <date>".

The markdown_body MUST follow this exact structure (do NOT use any top-level '#'
heading — the title is a separate field):

**Thesis:** <one crisp sentence>

## What's new since last time
- [Title](url) — one line on why it matters
(only genuinely new items; 3-6 of them; strongest first)

## How the picture is changing
<1-2 sentences explicitly comparing to your previous theses>

## Confidence
<one line: your confidence level and an honest caveat>

Be concise and specific. No filler. Prefer 5 strong items over 15 weak ones.
Keep the whole brief under ~250 words."""


def _tool_result_block(tool_use_id: str, payload: dict) -> dict:
    return {"toolResult": {
        "toolUseId": tool_use_id,
        "content": [{"json": payload}],
        "status": "success",
    }}


def run(llm, ctx, tools_spec, user_prompt: str) -> dict:
    system = SYSTEM_PROMPT.format(topics=", ".join(config.TOPICS))
    messages = [{"role": "user", "content": [{"text": user_prompt}]}]
    trace = []

    for turn in range(config.MAX_TURNS):
        assistant_msg = llm.converse(system, messages, tools_spec)
        messages.append(assistant_msg)

        tool_uses = [b["toolUse"] for b in assistant_msg.get("content", []) if "toolUse" in b]
        if not tool_uses:
            final_text = " ".join(b.get("text", "") for b in assistant_msg.get("content", []))
            trace.append({"turn": turn, "action": "final", "text": final_text})
            return {"final_text": final_text.strip(), "trace": trace,
                    "published": ctx.published_location}

        tool_result_blocks = []
        for tu in tool_uses:
            name, args = tu["name"], tu.get("input", {})
            result = ctx.dispatch(name, args)
            trace.append({"turn": turn, "action": name, "args": args,
                          "result_preview": _preview(result)})
            tool_result_blocks.append(_tool_result_block(tu["toolUseId"], result))

        messages.append({"role": "user", "content": tool_result_blocks})

    trace.append({"turn": config.MAX_TURNS, "action": "max_turns_reached"})
    return {"final_text": "Stopped at max turns.", "trace": trace,
            "published": ctx.published_location}


def _preview(result: dict) -> str:
    s = json.dumps(result, default=str)
    return s[:280] + ("…" if len(s) > 280 else "")

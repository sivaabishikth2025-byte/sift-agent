"""Model access via the Amazon Bedrock Converse API (tool use supported).

Also ships a deterministic StubLLM that emulates the Converse tool-use
handshake, so the whole agent loop runs on a laptop with no AWS credentials.
That makes local demos and tests reproducible.
"""
from __future__ import annotations

import json

import config


class BedrockLLM:
    """Thin wrapper over bedrock-runtime `converse`."""

    def __init__(self, model_id: str, region: str):
        import boto3
        self._client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        resp = self._client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=messages,
            toolConfig={"tools": tools},
            inferenceConfig={"maxTokens": 1500, "temperature": 0.3},
        )
        return resp["output"]["message"]


class StubLLM:
    """Deterministic stand-in for Bedrock, used when SIFT_LLM=stub.

    It drives the exact same fetch -> recall -> save -> publish tool sequence the
    real model would, and it builds the brief from the REAL data returned by the
    tools (the live headlines fetched this run), so a local test exercises the
    entire pipeline end-to-end. Only the natural-language reasoning is templated;
    the orchestration, data flow, memory, and rendering are all real.
    """

    def __init__(self, *_args, **_kwargs):
        self.model_id = "stub"
        self._step = 0

    @staticmethod
    def _tool_json(messages: list[dict], tool_use_id: str) -> dict | None:
        """Pull a tool's returned JSON back out of the conversation."""
        for m in messages:
            for block in m.get("content", []):
                tr = block.get("toolResult")
                if tr and tr.get("toolUseId") == tool_use_id:
                    for c in tr.get("content", []):
                        if "json" in c:
                            return c["json"]
        return None

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        step = self._step
        self._step += 1

        def tool_use(name, inp):
            return {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": f"tu-{name}", "name": name, "input": inp}}
            ]}

        if step == 0:
            return tool_use("fetch_signals", {"limit": 20})
        if step == 1:
            return tool_use("recall_memory", {"query": " ".join(config.TOPICS)})

        fetched = self._tool_json(messages, "tu-fetch_signals") or {}
        items = fetched.get("items", [])
        new_items = [it for it in items if it.get("is_new")]

        if step == 2:
            # Persist the genuinely-new items so future runs dedupe against them.
            return tool_use("save_findings", {
                "new_item_ids": [it["id"] for it in new_items[:8]],
                "thesis": self._thesis(fetched),
                "confidence": "medium",
            })
        if step == 3:
            return tool_use("publish_brief", {
                "title": "Sift Brief",
                "markdown_body": self._brief(fetched, new_items),
            })

        return {"role": "assistant", "content": [
            {"text": f"Done. Published brief with {len(new_items)} new item(s); memory updated."}
        ]}

    @staticmethod
    def _thesis(fetched: dict) -> str:
        n = fetched.get("new_count", 0)
        total = fetched.get("count", 0)
        return (f"{n} of {total} tracked items are new since the last run — "
                "signal is concentrated in autonomous agents and AWS tooling.")

    def _brief(self, fetched: dict, new_items: list[dict]) -> str:
        lines = ["# Sift Brief", "", f"**Thesis:** {self._thesis(fetched)}", ""]
        lines.append("## What's new since last time")
        if new_items:
            for it in new_items[:8]:
                title = it.get("title", "").strip()
                url = it.get("url", "")
                src = it.get("source", "")
                summ = it.get("summary", "")
                link = f"[{title}]({url})" if url else title
                lines.append(f"- {link} — *{src}* — {summ}")
        else:
            lines.append("- Nothing new — everything fetched was already reported. "
                         "(That's the memory working.)")
        lines += ["", "## How the picture is changing",
                  f"- Fetched {fetched.get('count', 0)} items; "
                  f"{fetched.get('new_count', 0)} are new vs. memory.",
                  "", "Confidence: medium. Generated locally by StubLLM — set "
                  "SIFT_LLM=bedrock for real Nova reasoning."]
        return "\n".join(lines)


def get_llm():
    if config.LLM_MODE == "stub":
        return StubLLM()
    return BedrockLLM(config.MODEL_ID, config.AWS_REGION)

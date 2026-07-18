<!--
AWS Builder Center submission for the "Build an Always-On Agent" challenge.
Structured to the official Article Requirements:
  - >= 500 words (this draft is ~950)
  - Title MUST start with "Weekend Agent Challenge: [Name of Your Agent]"
  - Add the tag: agents  (plus optional: bedrock, lambda, serverless, ai)
  - Required sections: Vision & What the Agent Does / How You Built It /
    AWS Services Used / Architecture Overview / What You Learned / Link to App or Repo
Replace [SCREENSHOT ...] markers and the repo link before publishing.
-->

# Weekend Agent Challenge: Sift — the analyst that reads the internet so I don't have to

*Tag: **#agents*** (also: bedrock, lambda, serverless, ai)

## Vision & What the Agent Does

The best productivity tool is the one you never have to open. So instead of
building another app with a button, I built **Sift** — an agent that wakes up on
its own, does the reading while I'm asleep, and leaves a brief waiting for me.

**The problem it solves:** most "daily digest" bots re-summarize the same
headlines every day. Open one on Tuesday and it repeats Monday's news, reworded.
That's a photocopier on a timer, not an analyst. I wanted something that
**remembers** what it already told me, so it only surfaces what's genuinely new —
and, crucially, explains *how the picture is changing*.

**What triggers it:** an **Amazon EventBridge Scheduler** rule fires every
morning at 06:00. There is no button anywhere in the system — the schedule *is*
the interface. The same handler also runs from a manual "invoke now" event, so I
can force a run for a demo.

**What it does on its own, unattended:**
1. **Fetches** the latest items from public sources — Hacker News, RSS/Atom
   feeds, and GitHub's newest fast-rising repos.
2. **Recalls** its long-term memory: the items it already reported and the
   theses it held on previous days.
3. **Reasons** over both with **Amazon Bedrock Nova** (Converse API + tool use)
   to decide what is actually new and relevant to my topics.
4. **Saves** the newly reported items and today's one-line thesis back to memory,
   so tomorrow's run is smarter than today's.
5. **Publishes** a clean, dated HTML brief.

**How it reports back:** the brief lands in Amazon S3 as `latest.html` — waiting
for me when I wake up. No app to open.

[SCREENSHOT 1: the EventBridge schedule in the console, State = ENABLED]
[SCREENSHOT 2: the published brief open in a browser]

## How You Built It

I started from the trigger and worked outward. The core design decision was to
make this a **real agent, not a prompt**: I gave the model four tools —
`fetch_signals`, `recall_memory`, `save_findings`, `publish_brief` — plus a
system prompt describing its job, and let Bedrock Nova drive. My orchestration
loop (~40 lines in `agent.py`) just executes whatever tool the model asks for and
feeds the result back as a `toolResult` block, looping until the model publishes.

**Key decisions:**
- **Memory is the differentiator.** A tiny DynamoDB table stores seen-item ids
  and past theses, so each run dedupes against history and compounds knowledge.
- **Zero heavy dependencies.** Sources use only the Python standard library
  (`urllib` + `xml`), and the Lambda runtime already ships `boto3` — so there are
  **no layers and no containers** to build. One `sam deploy` stands everything up.
- **A deterministic local test mode.** I wrote a `StubLLM` that emulates the
  Bedrock Converse tool-use handshake, so the *entire* pipeline runs on my laptop
  with no AWS credentials — and it builds the brief from the real headlines it
  fetches, so local runs are a genuine end-to-end test.

**Challenges I hit and fixed:**
- My little Markdown-to-HTML renderer mangled URLs containing underscores
  (the italic rule chewed them up). I fixed it by protecting links with
  placeholders before applying emphasis, and HTML-escaping the rest.
- Proving memory actually compounds: I ran the agent twice and watched the
  "new" count drop from 20 to 12 as the first run's items were recognized —
  that became my favorite piece of evidence.
- I validated the infrastructure three ways before deploying — `cfn-lint`,
  `sam validate`, and `sam build` — to catch IAM/resource mistakes early.

[SCREENSHOT 3: two runs side by side — "new_count" dropping as memory dedupes]

## AWS Services Used / Architecture Overview

- **Amazon EventBridge Scheduler** — the always-on trigger (cron, no button).
- **AWS Lambda** — runs the agent loop (Python 3.12).
- **Amazon Bedrock (Nova Lite)** — the reasoning engine, via Converse + tool use.
- **Amazon DynamoDB** — persistent memory (seen items + theses).
- **Amazon S3** — stores the published HTML briefs.
- **AWS IAM** — least-privilege roles for the function and the scheduler.

```
EventBridge Scheduler (06:00, no button)
        │  invokes
        ▼
   AWS Lambda ──Converse + tools──► Amazon Bedrock (Nova)
        │  ├─ recall/remember ─► DynamoDB (memory)
        │  ├─ fetch ─────────► Hacker News · RSS · GitHub
        │  └─ publish ───────► Amazon S3 (dated HTML brief) ──► waiting for you
```

Everything is defined in a single AWS SAM template (`template.yaml`).

[SCREENSHOT 4: CloudWatch Logs showing the scheduled invocation + "Sift run complete"]

## What You Learned

- **Bedrock Converse tool use** makes agent loops genuinely simple: you own a
  small loop, the model owns the decisions. It's a cleaner mental model than
  stuffing everything into one giant prompt.
- **Memory turns a summarizer into an analyst.** A cheap DynamoDB table is the
  difference between "here's the news" and "here's what changed since yesterday."
- **EventBridge Scheduler + Lambda is a perfect always-on backbone** — no
  servers, pennies of cost, and the trigger literally *is* the product.
- Testing an agent is far easier with a deterministic stand-in for the model, so
  you can exercise the orchestration and data flow offline.

**Cost:** comfortably within Free Tier — one short Lambda run per day, a handful
of Nova Lite calls, and tiny DynamoDB/S3 usage. Tear down with
`sam delete --stack-name sift-agent`.

## Link to App or Repo

Source code (public GitHub repo): **[https://github.com/<your-username>/sift-agent](https://github.com/<your-username>/sift-agent)**

The README includes one-command deploy instructions and a no-AWS-needed local
demo. *(Replace the link above with your actual repo before publishing.)*

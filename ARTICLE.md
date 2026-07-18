<!--
AWS Builder Center submission for the "Build an Always-On Agent" challenge.
Structured to the official Article Requirements:
  - >= 500 words (this draft is ~1,250)
  - Title MUST start with "Weekend Agent Challenge: [Name of Your Agent]"
  - Add the tag: agents  (plus optional: bedrock, lambda, serverless, ai)
  - Required sections: Vision & What the Agent Does / How You Built It /
    AWS Services Used / Architecture Overview / What You Learned / Link to App or Repo
Replace [SCREENSHOT ...] markers before publishing.
-->

# Weekend Agent Challenge: Sift — the analyst that reads the internet so you don't have to

*Tag: **#agents*** (also: bedrock, lambda, serverless, ai)

## Vision & What the Agent Does

The best productivity tool is the one you never have to open. So instead of
building another app with a button, I built **Sift** — an agent that wakes up on
its own every morning, does the reading while you sleep, and leaves a personal
brief waiting for you.

**The problem it solves:** most "daily digest" bots re-summarize the same
headlines every day. Open one on Tuesday and it repeats Monday's news, reworded.
That's a photocopier on a timer, not an analyst. Sift **remembers** what it
already told you, so it leads with what's genuinely new — and explains *how the
picture is changing* — while still delivering a fresh brief every single day.

And it isn't a private toy. **Sift is a multi-user product**: anyone can sign up,
choose the topics and feeds they care about, and get their *own* personalized
brief. Each user has isolated memory and their own delivery — one account's news
never bleeds into another's.

**What triggers it:** an **Amazon EventBridge Scheduler** rule fires every
morning. There is no button anywhere in the pipeline — the schedule *is* the
interface. It invokes a fan-out function that dispatches one independent agent run
per signed-up user, plus a public demo brief.

**What each run does, unattended:**
1. **Fetches** the latest items from a wide, real spread of sources — **topic-driven
   Google News search** (so results follow each user's chosen topics across the
   whole web), Hacker News, GitHub's newest fast-rising repos, and a dozen
   reputable feeds (AWS, TechCrunch, The Verge, Ars Technica, WIRED, MIT Tech
   Review, the Google AI blog, BBC Tech, and more) — ~175 items per run.
2. **Recalls** its long-term memory: the items it already reported and the theses
   it held on previous days, scoped to that specific user.
3. **Reasons** over both with **Amazon Bedrock Nova** (Converse API + tool use) to
   decide what is actually new and relevant to that user's topics.
4. **Saves** the featured items and today's one-line thesis back to memory, so
   tomorrow's run is smarter than today's.
5. **Publishes** a clean, dated HTML brief and **notifies** the user.

[SCREENSHOT 1: the signup / preferences page on the CloudFront app]
[SCREENSHOT 2: a published brief open in a browser]

## How You Built It

I started from the trigger and worked outward. The core design decision was to
make this a **real agent, not a prompt**: I gave the model four tools —
`fetch_signals`, `recall_memory`, `save_findings`, `publish_brief` — plus a system
prompt describing its job, and let Bedrock Nova drive. My orchestration loop
(~40 lines in `agent.py`) just executes whatever tool the model asks for and feeds
the result back as a `toolResult` block, looping until the model publishes.

Then I turned it into something other people can actually use:

- **Signup & auth** with **Amazon Cognito** (Hosted UI, email verification).
- **A preferences API** — an **API Gateway HTTP API** with a Cognito **JWT
  authorizer** in front of a Lambda that reads/writes each user's row in
  **DynamoDB**. Because identity comes from the verified token, a user can only
  ever touch their own preferences.
- **A real front end** — a clean signup / login / preferences dashboard, served
  over **HTTPS via Amazon CloudFront** from a private S3 bucket (Origin Access
  Control). Users pick topics as chips, add feeds, set a delivery time, and save.
- **Fan-out delivery** — the scheduled Lambda scans the users table and
  asynchronously invokes the agent once per enabled user, passing their prefs.
  Each user's brief is published under their own path and they're emailed a link.

**Key decisions:**
- **Memory is the differentiator, and it's per-user.** A single DynamoDB table
  stores seen-item ids and past theses, namespaced per account, so every user's
  brief dedupes against *their* history and compounds *their* knowledge.
- **Sources follow the user, not a fixed list.** Topic-driven Google News search
  means a user who picks "biotech" or "Formula 1" gets exactly that — the agent
  is not confined to a hardcoded handful of sites.
- **Zero heavy dependencies.** Sources use only the Python standard library
  (`urllib` + `xml`), and the Lambda runtime already ships `boto3` — **no layers,
  no containers**. One `sam deploy` stands the entire multi-service stack up.
- **A deterministic local test mode.** A `StubLLM` emulates the Bedrock Converse
  tool-use handshake, so the whole pipeline runs on a laptop with no AWS
  credentials, building the brief from real fetched headlines.

**Challenges I hit and fixed:**
- **Freshness vs. dedup.** My first memory pass was too aggressive and could go
  silent. I re-scoped it so it never repeats an identical story but always ships a
  fresh daily brief.
- **The Cognito ↔ CloudFront callback loop.** The client's callback URL needs the
  CloudFront domain, which doesn't exist until the distribution is created. I
  resolved it by referencing the distribution's domain in the user-pool client so
  CloudFormation orders it correctly — no circular dependency.
- **Dead feeds polluting briefs.** Flaky sources now return error markers that are
  filtered out before the model ever sees them.
- I validated the infrastructure with `cfn-lint`, `sam validate`, and `sam build`
  before every deploy.

[SCREENSHOT 3: fan-out proof — a personal brief published under u/<userId>/latest.html]

## AWS Services Used / Architecture Overview

- **Amazon EventBridge Scheduler** — the always-on trigger (cron, no button).
- **AWS Lambda** — the agent loop, the fan-out dispatcher, and the preferences API.
- **Amazon Bedrock (Nova Lite)** — the reasoning engine, via Converse + tool use.
- **Amazon Cognito** — signup, login, and JWT-based authorization.
- **Amazon API Gateway (HTTP API)** — the authenticated preferences endpoint.
- **Amazon DynamoDB** — per-user memory and user preferences.
- **Amazon S3** — stores published HTML briefs and the static web app.
- **Amazon CloudFront** — clean HTTPS delivery of the app (OAC to a private bucket).
- **Amazon SNS / SES** — notifications when a brief is ready.
- **AWS IAM** — least-privilege roles for every function and the scheduler.

```
                 EventBridge Scheduler (daily, no button)
                          │ invokes
                          ▼
                   Fan-out Lambda ──scans──► DynamoDB (users + prefs)
                          │ async invoke per user
                          ▼
   Agent Lambda ──Converse + tools──► Amazon Bedrock (Nova)
        │  ├─ recall/remember ─► DynamoDB (per-user memory)
        │  ├─ fetch ─► Google News (by topic) · HN · GitHub · 12 RSS feeds
        │  ├─ publish ─► Amazon S3 (dated HTML brief, per user)
        │  └─ notify ─► SNS / SES (link to the brief)

   Users ─► CloudFront (HTTPS) ─► S3 web app  ─┐
                                                ├─ Cognito (signup/login)
           Preferences dashboard ─► API Gateway┘  (JWT) ─► Lambda ─► DynamoDB
```

Everything is defined in a single AWS SAM template (`template.yaml`).

[SCREENSHOT 4: CloudWatch Logs showing the scheduled fan-out + "Fan-out dispatched N personal runs"]

## What You Learned

- **Bedrock Converse tool use** makes agent loops genuinely simple: you own a
  small loop, the model owns the decisions — a cleaner mental model than one giant
  prompt.
- **Memory turns a summarizer into an analyst**, and namespacing it per user is
  what turns a personal script into a product.
- **EventBridge Scheduler + Lambda fan-out is a perfect always-on backbone** — no
  servers, pennies of cost, and it scales to many users by simply invoking one
  isolated run each.
- **Cognito + API Gateway JWT authorizers + CloudFront/OAC** are a surprisingly
  small amount of config for a real, secure, multi-user web app.
- Testing an agent is far easier with a deterministic stand-in for the model.

**Cost:** comfortably within Free Tier — a short Lambda run per user per day, a
handful of Nova Lite calls, and tiny DynamoDB/S3/CloudFront usage. Tear down with
`sam delete --stack-name sift-agent`.

## Link to App or Repo

**Live app (signup, login, preferences) — HTTPS via CloudFront:**
**[https://d2dhklcmg1eipz.cloudfront.net](https://d2dhklcmg1eipz.cloudfront.net)**

**Public brief dashboard:**
[dashboard](http://sift-agent-briefsbucket-79m1iuj8cket.s3-website-us-east-1.amazonaws.com)
· [latest brief](https://sift-agent-briefsbucket-79m1iuj8cket.s3.us-east-1.amazonaws.com/latest.html)

**Source code (public GitHub repo):**
**[https://github.com/sivaabishikth2025-byte/sift-agent](https://github.com/sivaabishikth2025-byte/sift-agent)**

Anyone can sign up on the live app to get their own personalized daily brief, or
deploy their own instance — the README has a no-AWS-needed local demo and a
one-command `sam deploy --guided`. Nothing is hardcoded to a single account.

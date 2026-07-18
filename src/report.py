"""Render the brief to a modern, self-contained HTML page, publish it (S3 or
local disk), and maintain a dashboard `index.html` listing every past brief.

The published page is the "result waiting for you" — no app to open, just a link.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import config

_FAVICON = ("data:image/svg+xml,"
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
            "%3Ctext y='.9em' font-size='90'%3E%F0%9F%9B%B0%EF%B8%8F%3C/text%3E%3C/svg%3E")

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" href="__FAVICON__">
<style>
:root {{
  --bg:#0a0e1a; --card:#131a2b; --ink:#eef2fb; --muted:#98a6c4; --line:#242f49;
  --accent:#7aa2ff; --accent2:#b78bff; --chip:#1c2540;
}}
@media (prefers-color-scheme: light) {{
  :root {{ --bg:#f4f6fc; --card:#ffffff; --ink:#141b2d; --muted:#5f6f92;
           --line:#e7ecf7; --accent:#3b5bff; --accent2:#8b5cf6; --chip:#eef2fd; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.65 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:780px; margin:0 auto; padding:0 22px 72px; }}
.hero {{ position:relative; overflow:hidden; color:#fff;
  background:radial-gradient(1200px 400px at 15% -30%, rgba(255,255,255,.25), transparent),
             linear-gradient(120deg,#3b5bff,#8b5cf6 55%,#d946ef);
  padding:40px 0 34px; margin-bottom:28px; box-shadow:0 10px 40px rgba(59,91,255,.25); }}
.hero .wrap {{ padding-bottom:0; }}
.brand {{ display:inline-flex; align-items:center; gap:10px; font-weight:800;
  letter-spacing:.02em; font-size:15px; }}
.kicker {{ display:inline-flex; align-items:center; gap:8px; font-size:12px;
  letter-spacing:.1em; text-transform:uppercase; opacity:.95;
  background:rgba(255,255,255,.16); padding:4px 10px; border-radius:999px; }}
.dot {{ width:8px; height:8px; border-radius:50%; background:#7CFFB2;
  box-shadow:0 0 0 4px rgba(124,255,178,.28); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
.hero h1 {{ margin:14px 0 6px; font-size:32px; line-height:1.12; font-weight:800; }}
.hero .sub {{ opacity:.92; font-size:14px; }}
.stats {{ display:flex; gap:10px; flex-wrap:wrap; margin:-14px 0 24px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:10px 14px; font-size:13px; color:var(--muted); }}
.stat b {{ display:block; font-size:20px; color:var(--ink); font-weight:800; }}
.thesis {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:14px; padding:18px 20px; margin:0 0 28px; font-size:17px; line-height:1.5; }}
h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted);
  margin:32px 0 14px; }}
ul {{ list-style:none; padding:0; margin:0; display:grid; gap:12px; }}
li {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:15px 17px; transition:transform .1s ease, border-color .1s ease, box-shadow .1s ease; }}
li:hover {{ transform:translateY(-2px); border-color:var(--accent);
  box-shadow:0 8px 24px rgba(0,0,0,.12); }}
li a {{ color:var(--ink); text-decoration:none; font-weight:700; }}
li a:hover {{ color:var(--accent); }}
em {{ font-style:normal; color:var(--accent2); font-weight:600; }}
p {{ margin:10px 0; color:var(--ink); }}
.foot {{ margin-top:38px; color:var(--muted); font-size:13px;
  border-top:1px solid var(--line); padding-top:18px; }}
.index-item {{ display:flex; justify-content:space-between; align-items:center; }}
.index-item .date {{ color:var(--muted); font-variant-numeric:tabular-nums; }}
</style></head>
<body>
<header class="hero"><div class="wrap">
  <div class="brand">🛰️ Sift</div>
  <div style="margin-top:12px"><span class="kicker"><span class="dot"></span> Auto-updated daily</span></div>
  <h1>{h1}</h1>
  <div class="sub">Updated {ts}</div>
</div></header>
<main class="wrap">
{stats}
{body}
<div class="foot">Sift · powered by Amazon Bedrock Nova</div>
</main>
</body></html>
""".replace("__FAVICON__", _FAVICON)


def _inline(text: str) -> str:
    links: list[str] = []

    def _link(m):
        label, url = escape(m.group(1)), escape(m.group(2), quote=True)
        links.append(f'<a href="{url}" target="_blank" rel="noopener">{label}</a>')
        return f"\x00{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _link, text)
    text = escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], text)


def _md_body(md: str) -> str:
    """Render the brief Markdown subset to HTML, skipping the top-level H1
    (the title is shown in the hero) and styling the thesis line."""
    out, in_list = [], False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            continue
        rendered = _inline(line)
        if line.startswith("## "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list: out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        elif line.lower().startswith("**thesis:**"):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f'<div class="thesis">{rendered}</div>')
        elif not line:
            if in_list: out.append("</ul>"); in_list = False
        else:
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<p>{rendered}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _stats_html(stats: dict | None) -> str:
    if not stats:
        return ""
    cells = [
        ("Items scanned", stats.get("scanned")),
        ("New this run", stats.get("new")),
        ("In memory", stats.get("in_memory")),
    ]
    chips = "".join(f'<div class="stat"><b>{v}</b>{label}</div>'
                    for label, v in cells if v is not None)
    return f'<div class="stats">{chips}</div>' if chips else ""


class Reporter:
    def render(self, title: str, markdown_body: str, stats: dict | None = None) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return _PAGE.format(title=escape(title), h1=escape(title), ts=ts,
                            stats=_stats_html(stats), body=_md_body(markdown_body))

    def publish(self, title: str, markdown_body: str, stats: dict | None = None) -> str:
        html = self.render(title, markdown_body, stats)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"briefs/{date}.html"
        if config.BRIEF_BUCKET:
            loc = self._publish_s3(key, html)
        else:
            loc = self._publish_local(key, html)
        self._rebuild_index()
        return loc

    # -- local disk ----------------------------------------------------------
    def _publish_local(self, key: str, html: str) -> str:
        out = config.LOCAL_ROOT / key
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, "utf-8")
        (config.LOCAL_ROOT / "latest.html").write_text(html, "utf-8")
        return str(out)

    def _publish_s3(self, key: str, html: str) -> str:
        import boto3
        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        for k in (key, "latest.html"):
            s3.put_object(Bucket=config.BRIEF_BUCKET, Key=k, Body=html.encode("utf-8"),
                          ContentType="text/html; charset=utf-8")
        return f"s3://{config.BRIEF_BUCKET}/{key}"

    # -- dashboard index -----------------------------------------------------
    def _rebuild_index(self):
        dates = self._list_brief_dates()
        items = "\n".join(
            f'<li class="index-item"><a href="briefs/{d}.html" target="_blank" '
            f'rel="noopener">Brief — {d}</a><span class="date">{d}</span></li>'
            for d in dates
        ) or '<li>No briefs yet.</li>'
        body = f'<h2>All briefs ({len(dates)})</h2>\n<ul>\n{items}\n</ul>'
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        html = _PAGE.format(title="Sift — Dashboard", h1="Sift Dashboard", ts=ts,
                            stats="", body=body)
        if config.BRIEF_BUCKET:
            import boto3
            boto3.client("s3", region_name=config.AWS_REGION).put_object(
                Bucket=config.BRIEF_BUCKET, Key="index.html",
                Body=html.encode("utf-8"), ContentType="text/html; charset=utf-8")
        else:
            (config.LOCAL_ROOT / "index.html").write_text(html, "utf-8")

    def _list_brief_dates(self) -> list[str]:
        if config.BRIEF_BUCKET:
            import boto3
            s3 = boto3.client("s3", region_name=config.AWS_REGION)
            resp = s3.list_objects_v2(Bucket=config.BRIEF_BUCKET, Prefix="briefs/")
            keys = [o["Key"] for o in resp.get("Contents", [])]
        else:
            d = config.LOCAL_ROOT / "briefs"
            keys = [str(p) for p in d.glob("*.html")] if d.exists() else []
        dates = sorted({re.search(r"(\d{4}-\d{2}-\d{2})", k).group(1)
                        for k in keys if re.search(r"\d{4}-\d{2}-\d{2}", k)}, reverse=True)
        return dates

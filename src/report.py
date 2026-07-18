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

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#0b1020; --card:#141b2e; --ink:#e7ecf5; --muted:#95a2bd; --line:#26314b;
  --accent:#6ea8fe; --accent2:#8b5cf6; --chip:#1e2740;
}}
@media (prefers-color-scheme: light) {{
  :root {{ --bg:#f5f7fb; --card:#ffffff; --ink:#131a2b; --muted:#5b6b8c;
           --line:#e6ebf5; --accent:#2563eb; --accent2:#7c3aed; --chip:#eef2fb; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
.wrap {{ max-width:760px; margin:0 auto; padding:0 20px 64px; }}
.hero {{ background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#fff; padding:34px 0 30px; margin-bottom:26px; }}
.hero .wrap {{ padding-bottom:0; }}
.kicker {{ display:inline-flex; align-items:center; gap:8px; font-size:12px;
  letter-spacing:.08em; text-transform:uppercase; opacity:.92; }}
.dot {{ width:8px; height:8px; border-radius:50%; background:#7CFFB2;
  box-shadow:0 0 0 4px rgba(124,255,178,.25); }}
.hero h1 {{ margin:10px 0 4px; font-size:30px; line-height:1.15; }}
.hero .sub {{ opacity:.9; font-size:14px; }}
.thesis {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
  border-radius:12px; padding:16px 18px; margin:0 0 26px; font-size:17px; }}
h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:30px 0 12px; }}
ul {{ list-style:none; padding:0; margin:0; display:grid; gap:12px; }}
li {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:14px 16px; transition:transform .08s ease, border-color .08s ease; }}
li:hover {{ transform:translateY(-1px); border-color:var(--accent); }}
li a {{ color:var(--ink); text-decoration:none; font-weight:650; }}
li a:hover {{ color:var(--accent); }}
em {{ font-style:normal; color:var(--accent2); font-weight:600; }}
p {{ margin:10px 0; color:var(--ink); }}
.foot {{ margin-top:34px; color:var(--muted); font-size:13px;
  border-top:1px solid var(--line); padding-top:16px; }}
.back {{ color:var(--accent); text-decoration:none; font-size:14px; }}
.index-item {{ display:flex; justify-content:space-between; align-items:center; }}
.index-item .date {{ color:var(--muted); font-variant-numeric:tabular-nums; }}
</style></head>
<body>
<header class="hero"><div class="wrap">
  <span class="kicker"><span class="dot"></span> Sift · autonomous run</span>
  <h1>{h1}</h1>
  <div class="sub">Generated {ts} — you didn't have to open a thing.</div>
</div></header>
<main class="wrap">
{body}
<div class="foot">Produced automatically by the Sift agent on a schedule. No button was clicked.</div>
</main>
</body></html>
"""


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


class Reporter:
    def render(self, title: str, markdown_body: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return _PAGE.format(title=escape(title), h1=escape(title), ts=ts,
                            body=_md_body(markdown_body))

    def publish(self, title: str, markdown_body: str) -> str:
        html = self.render(title, markdown_body)
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
        html = _PAGE.format(title="Sift — Dashboard", h1="Sift Dashboard", ts=ts, body=body)
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

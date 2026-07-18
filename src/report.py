"""Render the final brief to a self-contained HTML page and publish it either
to the local disk or to an S3 bucket (optionally served as a static website).

The published page is the "result waiting for you when you get back" — no app
to open, just a link/file.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import config

_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 -apple-system, Segoe UI, Roboto, sans-serif; max-width: 720px;
         margin: 40px auto; padding: 0 20px; }}
  .meta {{ color: #888; font-size: 13px; margin-bottom: 24px; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  h2 {{ margin-top: 28px; border-bottom: 1px solid #8883; padding-bottom: 4px; }}
  a {{ color: #2563eb; }}
  code {{ background: #8882; padding: 1px 5px; border-radius: 4px; }}
  .badge {{ display:inline-block; background:#2563eb; color:#fff; border-radius:6px;
            padding:2px 8px; font-size:12px; }}
</style></head>
<body>
<div class="meta"><span class="badge">Sift · autonomous run</span> &nbsp; generated {ts}</div>
{body}
<hr><div class="meta">Produced automatically by the Sift agent — you didn't have to open a thing.</div>
</body></html>
"""


def _md_to_html(md: str) -> str:
    """Very small Markdown subset renderer (headings, lists, links, bold)."""
    import re
    from html import escape

    def inline(text: str) -> str:
        # 1) Protect links so their URLs are never touched by emphasis rules.
        links: list[str] = []

        def _link(m):
            label, url = escape(m.group(1)), escape(m.group(2), quote=True)
            links.append(f'<a href="{url}">{label}</a>')
            return f"\x00{len(links) - 1}\x00"

        text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _link, text)
        # 2) Escape any remaining raw HTML in the plain text.
        text = escape(text)
        # 3) Apply the tiny emphasis subset outside of links.
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
        text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)
        # 4) Restore protected links.
        return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], text)

    html_lines, in_list = [], False
    for raw in md.splitlines():
        line = inline(raw.rstrip())
        if line.startswith("## "):
            if in_list: html_lines.append("</ul>"); in_list = False
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            if in_list: html_lines.append("</ul>"); in_list = False
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            if not in_list: html_lines.append("<ul>"); in_list = True
            html_lines.append(f"<li>{line[2:]}</li>")
        elif not line:
            if in_list: html_lines.append("</ul>"); in_list = False
        else:
            if in_list: html_lines.append("</ul>"); in_list = False
            html_lines.append(f"<p>{line}</p>")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


class Reporter:
    def render(self, title: str, markdown_body: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return _HTML.format(title=title, ts=ts, body=_md_to_html(markdown_body))

    def publish(self, title: str, markdown_body: str) -> str:
        html = self.render(title, markdown_body)
        key = f"briefs/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.html"
        if config.BRIEF_BUCKET:
            return self._publish_s3(key, html)
        return self._publish_local(key, html)

    def _publish_local(self, key: str, html: str) -> str:
        out = config.LOCAL_ROOT / key
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, "utf-8")
        latest = config.LOCAL_ROOT / "latest.html"
        latest.write_text(html, "utf-8")
        return str(out)

    def _publish_s3(self, key: str, html: str) -> str:
        import boto3
        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        for k in (key, "latest.html"):
            s3.put_object(Bucket=config.BRIEF_BUCKET, Key=k, Body=html.encode("utf-8"),
                          ContentType="text/html; charset=utf-8")
        return f"s3://{config.BRIEF_BUCKET}/{key}"

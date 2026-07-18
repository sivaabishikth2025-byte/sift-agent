import re
import pathlib

t = pathlib.Path("ARTICLE.md").read_text(encoding="utf-8")
t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
body = re.sub(r"\[SCREENSHOT[^\]]*\]", "", t)
words = len(re.findall(r"[A-Za-z0-9']+", body))
print("word count:", words, "->", "PASS (>=500)" if words >= 500 else "FAIL")

req = [
    "Weekend Agent Challenge:",
    "#agents",
    "Vision & What the Agent Does",
    "How You Built It",
    "AWS Services Used / Architecture Overview",
    "What You Learned",
    "Link to App or Repo",
]
for r in req:
    print("  OK  " if r in t else "  MISSING  ", r)

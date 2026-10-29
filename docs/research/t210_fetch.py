#!/usr/bin/env python3
"""T-210 页面抓取小工具 —— 只读,只打印命中行。

用法:
    python3 t210_fetch.py <url> [关键词,逗号分隔] [--ctx N] [--maxhits N]

只做三件事:GET → 去 HTML 标签 → 打印命中关键词的行(含上下文)。
不做写库、不注册、不下单、不碰任何 .env。
"""
import argparse
import html
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "ignore")


def to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    raw = re.sub(r"\n{2,}", "\n", raw)
    return raw.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("keywords", nargs="?", default="")
    ap.add_argument("--ctx", type=int, default=0)
    ap.add_argument("--maxhits", type=int, default=40)
    ap.add_argument("--chars", type=int, default=4000)
    a = ap.parse_args()

    try:
        txt = to_text(fetch(a.url))
    except Exception as exc:  # noqa: BLE001
        print("FETCH_ERR", type(exc).__name__, exc)
        return 2

    print("LEN", len(txt), "URL", a.url)
    if not a.keywords:
        print(txt[: a.chars])
        return 0

    pats = [k.strip().lower() for k in a.keywords.split(",") if k.strip()]
    lines = txt.split("\n")
    hits = 0
    shown = set()
    for i, line in enumerate(lines):
        low = line.lower()
        if any(p in low for p in pats):
            lo = max(0, i - a.ctx)
            hi = min(len(lines), i + a.ctx + 1)
            if (lo, hi) in shown:
                continue
            shown.add((lo, hi))
            for j in range(lo, hi):
                print(f"{j}|{lines[j][:600]}")
            print("---")
            hits += 1
            if hits >= a.maxhits:
                break
    print(f"HITS {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

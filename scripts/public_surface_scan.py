#!/usr/bin/env python3
"""部署后核一遍「出去的是什么」:抓线上每一个公开、无参数的 GET 接口,看响应里有没有内部痕迹或指令式说法。

    python3 scripts/public_surface_scan.py                       # 默认打生产
    python3 scripts/public_surface_scan.py --api http://127.0.0.1:8000

判据与测试共用 `src/api/contracts/public_text.py`。有命中 ⇒ 退出码 1,逐条打印「接口 · 字段路径 · 上下文」。
为什么要有它:静态守卫只看得见字面量写在哪;11-14 的 22 处泄漏里,多数字符串写在数据层、由路由原样端出去,只有看响应才看得见。
它看不见的:随状态才出现的句子(比如别的 crowd-clock 相位)—— 那一类由 `tests/test_public_text.py` 按表守。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.api.contracts import public_text as pt  # noqa: E402

API = "https://web-production-0cdf76.up.railway.app"
#: 第三方内容(带署名的新闻标题 / 链接)与开源策略的文件名、框架名:是引用或产品事实,不是我们的话
THIRD_PARTY = ("/api/v1/intelligence/macro-events", "/api/v1/vc/", "/api/v1/market/narrative", "/api/v1/strategies/open-source")
SKIP = ("/", "/api/v1/social/og-image", "/api/v1/share/og-image", "/api/v1/social/og-meta")


def public_get_paths(spec: dict) -> list[str]:
    return sorted(p for p, v in (spec.get("paths") or {}).items()
                  if "get" in v and "{" not in p and not p.startswith("/internal") and "/admin" not in p and p not in SKIP)


def judge(path: str, body) -> dict | None:
    if any(path.startswith(x) for x in THIRD_PARTY):
        return None
    internal = pt.internal_findings(body, cap=6)
    wording = pt.wording_findings(body, cap=6)
    return {"internal": internal, "wording": wording} if internal or wording else None


def _get(url: str, timeout: float = 25.0):
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-public-surface-scan/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if "json" not in (r.headers.get("content-type") or ""):
            return None
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=API)
    a = ap.parse_args()
    paths = public_get_paths(_get(a.api.rstrip("/") + "/openapi.json"))

    def one(p):
        try:
            body = _get(a.api.rstrip("/") + p)
        except Exception as e:                                           # noqa: BLE001 —— 401 / 422 / 超时:读不到就不判,单列
            return p, None, f"{type(e).__name__}: {str(e)[:60]}"
        return p, (judge(p, body) if body is not None else None), None

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, paths))
    hits = [(p, h) for p, h, _ in res if h]
    unread = [(p, e) for p, _, e in res if e]
    for p, h in hits:
        for kind in ("wording", "internal"):
            for f in h[kind]:
                print(f"{kind:8s} {p} {f}")
    print(f"\n{len(paths)} 个公开 GET · 命中 {len(hits)} 个 · 读不到 {len(unread)} 个(需要参数 / 密钥 / 超时,不判)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())

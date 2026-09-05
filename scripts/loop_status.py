#!/usr/bin/env python3
"""开场命令 —— 一屏看清 loop 是不是通的 (S-301)。

## 为什么是这个东西,而不是又一份文档

Jazz, 2026-09-05:

> 「每次你记忆重置就会失去高维度……无论我们写多少 md,因为太多文档就会默认忽略了。」

他观察得准,而当晚有证据:CLAUDE.md 白纸黑字写着「Ingestion is ONE lane」,
实际有 24 条;写着「说『我们没有 X』之前先 grep」,我当天还是先断言后查。
那一晚拦住我的**三次全是测试,文档零次**。

所以这个脚本的定位不是「再加一份要读的东西」,是**把要记住的东西换成要跑的东西**。
一次调用替代一叠文档:

    python3 -m scripts.loop_status

## 三个数,只减不增

    Sense 入口          生产代码里各自发 HTTP 取价的文件数
    无判决对象          census 里没有被判活的表数
    断路 loop 段        Sense→Judge→Act→Learn 里断掉的段数

**为什么是这三个:** 缺陷生成率正比于「可以出错的地方的数量」,而修一个 bug
这三个数一个都不变。所以它们是唯一能判断「今天做的事有没有降低明天的故障率」
的量。任何一个动作,先说它降哪个数;说不出来,那就是在修实例。

## I1:取不到就是 unknown,不是 0

线上端点不可达时**不填 0**。一个 0 在这里会被读成「没有问题」,
而那正是这套东西存在的原因。
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://web-production-0cdf76.up.railway.app"

#: 会被认成「自己发 HTTP 取价」的取价原语。名字是从仓里实际用法抽的。
_PRICE_PRIMITIVES = ("klines", "candleSnapshot", "market_chart", "ohlc/range",
                     "/eod/", "allMids", "metaAndAssetCtxs")
_HTTP_MARKERS = ("httpx.", "client.get", "client.post", 'get(f"http', "requests.")

GREEN, AMBER, RED, GREY = "\033[32m", "\033[33m", "\033[31m", "\033[90m"
BOLD, OFF = "\033[1m", "\033[0m"


def _live(path: str, timeout: float = 25.0):
    """线上 JSON。**失败返回 None,绝不返回空 dict** —— 空 dict 会让下游算出 0。"""
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def sense_entrypoints() -> int:
    """生产代码里各自发 HTTP 取价的文件数。

    CLAUDE.md 规则 3b:「Ingestion is ONE lane (Seth), by function not by path.」
    这个数就是那条规则的实测值。2026-09-05 首测:**24**。
    """
    n = 0
    for d in ("src/data", "src/api"):
        for p in (ROOT / d).rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            try:
                s = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(k in s for k in _PRICE_PRIMITIVES) and any(
                    m in s for m in _HTTP_MARKERS):
                n += 1
    return n


def budgets() -> list[tuple[str, str]]:
    """所有只减不增的预算的当前声明值。**读源码,不读记忆。**"""
    out = []
    for f, pat in (
        ("tests/test_loop_beat.py", r"^NO_BEAT_BUDGET\s*=\s*(\d+)"),
        ("tests/test_loop_beat.py", r"^HARDCODED_OK_BUDGET\s*=\s*(\d+)"),
        ("tests/test_python_version_landmines.py", r"^UTCNOW_BUDGET\s*=\s*(\d+)"),
    ):
        try:
            src = (ROOT / f).read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(pat, src, re.M)
        if m:
            out.append((pat.split(r"\s")[0].lstrip("^"), m.group(1)))
    # 字典型预算数条目
    for f, name in (("tests/test_paid_capability_is_used.py", "NOT_WIRED_YET"),
                    ("tests/test_source_policy.py", "KNOWN_UNGATED")):
        try:
            src = (ROOT / f).read_text(encoding="utf-8")
        except OSError:
            continue
        blk = src.split(f"{name}")[1][:4000] if name in src else ""
        out.append((name, str(blk.count('":') or blk.count("': "))))
    return out


def loop_segments(fresh: dict | None) -> list[tuple[str, str, str]]:
    """四段电流。**返回 (段, 判定, 依据)** —— 判定必须带依据,否则没法反驳。"""
    if fresh is None:
        u = ("unknown", "线上不可达 —— **不是健康,是没测到**")
        return [(s, u[0], u[1]) for s in ("Sense", "Judge", "Act", "Learn")]

    src_block = (fresh.get("by_source") or {}).get("sources") or []
    dead_src = [s["source"] for s in src_block if s.get("verdict") == "DEAD"]
    flowing = [s for s in src_block if s.get("verdict") == "flowing"]
    n_cov = sum(int(s.get("symbols_recent") or 0) for s in flowing)

    prod = fresh.get("producers") or {}
    dead = list(prod.get("dead_or_corrupt") or [])
    stale = list(prod.get("stale_or_empty") or [])

    n_entry = sense_entrypoints()
    sense = ("发散" if n_entry > 1 else "收敛",
             f"{n_entry} 条入口 · {len(dead_src)} 个源已死({','.join(dead_src) or '—'})"
             f" · 在流的源覆盖 {n_cov} 标的")

    loops = fresh.get("loops") or {}
    judge_ok = "cis_scores" not in dead and "cis_scores" not in stale
    judge = ("通" if judge_ok else "断", "cis_scores 在流" if judge_ok
             else "cis_scores 不在流 —— Judge 段断,下游全部无效")

    navs = [t for t in dead + stale if t.endswith("_nav")]
    act = ("发散" if navs else "收敛",
           f"{len(navs)} 本账的表空或陈:{','.join(navs) or '—'}")

    # Learn 是两件事,不是一件 —— 在 max() 上同形,修法完全不同。
    learn_bits = []
    if "signal_outcomes" in dead + stale:
        learn_bits.append("②信号级 outcome 断供(signal_outcomes)")
    learn_bits.append("①的 outcome 已在流(beta_core_nav.excess_return)"
                      "但**没有消费点**")
    learn = ("断路", " · ".join(learn_bits))

    return [("Sense", *sense), ("Judge", *judge), ("Act", *act), ("Learn", *learn)]


def main() -> int:
    fresh = _live("/internal/data-freshness")
    build = _live("/internal/build-state")
    segs = loop_segments(fresh)

    n_entry = sense_entrypoints()
    scope = (fresh or {}).get("verdict_scope") or {}
    covers = scope.get("covers")
    n_uncov = scope.get("n_not_covered")
    n_broken = sum(1 for _, v, _ in segs if v in ("断路", "断"))

    print(f"\n{BOLD}══ CometCloud loop status ══{OFF}")
    if build:
        print(f"{GREY}构建 {build.get('git_sha_short')} · uptime "
              f"{int(build.get('uptime_seconds') or 0)}s{OFF}")
    else:
        print(f"{RED}线上不可达 —— 下面的数只有本地那部分可信{OFF}")

    print(f"\n{BOLD}三个数（只减不增；任何动作先说它降哪一个）{OFF}")
    print(f"  Sense 入口        {BOLD}{n_entry}{OFF}   "
          f"{GREY}生产代码里各自发 HTTP 取价的文件（规则 3b 要求 1）{OFF}")
    print(f"  无判决对象        {BOLD}{n_uncov if n_uncov is not None else '?'}{OFF}"
          f"   {GREY}census 覆盖 {covers or '?'}{OFF}")
    print(f"  断路 loop 段      {BOLD}{n_broken}{OFF} / 4")

    print(f"\n{BOLD}四段电流{OFF}  {GREY}Sense → Judge → Act → Learn 是循环，不是流水线{OFF}")
    for name, verdict, why in segs:
        col = {"通": GREEN, "收敛": GREEN}.get(verdict, RED if verdict in
                                                ("断路", "断") else AMBER)
        print(f"  {name:<7} {col}{verdict:<6}{OFF} {GREY}{why}{OFF}")

    if fresh:
        lp = fresh.get("loops") or {}
        print(f"\n{BOLD}循环{OFF}  心跳 {lp.get('n', '?')} 个 · "
              f"失败 {lp.get('n_failing', '?')} · 拒绝 {lp.get('n_refusing', '?')} · "
              f"旧构建 {lp.get('n_failing_on_stale_build', '?')}")
        for f_ in (lp.get("failing") or []):
            print(f"  {RED}FAIL{OFF} {f_.get('loop')} × {f_.get('n')} "
                  f"{GREY}{str(f_.get('err'))[:60]}{OFF}")
        for r_ in (lp.get("refusing") or []):
            print(f"  {AMBER}REF {OFF} {r_.get('loop')} × {r_.get('n')} "
                  f"{GREY}{str(r_.get('why'))[:60]}{OFF}")

    print(f"\n{BOLD}只减不增的预算{OFF}  {GREY}CI 盯着，越界即红{OFF}")
    for k, v in budgets():
        print(f"  {k:<22} {v}")

    print(f"\n{GREY}规则:一个动作如果不降低上面三个数之一，就不做。"
          f"修 bug 一个都不降。{OFF}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

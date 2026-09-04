#!/usr/bin/env python3
"""Entity/Decision 层的源探针 —— **Mac 侧跑**(CG key 不在沙箱) (S-290).

## 为什么先探再建

Jazz 2026-09-04:「vc funding flow、investment events 这个位置可以解决了吧?
我现在付费的 coingecko analyst 没有吗?有哪些免费的 api 可以实现呢?」

查下来三件事,**没有一件是我能从代码里读出确定答案的**:

① **CG Analyst 没有 VC 融资端点。** `source_policy.PAID_ENTITLEMENTS` 里
   14 项 analyst_only 能力,没有一项是 raises/funding —— CoinGecko 不发布这个。

② **但有四项已付费、零调用的能力**,而其中一项正是 Entity/Decision 层:

       public_treasury_history   上市公司持币 from 2020
       onchain top_holders       持有人结构
       onchain holders_chart     谁在进谁在出
       onchain top_traders       谁在交易

   S-264 我自己写下过它的理由:「MicroStrategy 买 BTC 是一个**有主体、有时点、
   有金额的企业决策,不需要我们推断**」。写完之后一次没调用。

③ **DeFiLlama 的两个端点在代码里都被注释成「paywalled as of ~May 2026」**
   (`/raises` 在 macro_events_scraper + deal_flow;`/emissions` 在 data_layer)。
   **三处都是注释,不是观测** —— 没人在那之后复测过。

> 本周反复咬到的那条:**注释与现实会分叉,而分叉不会报错。**
> 所以在决定「要不要付 DeFiLlama Pro $300/月」或「要不要换 RootData」之前,
> 先让事实说话。

## 它做什么 / 不做什么

**只读,只打印形状。不写库、不改配置、不落任何文件**(除非给 `--json`)。

三个状态必须分开,不能塌成「不可用」:

    ok        200 且有内容        → 可用
    empty     200 但空            → **可用但今天没有数据**,不是不可用
    paywalled 402/403/401         → 要钱
    error     网络/超时/非 JSON    → **读不到 ≠ 没有**(S-180)

用法:
    python3 scripts/probe_entity_sources.py
    python3 scripts/probe_entity_sources.py --json /tmp/entity_sources.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK, EMPTY, PAYWALLED, ERROR = "ok", "empty", "paywalled", "error"

#: 免费源。**含一个已知免费的对照** —— 若对照也失败,那是网络问题不是付费墙,
#: 而把这两种情况混起来正是本周反复出现的那个形状。
FREE_TARGETS = [
    ("defillama:/protocols", "https://api.llama.fi/protocols",
     "⚠️ 对照组 —— 已知免费。它失败 ⇒ 网络问题,不是付费墙"),
    ("defillama:/raises", "https://api.llama.fi/raises",
     "VC 融资轮次 —— 代码注释说 May 2026 起收费,**未经观测**"),
    ("defillama:/emissions", "https://api.llama.fi/emissions",
     "代币解锁日历 —— 同上,注释说收费但没人复测"),
]


def _probe(url: str, headers: dict | None = None, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
        raw = b""
        if code in (401, 402, 403):
            return {"verdict": PAYWALLED, "http": code,
                    "note": "要钱或要 key —— 这是一个确定的答案,不是失败"}
        return {"verdict": ERROR, "http": code, "note": str(e)[:120]}
    except Exception as e:                                      # noqa: BLE001
        return {"verdict": ERROR, "http": None,
                "note": f"{type(e).__name__}: {str(e)[:100]} —— **读不到 ≠ 没有**"}

    txt = raw.decode("utf-8", "ignore")
    low = txt[:400].lower()
    if any(k in low for k in ("upgrade", "subscribe", "pro api", "payment required")):
        return {"verdict": PAYWALLED, "http": code,
                "note": f"200 但正文是升级提示:{txt[:100]}"}
    try:
        data = json.loads(txt)
    except Exception:                                           # noqa: BLE001
        return {"verdict": ERROR, "http": code,
                "note": f"非 JSON({len(raw)} 字节):{txt[:80]}"}

    # 形状:list 直接数,dict 找最大的 list 值
    n, key = (len(data), "(root list)") if isinstance(data, list) else (0, None)
    sample = None
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and len(v) > n:
                n, key = len(v), k
        if key and data.get(key):
            sample = data[key][0]
    elif n:
        sample = data[0]
    return {
        "verdict": OK if n else EMPTY,
        "http": code, "n_records": n, "list_key": key,
        "bytes": len(raw),
        "sample_fields": sorted(sample.keys())[:14] if isinstance(sample, dict) else None,
        "note": ("有数据" if n else
                 "**200 但空 —— 可用,只是今天没有内容**(不要读成不可用)"),
    }


def _cg_key() -> str:
    """按**多个来源**找 key,不是一个。

    ⚠️ 第一版只查 `MAC_ENV`,没找到就报 ABSENT 并把整件事推给 Mac 侧 ——
    而**仓库根目录就有 `.env`**,S-269 的 deep walk 正是靠它从这个沙箱跑通了
    CG Pro(BTC 4,901 根)。**查一个地方没找到,不等于没有。**
    与本周反复出现的形状同源:一个作用域小于问题的检查,读起来就是覆盖。

    只返回 key 供请求头使用,**任何路径都不打印它的值**。
    """
    import os
    for k in ("COINGECKO_API_KEY", "CG_PRO_API_KEY", "COINGECKO_PRO_API_KEY"):
        v = os.environ.get(k)
        if v:
            return v
    try:
        from dotenv import dotenv_values
    except Exception:                                           # noqa: BLE001
        return ""
    cands = [ROOT / ".env"]
    try:
        from src.research.paths import MAC_ENV
        cands.append(MAC_ENV)
    except Exception:                                           # noqa: BLE001
        pass
    for f in cands:
        try:
            if not f.exists():
                continue
            d = dotenv_values(f)
            for k in ("COINGECKO_API_KEY", "CG_PRO_API_KEY",
                      "COINGECKO_PRO_API_KEY"):
                if d.get(k):
                    return d[k]
        except Exception:                                       # noqa: BLE001
            continue
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="out", default=None)
    args = ap.parse_args()
    rows: list = []

    print("═══ 免费源 ═══")
    for name, url, why in FREE_TARGETS:
        r = _probe(url)
        r.update(target=name, why=why)
        rows.append(r)
        print(f"  [{r['verdict']:9s}] {name:26s} http={r.get('http')} "
              f"n={r.get('n_records')} bytes={r.get('bytes')}")
        print(f"      ↳ {why}")
        if r.get("sample_fields"):
            print(f"      字段: {r['sample_fields']}")
        if r["verdict"] in (PAYWALLED, ERROR, EMPTY):
            print(f"      {r['note']}")

    key = _cg_key()
    print(f"\n═══ CoinGecko Pro(key: {'present' if key else 'ABSENT'})═══")
    if not key:
        print("  ✗ 沙箱里没有 key —— **本节必须在 Mac 上跑**")
    else:
        h = {"x-cg-pro-api-key": key}
        cg = [
            ("cg:/key", "https://pro-api.coingecko.com/api/v3/key",
             "档位回声 —— 先确认 Analyst 还在生效"),
            ("cg:public_treasury/bitcoin",
             "https://pro-api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
             "**Entity/Decision 层最干净的样本**(S-264 写下理由,零调用)"),
            ("cg:public_treasury/ethereum",
             "https://pro-api.coingecko.com/api/v3/companies/public_treasury/ethereum",
             "同上,ETH 侧"),
            ("cg:companies/historical/bitcoin",
             "https://pro-api.coingecko.com/api/v3/companies/historical_data/"
             "bitcoin?days=90",
             "**Analyst 档的历史端点** —— S-264 登记为 public_treasury_history,"
             "零调用。通了就能一次回填到 2020,不用等自己攒"),
            ("cg:key", "https://pro-api.coingecko.com/api/v3/key",
             "额度回声 —— 顺便确认 Analyst 还在生效"),
        ]
        for name, url, why in cg:
            r = _probe(url, headers=h)
            r.update(target=name, why=why)
            rows.append(r)
            print(f"  [{r['verdict']:9s}] {name:30s} http={r.get('http')} "
                  f"n={r.get('n_records')}")
            print(f"      ↳ {why}")
            if r.get("sample_fields"):
                print(f"      字段: {r['sample_fields']}")
            if r["verdict"] in (PAYWALLED, ERROR):
                print(f"      {r['note']}")

    ok = [r for r in rows if r["verdict"] == OK]
    control = next((r for r in rows if r["target"] == "defillama:/protocols"), None)
    print(f"\n{len(ok)}/{len(rows)} 个目标可用")
    if control and control["verdict"] != OK:
        print("⚠️ **对照组也失败了** —— 这一轮的所有 defillama 结果都不作数,"
              "先解决网络再重跑。付费墙与网络故障在这里必须分开读。")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""「当前 60 天像历史哪段,那时什么风格在跑」— 相位检索 (S-349)。

    python3 -m src.data.vector.regime_match              # 今天像哪几天
    python3 -m src.data.vector.regime_match 2026-03-11   # 指定某天

这是 HIGH_DIM_ONTOLOGY §5 里标着「📋 规划」的那一行落地:
**「当前60天像历史哪段」= 相位检索。** Jazz 2026-09-15:
「我们是跟踪 beta 的,不管 beta 是涨还是跌,我们就换着法子来匹配符合当时风格跑得好的
策略并且做一定的预判。**不然我们建矢量数据库来做什么呢?**」

⚠️ 为什么不是 pgvector。§4 的存储法则写得很死:
**dense+many → pgvector HNSW;sparse+few → jsonb + NaN-aware 共享维余弦**,
并且「稀疏向量做 0 补齐再算稠密余弦是**错误度量**」。
474 天是 few;每天可测维度 6–11 不等,是 sparse。所以走这条路,不走 ANN。

⚠️ 缺席 ≠ 0。`regime_daily.features` 里**没测到的维度,键直接不存在**(I1)。
把它补成 0 会让「那天 pillar_s 没算出来」和「那天 pillar_s 真的是 0」变成同一个向量 ——
这一年里我们为这一类同形付过太多次钱。共享维余弦只在**双方都有**的键上计算。
"""
from __future__ import annotations

import math
import os
from typing import Any

#: 低于这个共享维数,相似度不可信 —— 两天各只有 3 个维度重合时,
#: 余弦几乎必然接近 1,那是维度太少,不是真的像。
MIN_SHARED_DIMS = 6


def shared_dim_cosine(a: dict[str, Any], b: dict[str, Any]) -> tuple[float | None, int]:
    """(余弦, 共享维数)。共享维不足时返回 (None, n) —— **不是 0.0**。

    None 的意思是「比不了」,0.0 的意思是「完全不像」。两者处置相反:
    前者该去补数据,后者是一个真实结论。
    """
    keys = [k for k in a.keys() & b.keys()
            if isinstance(a[k], (int, float)) and isinstance(b[k], (int, float))]
    if len(keys) < MIN_SHARED_DIMS:
        return None, len(keys)
    va = [float(a[k]) for k in keys]
    vb = [float(b[k]) for k in keys]
    # 逐维 z 化用不了(只有两个样本),所以按各自模长归一 —— 量纲差异由调用方
    # 在建 features 时保证(pillar/score 都已是 0-100,pct 已是 0-1)。
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(x * x for x in vb))
    if na == 0 or nb == 0:
        return None, len(keys)
    return sum(x * y for x, y in zip(va, vb)) / (na * nb), len(keys)


def _fetch(url: str, key: str) -> list[dict]:
    import httpx
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{url}/rest/v1/regime_daily",
                  params={"select": "d,features,regime_db,n_universe,"
                                    "meditation_regime,meditation",
                          "order": "d.asc", "limit": "2000"},
                  headers={"apikey": key, "Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return r.json()


def most_similar(target_d: str, rows: list[dict], k: int = 5,
                 exclude_days: int = 30) -> list[dict]:
    """离 target 最近的 k 天。

    `exclude_days` 挡掉紧邻的日子 —— 昨天当然像今天,那不是信息。
    我们要的是**历史上的相位**,不是时间上的邻居。
    """
    import datetime as dt
    by_d = {r["d"]: r for r in rows}
    tgt = by_d.get(target_d)
    if not tgt:
        return []
    t0 = dt.date.fromisoformat(target_d)
    out = []
    for r in rows:
        if r["d"] == target_d:
            continue
        if abs((dt.date.fromisoformat(r["d"]) - t0).days) <= exclude_days:
            continue
        sim, n = shared_dim_cosine(tgt.get("features") or {}, r.get("features") or {})
        if sim is None:
            continue
        out.append({**r, "sim": sim, "n_shared": n})
    return sorted(out, key=lambda x: -x["sim"])[:k]


def main() -> int:
    import sys
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not (url and key):
        print("需要 SUPABASE_URL / SUPABASE_KEY")
        return 1
    rows = _fetch(url, key)
    target = sys.argv[1] if len(sys.argv) > 1 else max(r["d"] for r in rows)
    hits = most_similar(target, rows)
    tgt = next((r for r in rows if r["d"] == target), None)
    if not tgt:
        print(f"{target}: 库里没有这一天")
        return 1

    print(f"\n目标 {target} · regime={tgt['regime_db']} · universe={tgt['n_universe']}")
    print(f"{'':2}{'日期':<12}{'相似':>6}{'共享维':>7}  regime(库)   判读(人)     有正文")
    print("  " + "-" * 68)
    for h in hits:
        print(f"  {h['d']:<12}{h['sim']:>6.3f}{h['n_shared']:>7}  "
              f"{(h['regime_db'] or '?'):<12} {(h['meditation_regime'] or '—'):<11} "
              f"{'✓' if h.get('meditation') else '—'}")
    med = [h for h in hits if h.get("meditation")]
    if med:
        h = med[0]
        print(f"\n最近相位里有人写过判读 —— {h['d']}(相似 {h['sim']:.3f}):\n")
        print("  " + "\n  ".join(h["meditation"].splitlines()[:14]))
    else:
        print("\n这几个相位当时没人写判读 —— 那是个空白,不是「当时没事」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

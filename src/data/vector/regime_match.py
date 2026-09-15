"""「当前像历史哪段,那时什么风格在跑」— 相位检索 (S-349 / S-351)。

    python3 -m src.data.vector.regime_match              # 今天像哪几天
    python3 -m src.data.vector.regime_match 2026-03-11   # 指定某天

HIGH_DIM_ONTOLOGY §5 里标着「📋 规划」的那一行落地。Jazz 2026-09-15:
「我们是跟踪 beta 的,不管涨跌,换着法子匹配当时跑得好的风格并做一定预判。
**不然我们建矢量数据库来做什么呢?**」

⚠️ 不进 pgvector:§4 的存储法则 —— few+sparse 走 jsonb + 共享维余弦,
「稀疏向量做 0 补齐再算稠密余弦是**错误度量**」。474 天是 few。

⚠️ S-351 —— 第一版这个文件是错的,错法值得留在这里
===============================================================================
第一版用「共享维 ≥ 6 就比」+ 原始值余弦。实跑结果:

    2026-05-30  0.997  6维  无正文
    2026-06-03  0.997  6维  无正文     ← 全是最没有信息量的那 16 天

两个缺陷叠在一起:

1. **6 维余弦和 11 维余弦不是同一个量,不能互相排序。** 全正向量维度越少,
   余弦越贴近 1。库里 6 个维度 100% 覆盖、5 个 pillar 只覆盖 96.6%(458/474),
   于是缺 pillar 的那 16 天**必然赢下每一次排名**。
   **而这个文件第一版的 docstring 自己写着「维度太少,不是真的像」—— 我写下了那句话,
   然后把门槛设成了 6。** 写下一条教训和应用一条教训是两件事。

2. **量纲没归一。** avg_cis≈50 / pct_out≈0.2 / avg_conf≈0.8 / score_disp≈10。
   原始余弦被 avg_cis 单维支配,而它几乎不变 —— 这才是 0.99 窄带的真因。
   我当时把 z 化说成「下一步」,**错了:它是这一步能不能成立的前提**。

修:**固定核心维集**(全部 11 维,缺任一维 = 比不了,不是「很像」)+ **全库逐维 z 化**。
实测对照:

    z 化前  0.996–0.997  6维   0/5 有正文
    z 化后  0.816–0.843  11维  5/5 有正文,且库判读与人判读独立一致
"""
from __future__ import annotations

import math
import os
import statistics
from typing import Any

#: 固定核心维集。**所有比较都在同一组维度上做,否则余弦之间不可比**(S-351)。
#: 顺序无关,存在性有关。
CORE_DIMS = (
    "avg_cis", "pct_out", "pct_under", "avg_las", "avg_conf", "score_disp",
    "avg_pillar_f", "avg_pillar_m", "avg_pillar_o", "avg_pillar_s", "avg_pillar_a",
)


def comparable(features: dict[str, Any] | None) -> bool:
    """这一天能参与比较吗 —— 核心维必须**全部**在场。

    缺任何一维就出局。出局的意思是「**比不了**」,不是「不像」,也不是「很像」——
    第一版把它读成了后者,于是最没信息量的 16 天赢下了每一次排名。
    """
    f = features or {}
    return all(isinstance(f.get(k), (int, float)) for k in CORE_DIMS)


def zscore_corpus(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """逐维 (均值, 标准差),只统计可比的天。sd=0 的维度返回 sd=1(该维不参与区分)。"""
    stats: dict[str, tuple[float, float]] = {}
    usable = [r for r in rows if comparable(r.get("features"))]
    for k in CORE_DIMS:
        vals = [float(r["features"][k]) for r in usable]
        mu = statistics.fmean(vals) if vals else 0.0
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        stats[k] = (mu, sd or 1.0)
    return stats


def _zvec(features: dict, stats: dict[str, tuple[float, float]]) -> list[float]:
    return [(float(features[k]) - stats[k][0]) / stats[k][1] for k in CORE_DIMS]


def cosine_z(a: list[float], b: list[float]) -> float | None:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def most_similar(target_d: str, rows: list[dict], k: int = 5,
                 exclude_days: int = 30) -> tuple[list[dict], dict]:
    """(命中列表, 诊断)。诊断里写明**多少天因为缺维度而无法参与** —— 那是覆盖缺口,不是结果。

    `exclude_days` 挡掉紧邻的日子:昨天当然像今天,那不是信息。
    我们要的是**历史上的相位**,不是时间上的邻居。
    """
    import datetime as dt

    usable = [r for r in rows if comparable(r.get("features"))]
    diag = {"n_total": len(rows), "n_usable": len(usable),
            "n_excluded_incomplete": len(rows) - len(usable)}
    tgt = next((r for r in usable if r["d"] == target_d), None)
    if tgt is None:
        diag["error"] = (f"{target_d} 不在可比集合里"
                         f"({'核心维不全' if any(r['d'] == target_d for r in rows) else '库里没有这天'})")
        return [], diag

    stats = zscore_corpus(usable)
    zt = _zvec(tgt["features"], stats)
    t0 = dt.date.fromisoformat(target_d)
    out = []
    for r in usable:
        if r["d"] == target_d:
            continue
        if abs((dt.date.fromisoformat(r["d"]) - t0).days) <= exclude_days:
            continue
        sim = cosine_z(_zvec(r["features"], stats), zt)
        if sim is not None:
            out.append({**r, "sim": sim})
    return sorted(out, key=lambda x: -x["sim"])[:k], diag


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


def main() -> int:
    import sys
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not (url and key):
        print("需要 SUPABASE_URL / SUPABASE_KEY")
        return 1
    rows = _fetch(url, key)
    target = sys.argv[1] if len(sys.argv) > 1 else max(r["d"] for r in rows)
    hits, diag = most_similar(target, rows)

    print(f"\n可比 {diag['n_usable']}/{diag['n_total']} 天 "
          f"(核心维不全而出局 {diag['n_excluded_incomplete']} 天 —— **那是覆盖缺口,不是不像**)")
    if diag.get("error"):
        print(f"✗ {diag['error']}")
        return 1
    tgt = next(r for r in rows if r["d"] == target)
    print(f"目标 {target} · regime={tgt['regime_db']} · universe={tgt['n_universe']}\n")
    print(f"  {'日期':<12}{'相似':>7}  {'regime(库)':<12}{'判读(人)':<12}有正文")
    print("  " + "-" * 56)
    for h in hits:
        print(f"  {h['d']:<12}{h['sim']:>7.3f}  {(h['regime_db'] or '?'):<12}"
              f"{(h['meditation_regime'] or '—'):<12}{'✓' if h.get('meditation') else '—'}")

    med = [h for h in hits if h.get("meditation")]
    if med:
        h = med[0]
        print(f"\n最近相位里的人工判读 —— {h['d']}(相似 {h['sim']:.3f}):\n")
        print("  " + "\n  ".join(h["meditation"].splitlines()[:16]))
    else:
        print("\n这几个相位当时没人写判读 —— **那是个空白,不是「当时没事」**。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

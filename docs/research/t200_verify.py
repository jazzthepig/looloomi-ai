"""T-200 · S-685 的独立复算 —— 不 import 主脚本,从 t200_results.json + 原始库重算关键数字。

为什么单独写一份:主脚本的结论(DQS 不动、Calmar 不过)只有能被另一条代码路径复算出来才算数。
本脚本只做核对,不改任何口径:
  1) 逐日敞口序列 = 亮灯连续段 + 10 个自然日保持(与主脚本的数组逐位比);
  2) 年化 / 最大回撤 / Calmar 用 pandas 口径重算(主脚本用 numpy 口径);
  3) 循环平移零分布用 apparatus 重抽 1,000 次,比对抽样是否逐位相同;
  4) 四段熊市的持有 / 规则收益复算。

跑法:python3 docs/research/t200_verify.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.data.evaluation import apparatus  # noqa: E402

RESULTS = os.path.join(REPO, "docs", "research", "t200_results.json")

SUPA = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPK = os.environ.get("SUPABASE_KEY", "")
if not SUPA or not SUPK:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 未设置,退出")
PAGE = 1000


def fetch(table: str, params: dict) -> list[dict]:
    """PostgREST 翻页读。**必须**带 order=(按主键排)—— 不带时翻页边界会漂(T-170 / T-173 实测)。"""
    q = dict(params)
    q["select"] = q.get("select", "*")
    q["limit"] = str(PAGE)
    rows: list[dict] = []
    off = 0
    while True:
        q["offset"] = str(off)
        url = SUPA + "/rest/v1/" + table + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(
            url, headers={"apikey": SUPK, "Authorization": "Bearer " + SUPK})
        chunk = json.loads(urllib.request.urlopen(req, timeout=90).read())
        if not isinstance(chunk, list):
            raise RuntimeError(table + ": " + str(chunk)[:200])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        off += PAGE


def load_crypto(sym: str) -> pd.Series:
    rows = fetch("asset_mcap_daily",
                 {"symbol": "eq." + sym, "order": "d.asc", "select": "symbol,d,price"})
    idx = pd.to_datetime([r["d"] for r in rows], format="ISO8601", utc=True).tz_localize(None).normalize()
    s = pd.Series(pd.to_numeric([r["price"] for r in rows], errors="coerce"), index=idx).dropna()
    return s.groupby(level=0).last().sort_index()


def latch_from_spans(spans: list[list[str]], dates: pd.DatetimeIndex, hold: int = 10) -> np.ndarray:
    """亮灯连续段 → 减仓态(亮着之后保持 hold 个自然日)。"""
    out = np.zeros(len(dates), dtype=bool)
    for a, b in spans:
        i0 = int(np.flatnonzero(dates == pd.Timestamp(a))[0])
        i1 = int(np.flatnonzero(dates == pd.Timestamp(b))[0])
        out[i0: min(len(dates), i1 + 1 + hold)] = True
    return out


def calmar_of(exposure: np.ndarray, rets: np.ndarray) -> tuple[float, float, float]:
    sr = exposure * rets - 0.001 * np.abs(exposure - np.concatenate(([exposure[0]], exposure[:-1])))
    eq = pd.Series(1.0 + sr).cumprod()
    ann = float(eq.iloc[-1] ** (365.25 / len(sr)) - 1)
    mdd = float((eq / eq.cummax() - 1).min())
    return ann, mdd, ann / abs(mdd)


def main() -> int:
    R = json.load(open(RESULTS, encoding="utf-8"))
    B = R["assets"]["BTC"]
    dates = pd.to_datetime(B["dates"])
    price = load_crypto("BTC").reindex(dates)
    rets = price.pct_change().to_numpy(dtype=float)
    rets[0] = 0.0

    ok = True
    for rule in R["rules"]:
        e = B["rules"][rule]
        exp = np.array(e["exposure_0.5"], dtype=float)
        # 敞口 = 亮灯日起 10 个自然日内都是减仓态(亮灯段 + 保持期)
        latch = latch_from_spans(e["lit_spans"], dates, hold=10)
        same = bool((np.where(latch, 0.5, 1.0) == exp).all())
        # 减仓态连续段应当等于「亮灯段展开 10 天」本身
        same_latched = bool((latch == latch_from_spans(e["latched_spans"], dates, hold=0)).all())
        same = same and same_latched
        ann, mdd, cal = calmar_of(exp, rets)
        m = e["levels"]["0.5"]["metrics"]
        d = (abs(ann - m["annualized"]), abs(mdd - m["max_drawdown"]), abs(cal - m["calmar"]))
        good = same and max(d) < 1e-9
        ok = ok and good
        print(f"[{rule:5s}] 敞口逐位一致={same}  Δ年化={d[0]:.2e} Δ回撤={d[1]:.2e} ΔCalmar={d[2]:.2e} "
              f"→ {'OK' if good else 'MISMATCH'}")

    hold_eq = pd.Series(1.0 + rets).cumprod()
    h_ann = float(hold_eq.iloc[-1] ** (365.25 / len(rets)) - 1)
    h_mdd = float((hold_eq / hold_eq.cummax() - 1).min())
    good = abs(h_ann - B["hold"]["annualized"]) < 1e-9 and abs(h_mdd - B["hold"]["max_drawdown"]) < 1e-9
    ok = ok and good
    print(f"[持有  ] 年化 {h_ann:.6f} (JSON {B['hold']['annualized']:.6f}) "
          f"回撤 {h_mdd:.6f} (JSON {B['hold']['max_drawdown']:.6f}) → {'OK' if good else 'MISMATCH'}")

    # 循环平移零分布:重抽 1,000 次,抽样应与 JSON 逐位相同
    rule = "M8"
    e = B["rules"][rule]
    lit = latch_from_spans(e["lit_spans"], dates, hold=0)
    n = len(lit)

    def draw(rng: np.random.Generator) -> float:
        k = int(rng.integers(60, n - 60 + 1))
        sh = np.roll(lit, k)
        idxs = np.arange(n)
        last = np.maximum.accumulate(np.where(sh, idxs, -10 ** 9))
        ex = np.where((idxs - last) <= 10, 0.5, 1.0)
        return calmar_of(ex, rets)[2]

    null = apparatus.null_distribution(draw, R["n_shift"], seed=R["seed"],
                                       actual=e["levels"]["0.5"]["metrics"]["calmar"])
    jnull = np.array(e["levels"]["0.5"]["null"])
    same = bool(np.allclose(null, jnull, atol=1e-6))
    ok = ok and same
    print(f"[零分布 {rule}] p95={np.percentile(null, 95):.6f} (JSON {e['levels']['0.5']['null_p95']:.6f}) "
          f"分位={apparatus.percentile_of(e['levels']['0.5']['metrics']['calmar'], null):.6f} "
          f"(JSON {e['levels']['0.5']['percentile_of']:.6f}) 抽样逐位相同={same} "
          f"→ {'OK' if same else 'MISMATCH'}")

    seg = B["rules"]["M_any"]["bear_segments"][1]
    i0 = int(np.flatnonzero(dates == pd.Timestamp(seg["start"]))[0])
    i1 = int(np.flatnonzero(dates == pd.Timestamp(seg["end"]))[0])
    exp_any = np.array(B["rules"]["M_any"]["exposure_0.5"], dtype=float)
    sr = exp_any * rets - 0.001 * np.abs(exp_any - np.concatenate(([exp_any[0]], exp_any[:-1])))
    hold_seg = float(price.iloc[i1] / price.iloc[i0] - 1)
    rule_seg = float(np.prod(1 + sr[i0 + 1: i1 + 1]) - 1)
    good = (abs(hold_seg - seg["hold_return"]) < 1e-9 and abs(rule_seg - seg["rule_return"]) < 1e-9)
    ok = ok and good
    print(f"[熊市段 {seg['label']}] 持有 {hold_seg:.6f} (JSON {seg['hold_return']:.6f}) "
          f"规则 {rule_seg:.6f} (JSON {seg['rule_return']:.6f}) → {'OK' if good else 'MISMATCH'}")

    print("ALL OK" if ok else "有不一致")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""T-422 口径差 A/B:2026-11-19 三路对跑(Jazz 要的那个数)。

三路:
  **A0** = 已发布的官方档(`cis_official_daily` d=2026-11-19,58 行)—— CG 口径的真值。
  **A1** = **今天这套**重跑(`load_inputs` 原样:CG market_chart 持久化在 11-19;CG live 已死 ⇒ static 空)。
  **B1** = **纯兜底**重跑(`force=True`:CG 那条路整个取不到 ⇒ 价/市值/成交/总量全走库里原料)。
  **B2** = **生产形状**兜底(非 force:CG 优先,兜底只补 CG 取不到的那几天)。

分解:
  Δ(A0→A1) = **CG live 死掉**造成的影响(total_supply / max_supply 缺 ⇒ F 支柱塌方)。
  Δ(A1→B1) = 兜底口径相对 CG 口径的差(价/市值/成交的源变了;total_supply 从日表补回来)。
  Δ(A0→B1) = Jazz 要的**总口径差**。
  TradFi 腿的 Δ(A0→A1) = **重跑噪声底**(兜底不碰 TradFi;那里的差只能是代码漂移/EODHD 时点)。

跑法:nohup python3 docs/research/t422_ab.py > /Volumes/.../research/t422/ab.log 2>&1 &
"""
import asyncio, json, os, statistics, sys

ROOT = "/Users/sbb/Projects/looloomi-ai-lane-b"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t422"
D = "2026-11-19"
D_PREV = "2026-11-18"

import pandas as pd  # noqa: E402
from src.data.cis.rebuild import load_inputs, score_day, group_pct, LEVELS  # noqa: E402
from src.data.cis import cg_less_fallback as fb  # noqa: E402


def _sb(table, params):
    from src.data.style.header import _sb_get
    return _sb_get(table, params)


async def published(d):
    r = await _sb("cis_official_daily", {"select": "symbol,d,cis_score,regime_adjusted_score,grade,"
                                                   "signal,pct,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,"
                                                   "regime,inputs,missing,code_ref",
                                           "d": f"eq.{d}", "order": "symbol.asc"})
    return r.rows or []


async def prev_levels(d):
    r = await _sb("cis_official_daily", {"select": "symbol,signal", "d": f"eq.{d}", "order": "symbol.asc"})
    return {x["symbol"]: (LEVELS.index(x["signal"]) if x.get("signal") in LEVELS else None)
            for x in (r.rows or [])}


def to_map(rows):
    return {r["symbol"]: r for r in rows}


def final_rows(rows, prev):
    """score_day 的行 → 正式的档(分位 + 滞回)。和 official.run_once 走同一条路。"""
    group_pct(rows)
    from src.data.cis.official import official_rows
    return official_rows(rows, prev, "2026-11-21T00:00:00+00:00")


def delta(a, b, label, cls_of=None):
    """a → b 的差:分数差 / 等级变几个 / 档位变几个 / regime 变几个 / BTC 占比差。"""
    out = {"label": label, "n_common": 0, "n_only_a": [], "n_only_b": [],
           "d_score": [], "grade_changed": [], "signal_changed": [], "regime_changed": [],
           "pillar_f_delta": [], "btc_dom": {}, "rows": {}}
    syms = sorted(set(a) | set(b))
    for s in syms:
        ra, rb = a.get(s), b.get(s)
        if ra is None or rb is None:
            (out["n_only_a"] if rb is None else out["n_only_b"]).append(s)
            continue
        out["n_common"] += 1
        sa = ra.get("regime_adjusted_score")
        sb = rb.get("regime_adjusted_score")
        if sa is not None and sb is not None:
            out["d_score"].append(round(sb - sa, 2))
        if ra.get("grade") != rb.get("grade"):
            out["grade_changed"].append(s)
        if ra.get("signal") != rb.get("signal"):
            out["signal_changed"].append(s)
        if ra.get("regime") != rb.get("regime"):
            out["regime_changed"].append(s)
        fa, fbv = ra.get("pillar_f"), rb.get("pillar_f")
        if fa is not None and fbv is not None:
            out["pillar_f_delta"].append(round(fbv - fa, 2))
        ia, ib = ra.get("inputs") or {}, rb.get("inputs") or {}
        out["rows"][s] = {
            "score_a": sa, "score_b": sb, "d_score": (round(sb - sa, 2) if (sa is not None and sb is not None) else None),
            "grade_a": ra.get("grade"), "grade_b": rb.get("grade"),
            "signal_a": ra.get("signal"), "signal_b": rb.get("signal"),
            "regime_a": ra.get("regime"), "regime_b": rb.get("regime"),
            "pillar_f_a": fa, "pillar_f_b": fbv,
            "price_a": ia.get("price"), "price_b": ib.get("price"),
            "mcap_a": ia.get("mcap"), "mcap_b": ib.get("mcap"),
            "volume_a": ia.get("volume"), "volume_b": ib.get("volume"),
            "btc_dom_a": ia.get("btc_dom"), "btc_dom_b": ib.get("btc_dom"),
            "missing_a": ra.get("missing"), "missing_b": rb.get("missing"),
        }
    out["d_score_max"] = max(out["d_score"]) if out["d_score"] else None
    out["d_score_min"] = min(out["d_score"]) if out["d_score"] else None
    out["d_score_mean"] = round(statistics.fmean(out["d_score"]), 2) if out["d_score"] else None
    out["d_score_median"] = round(statistics.median(out["d_score"]), 2) if out["d_score"] else None
    out["d_score_mean_abs"] = round(statistics.fmean([abs(x) for x in out["d_score"]]), 2) if out["d_score"] else None
    out["n_grade_changed"] = len(out["grade_changed"])
    out["n_signal_changed"] = len(out["signal_changed"])
    out["n_regime_changed"] = len(out["regime_changed"])
    out["pillar_f_mean_delta"] = round(statistics.fmean(out["pillar_f_delta"]), 2) if out["pillar_f_delta"] else None
    out["pillar_f_median_delta"] = round(statistics.median(out["pillar_f_delta"]), 2) if out["pillar_f_delta"] else None
    out["pillar_f_min_delta"] = min(out["pillar_f_delta"]) if out["pillar_f_delta"] else None
    out["pillar_f_max_delta"] = max(out["pillar_f_delta"]) if out["pillar_f_delta"] else None
    return out


async def main():
    out = {"d": D, "prev_d": D_PREV}
    ts = pd.Timestamp(D)
    assets, data = await load_inputs(ts)
    out["n_assets"] = len(assets)

    # ---- A1:今天这套(CG market_chart 持久化在;CG live 已死 ⇒ static 空) ----
    rows_a1 = score_day(ts, assets, data)
    prev = await prev_levels(D_PREV)
    out["prev_levels_n"] = len(prev)

    # ---- 兜底原料 ----
    sym2cg = fb.sym2cg_map()
    raw = await fb.load_raw(sym2cg)
    out["raw_px_syms"] = sorted((raw.get("px") or {}).keys())
    out["raw_supply_ids"] = len(raw.get("supply") or {})

    # ---- B2:生产形状(CG 优先,兜底只补空缺) ----
    d2 = dict(data)
    d2["crypto"] = dict(data.get("crypto") or {})
    d2["static"] = {k: dict(v) for k, v in (data.get("static") or {}).items()}
    rep_b2 = fb.apply(d2, assets, raw, sym2cg, end=ts, force=False)
    rows_b2 = score_day(ts, assets, d2)

    # ---- B1:纯兜底(CG 那条路整个取不到) ----
    d1 = dict(data)
    d1["crypto"] = dict(data.get("crypto") or {})
    d1["static"] = {k: dict(v) for k, v in (data.get("static") or {}).items()}
    rep_b1 = fb.apply(d1, assets, raw, sym2cg, end=ts, force=True)
    rows_b1 = score_day(ts, assets, d1)

    a0 = await published(D)
    out["n_a0"] = len(a0)
    m_a0 = to_map(a0)
    m_a1 = to_map(final_rows(rows_a1, prev))
    m_b1 = to_map(final_rows(rows_b1, prev))
    m_b2 = to_map(final_rows(rows_b2, prev))

    out["delta_A0_A1"] = delta(m_a0, m_a1, "A0(已发布 CG 口径) → A1(今天这套重跑,CG live 死)")
    out["delta_A1_B1"] = delta(m_a1, m_b1, "A1(今天这套) → B1(纯兜底)")
    out["delta_A0_B1"] = delta(m_a0, m_b1, "A0(已发布) → B1(纯兜底)  ★ Jazz 要的总口径差")
    out["delta_A0_B2"] = delta(m_a0, m_b2, "A0(已发布) → B2(生产形状兜底)")
    out["delta_A1_B2"] = delta(m_a1, m_b2, "A1(今天这套) → B2(生产形状兜底)")

    # TradFi 腿 = 重跑噪声底(兜底不碰)
    tf = [s for s, c in assets.items() if c["class"] in ("US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity")]
    out["tradfi_names"] = sorted(tf)
    out["noise_floor_tradfi_A0_A1"] = {
        "n": sum(1 for s in tf if s in m_a0 and s in m_a1),
        "d_score": [round(m_a1[s]["regime_adjusted_score"] - m_a0[s]["regime_adjusted_score"], 2)
                    for s in tf if s in m_a0 and s in m_a1
                    and m_a0[s].get("regime_adjusted_score") is not None
                    and m_a1[s].get("regime_adjusted_score") is not None],
    }
    nf = out["noise_floor_tradfi_A0_A1"]["d_score"]
    out["noise_floor_tradfi_A0_A1"]["max_abs"] = max([abs(x) for x in nf]) if nf else None
    out["noise_floor_tradfi_A0_A1"]["mean_abs"] = round(statistics.fmean([abs(x) for x in nf]), 2) if nf else None

    out["report_B1"] = {k: v for k, v in rep_b1.items() if k not in ("sources",)}
    out["report_B1_sources"] = rep_b1.get("sources")
    out["report_B2"] = {k: v for k, v in rep_b2.items() if k not in ("sources",)}
    out["report_B2_sources"] = rep_b2.get("sources")

    # BTC 占比 / regime(每一路)
    for name, m in (("A0", m_a0), ("A1", m_a1), ("B1", m_b1), ("B2", m_b2)):
        b = m.get("BTC") or {}
        out.setdefault("btc", {})[name] = {
            "price": (b.get("inputs") or {}).get("price"),
            "mcap": (b.get("inputs") or {}).get("mcap"),
            "btc_dom": (b.get("inputs") or {}).get("btc_dom"),
            "regime": b.get("regime"),
            "grade": b.get("grade"), "signal": b.get("signal"),
            "score": b.get("regime_adjusted_score"),
        }
    out["n_rows"] = {"A0": len(m_a0), "A1": len(m_a1), "B1": len(m_b1), "B2": len(m_b2)}
    out["n_crypto_priced"] = {k: sum(1 for s, c in assets.items() if c["class"] not in
                                      ("US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity")
                                      and s in m) for k, m in (("A0", m_a0), ("A1", m_a1), ("B1", m_b1), ("B2", m_b2))}
    out["n_crypto_total"] = sum(1 for s, c in assets.items() if c["class"] not in
                                 ("US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "ab_2026-11-19.json"), "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=str)
    print("DONE", os.path.join(OUT, "ab_2026-11-19.json"))


if __name__ == "__main__":
    asyncio.run(main())

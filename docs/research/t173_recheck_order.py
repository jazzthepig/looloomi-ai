"""T-173(S-634 复核):origin/main 上补了 order= 的 t148 原样重跑,判定变不变?

两件事:
  1. 用与 t148 完全相同的 fetch_all 翻页逻辑,对同一批 panel 符号各取一次
     「带 order」与「不带 order」的 ohlcv_daily,比 (symbol, trade_date) 集合。
     T-170(B 道)的说法是:行数对得上,但不带 order 时 PostgREST 翻页边界会漂,
     同一批行落在不同的 (symbol, date) 上 ⇒ 静默少两成。带 order 的集合是基准。
  2. 把新跑出来的 t148_results.json 与 S-634 原判定(t173_s634_prior_results.json,
     = 补 order 之前那一次)逐字段对比,判据不改。

不重写任何判据、不重写零分布:NAV 口径与 200 次打乱都在 t148 里,这里只做取数对比。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import t148_alt_momentum_tilt as t148  # noqa: E402

REBAL_INCEPTION = t148.REBAL_INCEPTION
N_UNORDERED_REPEATS = 3


def fetch_ohlcv_no_order(symbols: list[str]) -> tuple[dict[str, dict[str, float]], int]:
    """fetch_ohlcv 的原版:同一查询,只是拿掉 order=。返回 (价格字典, 原始行数)。

    原始行数要留着:T-170 的说法是「行数对得上、不同的 (symbol, date) 少两成」——
    只有把原始行数与去重后的键数并排放,才看得出是翻页重复吃掉了行,还是少取到了行。
    """
    sym_list = ",".join(f'"{s}"' for s in symbols)
    rows = t148.fetch_all(
        f"ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist"
        f"&symbol=in.({sym_list})&trade_date=gte.{REBAL_INCEPTION}"
    )
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        d = str(r["trade_date"])[:10]
        c = r.get("close")
        if c is not None:
            out.setdefault(r["symbol"], {})[d] = float(c)
    return out, len(rows)


def keys_of(px: dict[str, dict[str, float]]) -> set[tuple[str, str]]:
    return {(s, d) for s, byd in px.items() for d in byd}


def price_disagreements(a: dict[str, dict[str, float]], b: dict[str, dict[str, float]]) -> int:
    n = 0
    for (s, d) in keys_of(a) & keys_of(b):
        if a[s][d] != b[s][d]:
            n += 1
    return n


def compare(ordered: dict[str, dict[str, float]], other: dict[str, dict[str, float]],
            n_rows_ordered: int, n_rows_unordered: int) -> dict:
    ko, kx = keys_of(ordered), keys_of(other)
    missing = ko - kx
    extra = kx - ko
    per_symbol_missing: dict[str, int] = {}
    for s, _ in missing:
        per_symbol_missing[s] = per_symbol_missing.get(s, 0) + 1
    per_symbol_ordered = {s: len(v) for s, v in ordered.items()}
    per_symbol_other = {s: len(v) for s, v in other.items()}
    worst = sorted(per_symbol_missing.items(), key=lambda kv: -kv[1])[:8]
    return {
        "n_raw_rows_ordered": n_rows_ordered,
        "n_raw_rows_unordered": n_rows_unordered,
        "n_keys_ordered": len(ko),
        "n_keys_unordered": len(kx),
        "n_missing_vs_ordered": len(missing),
        "missing_pct": round(100.0 * len(missing) / len(ko), 3) if ko else None,
        "n_extra_vs_ordered": len(extra),
        "n_price_disagreements_on_shared_keys": price_disagreements(ordered, other),
        "n_symbols_ordered": len(ordered),
        "n_symbols_unordered": len(other),
        "worst_symbols_by_missing": worst,
        "per_symbol_ordered_count": per_symbol_ordered,
        "per_symbol_unordered_count": per_symbol_other,
        "date_range_ordered": [min(d for _, d in ko), max(d for _, d in ko)] if ko else None,
        "date_range_unordered": [min(d for _, d in kx), max(d for _, d in kx)] if kx else None,
        "sample_missing": sorted(missing)[:10],
    }


def v3_pipeline(px: dict[str, dict[str, float]], names: list[str]) -> dict:
    """把 t148 的原样流程在给定价格集上跑一遍(反推 w_① → V3 30d → 200 次打乱)。

    只换 px,判据、随机种子、打乱次数、NAV 口径全部沿用 t148 —— 目的是量「同一套判据
    喂进一个缺两成价格的分页结果时,结论会不会翻」,不是另起一个实验。
    """
    import numpy as np
    from src.data.evaluation.apparatus import shuffle_within

    ct_rows = t148.fetch_all("cis_tilt_daily?select=d,arm,nav,ret,weights,z,rebalanced,turnover"
                             "&arm=eq.cis_a1_u_replay&order=d.asc")
    w0_per_date = {r["d"]: t148.back_solve_w0(r["weights"], r["z"] or {})
                   for r in ct_rows if r.get("rebalanced") and r.get("weights")}
    rebal_dates = sorted(w0_per_date.keys())

    v0_nav, _ = t148.run_weekly(rebal_dates, w0_per_date, px, names, inception_nav=1.0)
    z30 = {d: t148.compute_momentum_z(px, names, d, t148.MOMENTUM_DAYS_PRIMARY)
           for d in rebal_dates}
    v3_w = {d: t148.build_v3_weights(w0_per_date[d], z30[d], names, k=0.5) for d in rebal_dates}
    v3_nav, _ = t148.run_weekly(rebal_dates, v3_w, px, names, inception_nav=1.0)

    v0_total, v3_total = t148.nav_total(v0_nav), t148.nav_total(v3_nav)
    v0_ho = t148.nav_total_holdout(v0_nav)
    v3_ho = t148.nav_total_holdout(v3_nav)
    diff_all, diff_ho = v3_total - v0_total, v3_ho - v0_ho

    rng = np.random.default_rng(t148.SEED)
    alts = [s for s in names if s not in t148.PANEL_BTC_ETH]
    sh_totals = []
    for _ in range(t148.N_SHUFFLES):
        sh_w = {}
        for d in rebal_dates:
            sh_z = dict(z30[d])
            vals = np.array([sh_z[s] for s in alts], dtype=float)
            vals_sh = shuffle_within(vals.tolist(), ["x"] * len(alts), rng)
            for s, v in zip(alts, vals_sh):
                sh_z[s] = float(v)
            sh_w[d] = t148.build_v3_weights(w0_per_date[d], sh_z, names, k=0.5)
        sh_nav, _ = t148.run_weekly(rebal_dates, sh_w, px, names, inception_nav=1.0)
        sh_totals.append(t148.nav_total(sh_nav))
    s_full = np.array(sh_totals)
    pctile = float((s_full - v0_total < diff_all).mean())
    return {
        "n_price_symbols": len(px),
        "n_price_pairs": sum(len(v) for v in px.values()),
        "v0_total": round(v0_total, 4),
        "v3_total": round(v3_total, 4),
        "diff_full": round(diff_all, 4),
        "diff_2025_holdout": round(diff_ho, 4),
        "pctile_v3_minus_v0_full": round(pctile, 4),
        "judgement_pass": bool((diff_all > 0) and (diff_ho > 0) and (pctile > 0.95)),
    }


def main() -> int:
    prior_path = HERE / "t173_s634_prior_results.json"
    new_path = HERE / "t148_results.json"
    prior = json.loads(prior_path.read_text())
    new = json.loads(new_path.read_text())
    names = prior["panel"]["names"]

    print(f"[T-173] panel {len(names)} symbols; ordered fetch ...", flush=True)
    sym_list = ",".join(f'"{s}"' for s in names)
    ordered_rows = t148.fetch_all(
        f"ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist"
        f"&symbol=in.({sym_list})&trade_date=gte.{REBAL_INCEPTION}"
        f"&order=symbol.asc,trade_date.asc"
    )
    ordered = t148.fetch_ohlcv(names)
    n_rows_ordered = len(ordered_rows)
    print(f"  ordered: {len(names)} symbols, {n_rows_ordered} raw rows, "
          f"{sum(len(v) for v in ordered.values())} distinct (symbol, date) pairs", flush=True)

    repeats = []
    degraded_px = None
    for i in range(N_UNORDERED_REPEATS):
        print(f"[T-173] unordered fetch #{i + 1} ...", flush=True)
        uo, n_rows_uo = fetch_ohlcv_no_order(names)
        cmp_i = compare(ordered, uo, n_rows_ordered, n_rows_uo)
        repeats.append(cmp_i)
        if degraded_px is None and cmp_i["n_missing_vs_ordered"] > 0:
            degraded_px = uo
        print(f"  raw_rows={n_rows_uo} pairs={cmp_i['n_keys_unordered']} "
              f"missing={cmp_i['n_missing_vs_ordered']} ({cmp_i['missing_pct']}%)", flush=True)

    # 探索性:若 S-634 那次真的吃到这种缺两成的分页结果,判定会不会翻
    degraded_run = None
    if degraded_px is not None:
        print("[T-173] EXPLORATORY: re-running the same t148 pipeline on the degraded "
              "price set (missing ~20% of (symbol, date))...", flush=True)
        degraded_run = v3_pipeline(degraded_px, names)
        print(f"  degraded: diff_full={degraded_run['diff_full']} "
              f"diff_holdout={degraded_run['diff_2025_holdout']} "
              f"pctile={degraded_run['pctile_v3_minus_v0_full']} "
              f"judgement={degraded_run['judgement_pass']}", flush=True)

    # 其它 fetch_all 调用点是否都带 order
    src = (HERE / "t148_alt_momentum_tilt.py").read_text()
    call_sites = []
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "fetch_all(" in line and "def fetch_all" not in line:
            block = " ".join(lines[i:i + 3])
            call_sites.append({
                "line": i + 1,
                "query": block.strip()[:160],
                "has_order": "order=" in block,
            })

    def cmp_block(tag: str) -> dict:
        p, n = prior[tag], new[tag]
        return {
            "prior": p,
            "new": n,
            "identical": p == n,
            "changed_fields": {k: [p.get(k), n.get(k)] for k in set(p) | set(n)
                               if p.get(k) != n.get(k)},
        }

    out = {
        "ticket": "T-173",
        "question": "S-634 复核:t148 fetch_ohlcv 补 order= 后原样重跑,判定变不变?",
        "script_ran": "docs/research/t148_alt_momentum_tilt.py (origin/main @ f1814761, 判据未改)",
        "data_window": new["data_window"],
        "panel_size": new["panel"]["size"],
        "ohlcv_order_diff": {
            "n_unordered_repeats": N_UNORDERED_REPEATS,
            "repeats": repeats,
            "repeats_identical_rowcounts": len({r["n_keys_unordered"] for r in repeats}) == 1,
            "all_repeats_match_ordered": all(r["n_missing_vs_ordered"] == 0 for r in repeats),
            "raw_row_count_stable": len({r["n_raw_rows_unordered"] for r in repeats}) == 1,
            "n_repeats_with_drift": sum(1 for r in repeats if r["n_missing_vs_ordered"] > 0),
        },
        "exploratory_degraded_price_run": degraded_run,
        "fetch_all_call_sites": call_sites,
        "all_call_sites_have_order": all(c["has_order"] for c in call_sites),
        "v0_check": {"prior": prior["v0_check"], "new": new["v0_check"]},
        "v3_30d": cmp_block("v3_30d"),
        "v3_90d_report_only": cmp_block("v3_90d_report_only"),
        "yearly": {"prior": prior["yearly"], "new": new["yearly"],
                   "identical": prior["yearly"] == new["yearly"]},
        "judgement": {
            "prior_pass": prior["judgement_pass"],
            "new_pass": new["judgement_pass"],
            "unchanged": prior["judgement_pass"] == new["judgement_pass"],
        },
        "run_config_unchanged": {
            k: new[k] for k in ("n_shuffles", "momentum_days_primary",
                                "momentum_days_secondary", "cost_bps")
        },
    }
    out_path = HERE / "t173_s634_recheck.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[T-173] written: {out_path}")
    print(f"  judgement prior={out['judgement']['prior_pass']} "
          f"new={out['judgement']['new_pass']} "
          f"unchanged={out['judgement']['unchanged']}")
    print(f"  v3_30d identical={out['v3_30d']['identical']} "
          f"changed={out['v3_30d']['changed_fields']}")
    print(f"  unordered missing rows (repeat1): {repeats[0]['n_missing_vs_ordered']} "
          f"({repeats[0]['missing_pct']}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
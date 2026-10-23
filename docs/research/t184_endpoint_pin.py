#!/usr/bin/env python3
"""T-184 — T-179 的 18 家股数缺口名单:端点固定到整周五重跑 + 其余 14 家起点对申报。

卡:tasks/T-184.json(来源 §C-auto-1023-1205 对 T-179 的交叉复核,Seth 10-23 核认)

T-179 用的是「最新一行」当端点,而 world50_mcap_weekly 2026-10-21(周三)多出一行
(124/125 家都有)。周三端点有两处副作用:
  ① 名单随端点漂:周三 T −5.79% 入名单、10-16 周五 −4.17% 出名单(18 ↔ 17 家)。
  ② 台阶表漏掉「基点 → 窗口第一行」这一步:T-179 的 steps() 只在窗口内两两比较,
     TSLA 2025-10-24 +3.11%(基点 2025-10-17 → 下一行)因此消失 —— 而那一步恰好
     与 EDGAR 10-Q 封面逐位相同。

本脚本做四件事(卡 acceptance ①②③④):
  ① 端点固定到最后一个整周五,重出名单与 CSV,写明与旧 18 家的差。
  ② 其余 14 家的 base_date 起点股数逐家对一次申报封面股数,A/B 分类(按 WELL 的做法)。
  ③ 同一判据再跑 13/26/52 周,报每个窗口的家数与 WDC 是否在列。
  ④ 名单内外各自「基点后 35 天内 >1.5% 台阶」的比率,用同一口径复算。

只读 + 研究脚本。不改 v2.py / 不改表(卡 acceptance 末句)。
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 卡上写明「在 T-179 脚本上改(import,不复制)」—— 复用它的取数、universe、steps、ANNOTATION。
import t179_share_change_audit as T179  # noqa: E402

OUT_DIR = "/Volumes/CometCloudAI/cometcloud-local/research/t184"
RPT_DIR = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input"
EDGAR_CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t184/edgar_base_shares.json"

q, dd = T179.q, T179.d
universe, shares_series = T179.universe, T179.shares_series

FLAG_PCT = 0.05         # 进名单:窗口变化 |Δ| > 5%(与 T-179 同)
EARLY_DAYS = 35         # ④ 的「基点后 N 天」
EARLY_STEP_PCT = 0.015  # ④ 的台阶阈值 1.5%
WINDOWS = {"13w": 91, "26w": 182, "52w": 364}

# ② T-179 已经把起点对过申报的 5 家(ANNOTATION 里明确写了 base 的申报号)—— 不重做。
ALREADY_BASE_CHECKED = {"BKNG", "DELL", "VZ", "MO", "T"}


# ---------------------------------------------------------------- 端点固定
def last_full_friday(ser: dict[str, list[dict]]) -> tuple[date, int]:
    """返回 (最后一个整周五, 被丢掉的多余行日期数)。

    shares_x_close_v3 正常一周一行、落在周五。取每家最后一个「周五或更早」的行,
    就把周三那种「半周行」摘掉了 —— 不用在这里判断是不是部分周。
    """
    days = sorted({r["d"] for v in ser.values() for r in v})
    fridays = [x for x in days if x.weekday() == 4] or days
    cutoff = fridays[-1]
    dropped = [x for x in days if x > cutoff]
    return cutoff, len(dropped)


def series_at(ser: dict[str, list[dict]], cutoff: date) -> dict[str, list[dict]]:
    return {k: [r for r in v if r["d"] <= cutoff] for k, v in ser.items()}


# ---------------------------------------------------------------- 台阶(含基点→首行)
def steps_incl_base(seq: list[dict]) -> list[tuple[date, float]]:
    """T-179.steps 漏掉了「基点 → 窗口第一行」这一步。

    T-179 的写法:`win = [r for r in seq if r["d"] > base["d"]]` 然后
    `steps(win, "shares")` —— 基点行不在 win 里,所以基点本身的那一次变化永远不在表里。
    TSLA 2025-10-24 +3.11% 就是这样消失的(它与 EDGAR 10-Q 0001628280-25-045968
    的封面 3,325,819,167 逐位相同)。这里对完整序列(含基点)两两比较,再用日期过滤窗口。
    """
    return T179.steps(seq, "shares")


# ---------------------------------------------------------------- 单窗口计算
def window_rows(ser: dict[str, list[dict]], days: int) -> list[dict]:
    out = []
    for sym, raw in ser.items():
        seq = sorted(raw, key=lambda r: r["d"])
        if len(seq) < 8:
            continue
        last = seq[-1]
        base_day = last["d"] - timedelta(days=days)
        base = [r for r in seq if r["d"] <= base_day]
        if not base:
            continue
        base = base[-1]
        ch = last["shares"] / base["shares"] - 1.0
        st = steps_incl_base(seq)
        win_steps = [(a, b) for a, b in st if a > base["d"] and a <= last["d"]]
        early = [(a, b) for a, b in win_steps if (a - base["d"]).days <= EARLY_DAYS]
        # 备选口径:同一 35 天窗口里**水平**总共动了多少(不是单周台阶)。
        # 卡上写的「基点后 35 天内 >1.5% 台阶」是哪一个,两个都报,差在哪说清楚。
        d35 = [r for r in seq if base["d"] <= r["d"] <= base["d"] + timedelta(days=EARLY_DAYS)]
        cum35 = (d35[-1]["shares"] / base["shares"] - 1.0) if d35 else 0.0
        out.append(
            {
                "key": sym,
                "pct": round(ch * 100, 2),
                "base_shares": round(base["shares"]),
                "last_shares": round(last["shares"]),
                "base_date": base["d"].isoformat(),
                "last_date": last["d"].isoformat(),
                "n_weeks": len(seq),
                "steps": "; ".join(f"{a.isoformat()} {b*100:+.2f}%" for a, b in win_steps),
                "early_steps": "; ".join(f"{a.isoformat()} {b*100:+.2f}%" for a, b in early),
                "n_early": len(early),
                "cum35_pct": round(cum35 * 100, 2),
                "early_all": "; ".join(f"{a.isoformat()} d{(a-base['d']).days} {b*100:+.2f}%"
                                       for a, b in win_steps if (a - base["d"]).days <= 40),
            }
        )
    return out


def flagged(rows: list[dict]) -> list[dict]:
    return [r for r in rows if abs(r["pct"]) / 100 > FLAG_PCT]


# ---------------------------------------------------------------- ② 申报起点核对
def base_vs_filing(base_shares: float, base_day: str, facts: list[dict]) -> dict | None:
    """把库里 base_date 的股数,对着 **base_date 当日已经公开** 的最新一份申报封面股数比。

    WELL(T-179 的 B 类)那一条的判据是:base_date 当天就已经有一份封面写着别的数,
    库里还停在更旧的数 ⇒ 起点陈旧,窗口变化被高估。这里把它变成可复用的分类:
      - avail = filed <= base_date 的事实(filed >= end 恒成立,所以这批 end 也都 <= base_date)
        这是 base_date 当天「市场上能看到的最后一份封面」。
      - future = base_date 之后才 filed 的第一份封面。若它已经改了数,说明基点本身
        落在一个即将变的位置 —— 那是 PIT 取数的性质,不是库的错,单列成 note 不降级。
    """
    bd = dd(base_day)
    avail = [f for f in facts if dd(f["filed"]) <= bd]
    future = sorted([f for f in facts if dd(f["filed"]) > bd], key=lambda f: dd(f["filed"]))
    if not avail:
        return None
    best = max(avail, key=lambda f: (dd(f["end"]), dd(f["filed"])))
    diff = base_shares / float(best["val"]) - 1.0
    pit = ""
    if future and abs(base_shares / float(future[0]["val"]) - 1.0) > 0.001:
        pit = (f"PIT:{future[0]['form']} {future[0]['accn']} (end {future[0]['end']}, "
               f"filed {future[0]['filed']}) = {int(future[0]['val']):,} —— base_date 之后 "
               f"才公开,基点取的是当日能看到的数,不是错")
    if abs(diff) <= 0.001:
        cls, note = "A", "起点 = base_date 当日最新封面股数"
    else:
        cls, note = "B", ("stale:base_date 当日已有更新的封面,库值落后 ⇒ 窗口变化被高估"
                          "(WELL 型)")
    return {
        "filing_end": best["end"],
        "filing_filed": best["filed"],
        "filing_val": int(best["val"]),
        "filing_accn": best["accn"],
        "filing_form": best.get("form", ""),
        "diff_pct": round(diff * 100, 3),
        "category": cls,
        "note": note,
        "pit_note": pit,
    }


def main() -> None:
    syms, asof = universe()
    raw = shares_series(syms)
    cutoff, n_dropped_dates = last_full_friday(raw)
    ser = series_at(raw, cutoff)
    print("CIS v2 equity universe:", len(syms), "| cis_v2_daily as of", asof)
    print("端点固定:", cutoff, "(周五) | 丢掉的多余行日期数:", n_dropped_dates)

    # 端点行的差别:周三行股数 ≠ 周五行股数的家数
    diff_syms = []
    for k, v in ser.items():
        seq = sorted(v, key=lambda r: r["d"])
        later = sorted([r for r in raw.get(k, []) if r["d"] > cutoff], key=lambda r: r["d"])
        if later and abs(later[-1]["shares"] / seq[-1]["shares"] - 1.0) > 1e-9:
            diff_syms.append((k, round((later[-1]["shares"] / seq[-1]["shares"] - 1) * 100, 3)))
    print("周三行股数 ≠ 周五行股数:", len(diff_syms), "/", len(ser), diff_syms)

    # T-179 的周三端点旧值(同一份 shares_series,只把端点换成周三那一行)
    newest = max(r["d"] for v in raw.values() for r in v)
    old = window_rows(series_at(raw, newest), 364)
    new52 = window_rows(ser, 364)
    old_keys = {r["key"] for r in flagged(old)}
    new_keys = {r["key"] for r in flagged(new52)}
    print("周三端点 52w 名单:", len(old_keys), "| 周五端点 52w 名单:", len(new_keys))
    print("  只在周三名单:", sorted(old_keys - new_keys), "| 只在周五名单:", sorted(new_keys - old_keys))

    # ③ 13/26/52 周
    wins = {w: window_rows(ser, n) for w, n in WINDOWS.items()}
    for w in ("13w", "26w", "52w"):
        names = sorted(r["key"] for r in flagged(wins[w]))
        print(f"  {w}: {len(names)} 家 | WDC 在列: {'WDC' in names} | {names}")

    # ④ 基点后 35 天内 >1.5% 台阶:名单内 vs 名单外
    inl = [r for r in wins["52w"] if r["key"] in new_keys]
    outl = [r for r in wins["52w"] if r["key"] not in new_keys]
    a_in = sum(1 for r in inl if r["n_early"] > 0)
    a_out = sum(1 for r in outl if r["n_early"] > 0)
    print(f"④ 基点后 {EARLY_DAYS} 天内 >{EARLY_STEP_PCT*100:.1f}% 台阶: "
          f"名单内 {a_in}/{len(inl)} vs 名单外 {a_out}/{len(outl)}")
    c_in = sum(1 for r in inl if abs(r["cum35_pct"]) / 100 > EARLY_STEP_PCT)
    c_out = sum(1 for r in outl if abs(r["cum35_pct"]) / 100 > EARLY_STEP_PCT)
    print(f"④ 备选口径(同一 35 天窗口内**水平**累计 |Δ| > 1.5%): "
          f"名单内 {c_in}/{len(inl)} vs 名单外 {c_out}/{len(outl)}")
    for tag, grp in (("内", inl), ("外", outl)):
        for r in grp:
            if r["n_early"]:
                print(f"   {tag} {r['key']:6s} {r['early_steps']}")
    print("   近邻核对(名单内 40 天内全部台阶,含 |Δ| <= 1.5% 的):")
    for r in inl:
        if r["early_all"]:
            print(f"   近 {r['key']:6s} {r['early_all']}")

    # ② 14 家起点 vs 申报(T-184 重拉的 EDGAR 封面事实,facts 窗口比 T-179 缓存宽)
    edgar = json.load(open(EDGAR_CACHE)) if os.path.exists(EDGAR_CACHE) else {}
    base52 = {r["key"]: r for r in new52}
    checks = {}
    for sym in sorted(edgar):
        facts = edgar[sym].get("facts") or []
        row = base52.get(sym)
        if row is None:
            continue
        got = base_vs_filing(row["base_shares"], row["base_date"], facts)
        if got:
            got.update({"db_base_shares": row["base_shares"], "base_date": row["base_date"]})
        checks[sym] = got
    print(f"② 起点对申报:{len(checks)} 家 | 类别:",
          dict(Counter(v["category"] for v in checks.values() if v)))
    for sym in sorted(checks):
        v = checks[sym]
        if v is None:
            print(f"   {sym:6s} base_date 当日无任何已 filed 的封面事实")
            continue
        print(f"   {sym:6s} {v['category']} diff={v['diff_pct']:+7.3f}%  库 {v['db_base_shares']:,} "
              f"vs {v['filing_form']} {v['filing_accn']} (end {v['filing_end']}, "
              f"filed {v['filing_filed']}) {v['filing_val']:,} | {v['note']}")
        if v["pit_note"]:
            print(f"          {v['pit_note']}")

    # ---------------- 落盘
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(RPT_DIR, exist_ok=True)

    def dump(fn: str, rows: list[dict], cols: list[str]) -> None:
        with open(os.path.join(OUT_DIR, fn), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})

    cols = ["key", "pct", "base_shares", "last_shares", "base_date", "last_date",
            "n_weeks", "steps", "early_steps", "n_early", "in_52w_list"]
    for r in wins["52w"]:
        r["in_52w_list"] = "Y" if r["key"] in new_keys else "N"
    dump("t184_endpoint_52w.csv", sorted(wins["52w"], key=lambda r: -abs(r["pct"])), cols)
    dump("t184_windows_13w_26w.csv",
         [dict(r, window=w) for w in ("13w", "26w") for r in wins[w]], cols + ["window"])
    dump("t184_base_vs_filing.csv",
         [dict(sym=s, **v) for s, v in sorted(checks.items()) if v],
         ["sym", "base_date", "db_base_shares", "filing_form", "filing_end", "filing_filed",
          "filing_val", "filing_accn", "diff_pct", "category", "note", "pit_note"])

    tsla = next(r for r in wins["52w"] if r["key"] == "TSLA")
    json.dump(
        {
            "asof": asof, "endpoint_weekday": cutoff.isoweekday(), "endpoint": cutoff.isoformat(),
            "dropped_dates": n_dropped_dates, "universe": len(syms),
            "endpoint_row_differs": diff_syms,
            "list_wed": sorted(old_keys), "list_fri": sorted(new_keys),
            "only_wed": sorted(old_keys - new_keys), "only_fri": sorted(new_keys - old_keys),
            "window_counts": {w: len(flagged(r)) for w, r in wins.items()},
            "window_lists": {w: sorted(r["key"] for r in flagged(r)) for w, r in wins.items()},
            "wdc": {w: ("WDC" in {r["key"] for r in flagged(r)}) for w, r in wins.items()},
            "early_ratio": {"in": [a_in, len(inl)], "out": [a_out, len(outl)],
                            "days": EARLY_DAYS, "step_pct": EARLY_STEP_PCT,
                            "alt_cumulative": {"in": [c_in, len(inl)], "out": [c_out, len(outl)]}},
            "base_vs_filing": checks,
            "tsla_steps_52w": tsla["steps"],
        },
        open(os.path.join(OUT_DIR, "t184_results.json"), "w"), indent=1, ensure_ascii=False,
    )
    print("\nTSLA 52w steps(周五端点):", tsla["steps"])
    print("写出:", OUT_DIR, "与", RPT_DIR)


if __name__ == "__main__":
    main()
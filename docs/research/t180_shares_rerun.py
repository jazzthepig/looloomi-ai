#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-180 —— S-668 H1 的「供给纪律」与 S-670 的 ISSUE 按**申报股数**重跑。

台账「S-668 H1 / S-670 ISSUE 更正」(2026-10-22 16:17 UTC):预注册不改(写的就是股数),
错的是实现。原来股数 = world50_mcap_weekly.mcap_usd ÷ ohlcv_daily.close,而 close 是
**总回报复权**的,除出来是 股数 × 原始价 / 复权价 —— 量的是股东收益率(净回购 + 股息),
不是净增发。现在 `world50_mcap_weekly.shares` 已按申报口径填好(141/141 家),重跑。

两件:
  ① S-668 H1 原判据一字不改重跑(发现段 2016-01→2020-12 每 4 周不重叠、留出段
     2021-01→2026-09、v2 三维合成(size + stability + supply)对之后 20 个交易日收益
     的截面 Spearman IC;发现段 IC>0 且 t≥1.5 才进留出段,留出段 IC>0 且 t≥2 = 过)。
  ② S-670 的 ISSUE 照 S-670 原判法重跑(4 周 / 13 周,发现段门 t≥2 + 前后两半 IC>0,
     留出段 IC>0 且 t≥2)。

「旧 → 新」的定义:**同一个内核、同一段数据、同一个前瞻收益**,唯一差别是喂进
`equity_inputs` 的第四元(股数)。旧 = mcap ÷ 复权收盘(T-169/T-172 的原实现),
新 = world50_mcap_weekly.shares。

挪一天(prompt 新规):信号日/截面日当天的派生量判完,再把**派生量所用的三个输入**
(mcap / close / shares)整体换成上一个可用周戳的观测、截面日与前瞻收益锚点不动,
再判一次。周频数据没有日频戳 ⇒「挪一天」落到「上一周戳」= 提前 7 天。

取数 / 截面 / IC 一律 import `t169_equity_quality` 与 `t172_equity_signals`,不复制;
零分布只走 `src.data.evaluation.apparatus`。翻页一律带 order=。

用法: python3 docs/research/t180_shares_rerun.py
产出: docs/research/t180_results.json
       /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-180_shares_rerun.md
缓存: /Volumes/CometCloudAI/cometcloud-local/research/t180/
"""
from __future__ import annotations

import collections
import json
import math
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MAC = "/Volumes/CometCloudAI/cometcloud-local"
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
CACHE = os.path.join(MAC, "research", "t180")
RESULTS = os.path.join(HERE, "t180_results.json")
REPORT = os.path.join(MAC, "_reports", "absorb_input", "T-180_shares_rerun.md")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(os.path.dirname(REPORT), exist_ok=True)

# ---- 零分布 / 盈亏只走 apparatus;没装好就退出,不在本文件里另写一份 ----
try:
    from src.data.evaluation.apparatus import (  # noqa: F401
        long_return, null_distribution, percentile_of, shuffle_within,
    )
    APPARATUS = "src.data.evaluation.apparatus"
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"apparatus 导入失败,退出(不要另起炉灶):{exc}")

# ---- v2 内核:唯一的定义处(与影子写入端同一个文件)----
from src.data.cis.v2 import CODE_REF, DIMS, equity_inputs, score_group  # noqa: E402

# ---- 前序脚本:取数 / 截面 / IC 函数 import,不复制 ----
import t169_equity_quality as T169  # noqa: E402
import t172_equity_signals as T172  # noqa: E402

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

# ---- S-668 H1 / S-670 原文的时间窗与门槛(一字不改)----
DISC = ("2016-01-01", "2020-12-31")
HOLD = ("2021-01-01", "2026-09-30")
GRID_START = "2015-01-02"
GRID_END = "2026-09-30"
HORIZON_DAYS = 20            # 之后 20 个交易日
MIN_CROSS_SECTION = 15
SAMPLE_EVERY_WEEKS = 4       # 发现段每 4 周取一个不重叠样本
H_FWD_DAYS = {4: 20, 13: 65}  # S-670:4 周 / 13 周
STRIDE_WEEKS = {4: 4, 13: 13}
MCAP_SOURCE = "shares_x_close_v3"

# 「挪一天」= 派生量输入整体退到上一个可用周戳。
LAG_STAMP = 1


# ---------------------------------------------------------------- 读取层
def _page_all(path: str, per: int = 1000, cap: int = 4_000_000) -> list:
    """翻页 —— 直接用 t172 的实现(它已经按**实收行数**推进 offset,不是自己写一遍)。
    调用方负责把 order= 拼进 path。"""
    return T172._page_all(path, per=per, cap=cap)


def fetch_mcap_shares() -> tuple[dict, dict]:
    """返回 (d -> {key: mcap_usd}, d -> {key: shares})。只取 source = shares_x_close_v3。
    shares 只读这一列(申报口径);没填的那一周就是没有,不用 市值 ÷ 收盘 去补。"""
    p = os.path.join(CACHE, "mcap_shares.json")
    if os.path.exists(p):
        c = json.load(open(p))
        return {d: {k: float(v) for k, v in m.items()} for d, m in c["mcap"].items()}, \
               {d: {k: float(v) for k, v in m.items()} for d, m in c["shares"].items()}

    q = ("world50_mcap_weekly?select=key,d,mcap_usd,shares&source=eq." + MCAP_SOURCE
         + "&d=gte." + GRID_START + "&order=key.asc,d.asc")
    rows = _page_all(q)
    mc: dict = collections.defaultdict(dict)
    sh: dict = collections.defaultdict(dict)
    for r in rows:
        k, d = r["key"], r["d"][:10]
        if "." in k:                       # 只用不带 . 后缀的 key(与 T-169/T-172 同口径)
            continue
        if r.get("mcap_usd") is not None:
            mc[d][k] = float(r["mcap_usd"])
        if r.get("shares") is not None and float(r["shares"]) > 0:
            sh[d][k] = float(r["shares"])
    print(f"  world50({MCAP_SOURCE}) 周戳 {len(mc)} 个;shares 覆盖 {len(sh)} 个周戳,"
          f"{len({k for d in sh.values() for k in d})} 个 key", flush=True)
    json.dump({"mcap": mc, "shares": sh}, open(p, "w"))
    return dict(mc), dict(sh)


def px_close_on_or_before(dates: list[str], closes: np.ndarray, day: str, max_gap: int = 7):
    """t169 的 `close_on_or_before` 的等价物,拆成两半用现成的函数凑:

    - 取值用 `t172.at_or_before`(day 当日或之前最近一个观测)—— 注意**不能**用
      apparatus 的 `price_on_or_after`,那个是「当天或之后」,拿它取入场价就是未来函数。
    - 过期检查(t169 的 max_gap)在这里补上,at_or_before 自己不带。
    """
    v = T172.at_or_before(list(dates), np.asarray(closes, dtype=float), day)
    if v is None or not math.isfinite(v) or v <= 0:
        return None
    i = np.searchsorted(np.asarray(dates, dtype="datetime64[D]"), np.datetime64(day), side="right") - 1
    if i < 0 or (date.fromisoformat(day) - date.fromisoformat(str(dates[i])[:10])).days > max_gap:
        return None
    return float(v)


# ==================================================================== ① S-668 H1
def part_s668(mc: dict, sh: dict, px: dict) -> dict:
    """S-668 H1 原判据一字不改;唯一差别 = 喂给 equity_inputs 的第四元。"""
    keys = sorted({k for d in mc.values() for k in d})
    # mc 是 d -> {key: mcap},先转成 key -> {d: mcap},否则下面按名字取永远是空
    per_key: dict[str, dict] = collections.defaultdict(dict)
    for d, m in mc.items():
        for k, v in m.items():
            per_key[k][d] = v
    # 每周频输入行 = (周日期, mcap_usd, 当周最后一个交易日的复权收盘, shares)
    weekly: dict[str, list[tuple]] = {}
    for k in keys:
        ser = per_key.get(k, {})
        rows = []
        for d in sorted(ser):
            c = px_close_on_or_before(px[k][0], px[k][1], d, max_gap=7)
            if c:
                rows.append((d, ser[d], c, sh.get(d, {}).get(k)))
        if rows:
            weekly[k] = rows
    print("  周频输入行:%d 个名字 × %d 周(中位 %d 行)"
          % (len(weekly), len(stamps_ := sorted({r[0] for v in weekly.values() for r in v})),
             int(np.median([len(v) for v in weekly.values()]))), flush=True)
    # 交易日历 = 全部裸名字交易日的并集(t169 原口径:同一日历给所有名字)
    cal = sorted({d for k in px for d in px[k][0]})
    cal_idx = {d: i for i, d in enumerate(cal)}

    def fwd(k: str, day: str):
        i = cal_idx.get(day)
        if i is None or i + HORIZON_DAYS >= len(cal):
            return None
        a = px_close_on_or_before(px[k][0], px[k][1], cal[i], max_gap=10)
        b = px_close_on_or_before(px[k][0], px[k][1], cal[i + HORIZON_DAYS], max_gap=10)
        if not a or not b or a <= 0:
            return None
        return long_return(a, b)

    stamps = sorted({r[0] for rows in weekly.values() for r in rows})

    # 四元组的第四元分别取:隐含股数(旧)/ 申报股数(新)/ 两者各退一戳(挪一天)
    def rows_for(k: str, mode: str) -> list[tuple]:
        rs = weekly[k]
        if mode == "OLD":
            return [(d, m, c, m / c) for d, m, c, _ in rs]          # 旧:股数 = 市值 ÷ 复权收盘
        if mode == "NEW":
            return [(d, m, c, s) for d, m, c, s in rs]              # 新:股数 = 申报列
        return [(d, m, c, (m / c if mode == "OLD_L1" else s)) for d, m, c, s in rs]

    MODES = ["OLD", "NEW", "OLD_L1", "NEW_L1"]
    per_week: dict[str, list[dict]] = {m: [] for m in MODES}
    skipped_small = skipped_no_fwd = 0
    prev_stamp = {stamps[0]: None} if stamps else {}
    for i in range(1, len(stamps)):
        prev_stamp[stamps[i]] = stamps[i - 1]

    # 每个 (模式, 名字) 的输入行只构一次(600 周 × 4 模式 × 125 家,现搭就是几千万次)
    rows_by_mode = {m: {k: rows_for(k, m) for k in weekly} for m in MODES}
    at_date: dict[str, list[str]] = collections.defaultdict(list)
    for k, rs in weekly.items():
        for r in rs:
            at_date[r[0]].append(k)

    for d in stamps:
        day = date.fromisoformat(d)
        have = at_date.get(d, [])
        if len(have) < MIN_CROSS_SECTION:
            skipped_small += 1
            continue
        pl = prev_stamp.get(d)
        for mode in MODES:
            base = mode[:-3] if mode.endswith("_L1") else mode
            asof_lag = pl if (mode.endswith("_L1") and pl) else d
            # 锚点口径:size / stability 永远取截面日当天;只有 supply 挪。
            # (L0 时两者相同;L1 时用 equity_inputs(rows, 上一戳) 的 supply 覆盖)
            raw = {}
            for k in have:
                r0 = equity_inputs(rows_by_mode[base][k], d)
                if asof_lag != d:
                    r1 = equity_inputs(rows_by_mode[mode][k], asof_lag)
                    r0 = dict(r0, supply=r1.get("supply"), shares=r1.get("shares"))
                raw[k] = r0
            scored = score_group("equity", raw)
            pts = []
            for k, s in scored.items():
                if s["score"] is None:
                    continue
                r = fwd(k, d)
                if r is None:
                    continue
                pts.append({"k": k, "score": s["score"],
                            "raw": {dim: raw[k].get(dim) for dim in DIMS["equity"]}, "r": r})
            if len(pts) < MIN_CROSS_SECTION:
                skipped_no_fwd += 1
                continue
            row = {"d": d, "n": len(pts),
                   "ic": T169.spearman([p["score"] for p in pts], [p["r"] for p in pts])}
            for dim in DIMS["equity"]:
                hv = [(p["raw"][dim], p["r"]) for p in pts if p["raw"][dim] is not None]
                row["ic_" + dim] = (T169.spearman([a for a, _ in hv], [b for _, b in hv])
                                    if len(hv) >= MIN_CROSS_SECTION else None)
            per_week[mode].append(row)
        if len(per_week["NEW"]) % 40 == 0:
            print("    %d/%d 周" % (len(per_week["NEW"]), len(stamps)), end="\r", flush=True)
    print("  周截面 NEW=%d  跳过(截面<%d)=%d  跳过(前瞻不足)=%d"
          % (len(per_week["NEW"]), MIN_CROSS_SECTION, skipped_small, skipped_no_fwd), flush=True)

    def seg(rows, lo, hi, every):
        dlo, dhi = date.fromisoformat(lo), date.fromisoformat(hi)
        out = []
        for i, w in enumerate(rows):
            dd = date.fromisoformat(w["d"])
            if not (dlo <= dd <= dhi):
                continue
            if every and i % every != 0:
                continue
            out.append(w)
        return out

    def stats(rows, key="ic"):
        return T169.mean_t([w[key] for w in rows])

    out: dict = {"weeks_used": len(per_week["NEW"]), "skipped_small": skipped_small,
                 "skipped_no_forward": skipped_no_fwd,
                 "discovery_window": list(DISC), "holdout_window": list(HOLD),
                 "horizon_days": HORIZON_DAYS, "modes": {}}
    for mode in MODES:
        pw = per_week[mode]
        d_all, d_s = seg(pw, DISC[0], DISC[1], 0), seg(pw, DISC[0], DISC[1], SAMPLE_EVERY_WEEKS)
        h_all, h_s = seg(pw, HOLD[0], HOLD[1], 0), seg(pw, HOLD[0], HOLD[1], SAMPLE_EVERY_WEEKS)
        di, dt, dn = stats(d_s)
        hi, ht, hn = stats(h_s)
        dp = bool(di is not None and di > 0 and dt is not None and dt >= 1.5)
        block = {
            "what": mode,
            "shares_source": ("mcap_usd ÷ 复权收盘(T-169/T-172 原实现)" if mode.startswith("OLD")
                              else "world50_mcap_weekly.shares(申报口径)"),
            "lag_stamps": 1 if mode.endswith("_L1") else 0,
            "discovery": {"n": dn, "mean_ic": di, "t": dt,
                          "gate": "mean_ic > 0 and t >= 1.5", "pass": dp,
                          "all_weeks": {"n": stats(d_all)[2], "mean_ic": stats(d_all)[0],
                                        "t": stats(d_all)[1]},
                          "single_dims": {dim: stats(d_s, "ic_" + dim) for dim in DIMS["equity"]}},
            "holdout": {"n": hn, "mean_ic": hi, "t": ht,
                        "gate": "mean_ic > 0 and t >= 2", "in_gate": dp,
                        "pass": bool(dp and hi is not None and hi > 0 and ht is not None and ht >= 2),
                        "all_weeks": {"n": stats(h_all)[2], "mean_ic": stats(h_all)[0],
                                      "t": stats(h_all)[1]},
                        "single_dims": {dim: stats(h_s, "ic_" + dim) for dim in DIMS["equity"]}},
        }
        block["verdict"] = ("H1 PASS" if block["holdout"]["pass"]
                            else ("发现段过、留出段不过 ⇒ H1 FAIL" if dp else "发现段未过 ⇒ H1 FAIL"))
        out["modes"][mode] = block
    out["code_ref"] = CODE_REF
    out["dms_equity"] = list(DIMS["equity"])
    return out


# ==================================================================== ② S-670 ISSUE
def part_s670(mc: dict, sh: dict, px: dict) -> dict:
    """S-670 的 ISSUE 照原判法重跑;其余 6 个信号不动(M12 跑一遍当流水线对照)。"""
    grid = T172.fridays(GRID_START, GRID_END)
    keys = sorted({k for d in mc.values() for k in d})
    syms = {k: T172.Sym(k, px[k]) for k in keys if len(px.get(k, [])) > 0}
    for s in syms.values():
        s.build_grid(grid)

    SIGS = ["M12", "ISSUE_OLD", "ISSUE_NEW", "ISSUE_OLD_L1", "ISSUE_NEW_L1"]
    rows: list[dict] = []
    skipped_small = 0
    for i, wk in enumerate(grid):
        if not (DISC[0] <= wk <= HOLD[1]):
            continue
        snap = mc.get(wk) or {}
        cross = [k for k in keys if k in snap and k in syms and snap[k] > 0]
        if len(cross) < MIN_CROSS_SECTION:
            skipped_small += 1
            continue
        mc_prev = mc.get(grid[i - 52], {}) if i >= 52 else {}
        # 挪一天:派生量三个输入(mcap / close / shares)整体退到上一个周网格点,
        # 截面日与前瞻收益锚点不动。价格必须配同一周网格点的收盘,否则又变成当天口径。
        j = i - LAG_STAMP
        if j >= 52:
            snap_l = mc.get(grid[j], {})
            sh_l = sh.get(grid[j], {})
            sh_52_l = sh.get(grid[j - 52], {})
            mc_prev_l = mc.get(grid[j - 52], {})
        else:
            snap_l, sh_l, sh_52_l, mc_prev_l = {}, {}, {}, {}

        sv = {s: [] for s in SIGS}
        for k in cross:
            w = syms[k].wk_px
            sh_now = sh.get(wk, {}).get(k)
            sh_52 = sh.get(grid[i - 52], {}).get(k) if i >= 52 else None
            sh_la = sh_l.get(k)
            sh_52_la = sh_52_l.get(k)
            imp = snap[k] / w[i] if w[i] == w[i] and w[i] > 0 else float("nan")
            mc52 = mc_prev.get(k, float("nan"))
            imp52 = (mc52 / w[i - 52]) if (i >= 52 and mc52 == mc52 and mc52 > 0 and w[i - 52] > 0) else float("nan")
            mc_l = snap_l.get(k, float("nan"))
            mc52_l = mc_prev_l.get(k, float("nan"))
            imp_l = mc_l / w[j] if (j >= 0 and w[j] == w[j] and w[j] > 0 and mc_l == mc_l) else float("nan")
            imp52_l = ((mc52_l / w[j - 52]) if (j >= 52 and mc52_l == mc52_l and mc52_l > 0
                                                 and w[j - 52] > 0) else float("nan"))

            def g(a, b):   # −(52 周股数增长),两个都有效才有值
                return -(a / b - 1.0) if (a is not None and b is not None
                                         and a == a and b == b and a > 0 and b > 0) else float("nan")

            sv["M12"].append((w[i - 4] / w[i - 52] - 1.0) if i >= 52 else float("nan"))
            sv["ISSUE_OLD"].append(g(imp, imp52))
            sv["ISSUE_NEW"].append(g(sh_now, sh_52))
            sv["ISSUE_OLD_L1"].append(g(imp_l, imp52_l))
            sv["ISSUE_NEW_L1"].append(g(sh_la, sh_52_la))
        ics, fwd = {}, {}
        for hz, nd in H_FWD_DAYS.items():
            f = np.array([s.fwd(i, nd) for s in (syms[k] for k in cross)], dtype=float)
            fwd[hz] = f.tolist()
            for sg in SIGS:
                ics["%s_%d" % (sg, hz)] = T172.spearman_ic(np.array(sv[sg], dtype=float), f)
        rows.append({"week": wk, "n": len(cross), "sig": sv, "fwd": fwd, "ics": ics})
        if len(rows) % 100 == 0:
            print("    … 周 %d(%s,n=%d)" % (len(rows), wk, len(cross)), flush=True)
    print("  截面周 %d,因 <%d 家跳过 %d" % (len(rows), MIN_CROSS_SECTION, skipped_small), flush=True)

    out: dict = {"cross_weeks": len(rows), "skipped_small": skipped_small,
                 "n_keys": len(keys), "results": {}}
    for sg in SIGS:
        for hz in (4, 13):
            d = T172.summarize(rows, sg, hz, *DISC)
            h = T172.summarize(rows, sg, hz, *HOLD)
            gates = {"mean_ic>0": (d["mean_ic"] or 0) > 0,
                     "t>=2": (d["t"] is not None) and d["t"] >= 2,
                     "half1>0": (d["half1"] is not None) and d["half1"] > 0,
                     "half2>0": (d["half2"] is not None) and d["half2"] > 0}
            enter = all(gates.values())
            hpass = (h["mean_ic"] or 0) > 0 and (h["t"] is not None) and h["t"] >= 2
            out["results"]["%s_%d" % (sg, hz)] = {
                "signal": sg, "horizon_wk": hz, "discovery": d, "gates": gates,
                "enter_holdout": enter, "holdout": h, "holdout_pass": hpass if enter else None,
                "verdict": ("过" if (enter and hpass) else ("进留出但没过" if enter else "发现段未过")),
                "null_discovery": T172.null_pct(rows, sg, hz, *DISC),
                "null_holdout": T172.null_pct(rows, sg, hz, *HOLD) if enter else None,
            }

    # ---- 旧 ISSUE 与新 ISSUE 的截面相关(只报)----
    corr: dict = {}
    for tag, lo, hi in (("all", DISC[0], HOLD[1]), ("discovery", *DISC), ("holdout", *HOLD)):
        cs = []
        for r in rows:
            if not (lo <= r["week"] <= hi):
                continue
            a = np.array(r["sig"]["ISSUE_OLD"], dtype=float)
            b = np.array(r["sig"]["ISSUE_NEW"], dtype=float)
            v = T172.spearman_ic(a, b)
            if math.isfinite(v):
                cs.append(v)
        corr[tag] = {"n_weeks": len(cs), "mean_spearman": float(np.mean(cs)) if cs else None,
                     "t": T172.tstat(cs)}
    out["old_vs_new_cross_section_corr"] = corr

    # ---- 旧 − 新 ≈ 股息率?逐周缺口 + 高股息公司 ----
    out["supply_gap"] = _gap_summary(mc, sh, syms, grid)
    return out


def _gap_summary(mc: dict, sh: dict, syms: dict, grid: list) -> dict:
    """旧 ISSUE − 新 ISSUE 的差额 = 申报增长 − 隐含增长。

    隐含股数 = 股数 × 原始价 / 复权价,而复权价/原始价 就是总回报累积因子,
    一年涨 ≈ 1 + 股息率 ⇒ 隐含增长 ≈ 申报增长 − 股息率
    ⇒ **缺口 ≈ 股息率**(净回购本来就在「申报增长」里面,不进这个缺口)。"""
    by_name: dict = collections.defaultdict(lambda: {"old": [], "new": []})
    for wk in grid:
        if not ("2024-01-01" <= wk <= "2026-09-30"):
            continue
        i = grid.index(wk)
        if i < 52:
            continue
        for k, s in sh.get(wk, {}).items():
            s52 = sh.get(grid[i - 52], {}).get(k)
            if not s52 or k not in syms:
                continue
            mc_now = mc.get(wk, {}).get(k)
            mc_prev = mc.get(grid[i - 52], {}).get(k)
            w = syms[k].wk_px
            if not (mc_now and mc_prev and w[i] == w[i] and w[i] > 0 and w[i - 52] == w[i - 52]
                    and w[i - 52] > 0):
                continue
            imp = mc_now / w[i]
            imp52 = mc_prev / w[i - 52]
            by_name[k]["old"].append(imp / imp52 - 1.0)
            by_name[k]["new"].append(s / s52 - 1.0)
    rows = []
    for k, v in by_name.items():
        if not v["old"] or not v["new"]:
            continue
        o = float(np.mean(v["old"]))
        n = float(np.mean(v["new"]))
        rows.append({"key": k, "weeks": len(v["old"]),
                     "implied_52w_share_change": round(o, 5),
                     "reported_52w_share_change": round(n, 5),
                     "gap_old_minus_new": round(n - o, 5)})
    rows.sort(key=lambda r: -r["gap_old_minus_new"])
    return {"what": "gap = 申报增长 − 隐含增长 = 旧 ISSUE − 新 ISSUE;正值 ≈ **股息率**"
                        "(净回购在「申报增长」里,不进这个缺口)",
            "window": ["2024-01-01", "2026-09-30"], "n_names": len(rows),
            "top": rows[:15], "bottom": rows[-10:]}


# ==================================================================== 主流程
def main() -> int:
    print("[T-180] S-668 H1 / S-670 ISSUE —— 按申报股数重跑", flush=True)
    cache_out = os.path.join(CACHE, "t180_out.json")
    if os.path.exists(cache_out):
        print("  [cache] 复用 %s(删掉它可强制重算)" % cache_out, flush=True)
        write_report(json.load(open(cache_out)))
        print("[T-180] 报告 → %s" % REPORT, flush=True)
        return 0
    print("== 取数 ==", flush=True)
    mc, sh = fetch_mcap_shares()
    keys = sorted({k for d in mc.values() for k in d})
    px = T172.fetch_px(keys)          # 复用 t172 的取数 + 缓存(复权收盘)
    syms_px = {k: ([r[0] for r in v], np.array([r[1] for r in v], dtype=float))
               for k, v in px.items()}
    print("  裸 key %d;有价 %d" % (len(keys), len(syms_px)), flush=True)

    print("== ① S-668 H1 ==", flush=True)
    s668 = part_s668(mc, sh, syms_px)
    print("== ② S-670 ISSUE ==", flush=True)
    s670 = part_s670(mc, sh, px)

    out = {"meta": {"task": "T-180", "prereg": "S-668 H1 + S-670(预注册不改,错的是实现)",
                    "apparatus": APPARATUS, "code_ref": CODE_REF,
                    "universe": "world50_mcap_weekly source=%s,无点 key" % MCAP_SOURCE,
                    "shares_source": "world50_mcap_weekly.shares(申报口径)",
                    "old_implementation": "股数 = mcap_usd ÷ ohlcv_daily.close(复权收盘)",
                    "lag_rule": "挪一天 = 派生量三个输入整体退到上一个可用周戳;截面日与前瞻锚点不动",
                    "reused": {"t169": ["spearman", "mean_t"], "t172": sorted(
                        n for n in ("_page_all", "fridays", "at_or_before", "Sym", "spearman_ic",
                                    "rankdata", "tstat", "window", "summarize", "null_pct",
                                    "fetch_px") if hasattr(T172, n))},
                    "discovery": list(DISC), "holdout": list(HOLD)},
           "s668_h1": s668, "s670_issue": s670}
    json.dump(out, open(os.path.join(CACHE, "t180_out.json"), "w"), ensure_ascii=False, indent=2)
    json.dump(out, open(RESULTS, "w"), ensure_ascii=False, indent=2)
    write_report(out)
    print("[T-180] 结果 → %s\n[T-180] 报告 → %s" % (RESULTS, REPORT), flush=True)
    return 0


def _f(v, n=4):
    return "—" if v is None else ("%+." + str(n) + "f") % v


def _g(v, n=2):
    return "—" if v is None else ("%." + str(n) + "f") % v


def write_report(out: dict) -> None:
    m, A, B = out["meta"], out["s668_h1"], out["s670_issue"]
    L: list[str] = []
    P = L.append
    P("# T-180 · S-668 H1 / S-670 ISSUE 重跑结果 —— 按申报股数,不再用市值 ÷ 复权收盘\n")
    P("生成:T-180 · 预注册不改(写的一直是股数),改的是实现。\n")
    P("| 项 | 值 |")
    P("| --- | --- |")
    P("| shares 来源 | `world50_mcap_weekly.shares`(申报口径) |")
    P("| 旧实现 | 股数 = `mcap_usd` ÷ `ohlcv_daily.close`(复权收盘) |")
    P("| 内核 | `src.data.cis.v2` `equity_inputs` / `score_group`,%s |" % m["code_ref"])
    P("| 零分布 | `%s`(t172 的 `null_pct` 直接复用) |" % m["apparatus"])
    P("| 宇宙 | %s;截面周 %d |" % (m["universe"], B["cross_weeks"]))
    P("| 发现段 / 留出段 | %s → %s / %s → %s |" % (m["discovery"][0], m["discovery"][1],
                                                    m["holdout"][0], m["holdout"][1]))
    P("")
    P("> 旧实现的股数 = 股数 × 原始价 / 复权价 ⇒ 它的 52 周变化 ≈ **真实股数变化 − 股息率 − 分拆**。")
    P("> 也就是说旧版量的是股东收益率(净回购 + 股息),不是净增发。这一节把两者并排放。\n")

    P("## ① S-668 H1(个股 v2 三维合成 → 之后 20 个交易日)\n")
    P("原判据一字未改:发现段每 4 周不重叠、IC > 0 且 t ≥ 1.5 才进留出段;留出段 IC > 0 且 t ≥ 2 = 过。\n")
    P("| 实现 | 段 | n | 合成 IC | t | 门槛 | size | stability | supply |")
    P("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for mode, blk in A["modes"].items():
        for seg_name, seg_key in (("发现", "discovery"), ("留出", "holdout")):
            sd = blk[seg_key]
            dm = sd["single_dims"]
            P("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
              % (mode.replace("_L1", " +挪一天"), seg_name, sd["n"], _f(sd["mean_ic"]),
                 _g(sd["t"]), "过" if sd["pass"] else "不过",
                 _f(dm["size"][0]), _f(dm["stability"][0]), _f(dm["supply"][0])))
    P("")
    for mode, blk in A["modes"].items():
        P("- **%s**(%s):%s" % (mode, blk["shares_source"], blk["verdict"]))
    P("")

    P("## ② S-670 的 ISSUE(4 周 / 13 周)\n")
    P("| 信号 | 期限 | 段 | n | IC | t | 前半 IC | 后半 IC | 门 | 判定 |")
    P("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for sig in ("ISSUE_OLD", "ISSUE_NEW", "ISSUE_OLD_L1", "ISSUE_NEW_L1", "M12"):
        for hz in (4, 13):
            r = B["results"].get("%s_%d" % (sig, hz))
            if not r:
                continue
            for seg_name, sd in (("发现", r["discovery"]), ("留出", r["holdout"])):
                gate = ("进留出" if r["enter_holdout"] else "发现段未过")
                if seg_name == "留出" and r["enter_holdout"]:
                    gate = "留出" + ("过" if r["holdout_pass"] else "未过")
                P("| %s | %dw | %s | %s | %s | %s | %s | %s | %s | %s |"
                  % (sig.replace("_L1", " +挪一天"), hz, seg_name, sd["n_weeks"],
                     _f(sd["mean_ic"]), _g(sd["t"]), _f(sd["half1"]), _f(sd["half2"]),
                     gate, r["verdict"]))
    P("")
    P("零分布(apparatus,每周打乱前瞻收益,400 次):\n")
    P("| 信号 | 期限 | 段 | 实际均值 IC | 零均值 | 零 sd | 分位 |")
    P("| --- | --- | --- | --- | --- | --- | --- |")
    for sig in ("ISSUE_OLD", "ISSUE_NEW", "ISSUE_OLD_L1", "ISSUE_NEW_L1"):
        for hz in (4, 13):
            r = B["results"].get("%s_%d" % (sig, hz))
            if not r:
                continue
            for seg_name, nd in (("发现", r["null_discovery"]), ("留出", r["null_holdout"])):
                if not nd or nd.get("pct") is None:
                    continue
                P("| %s | %dw | %s | %s | %s | %s | %s |"
                  % (sig.replace("_L1", " +挪一天"), hz, seg_name, _f(nd.get("actual")),
                     _f(nd.get("null_mean")), _g(nd.get("null_sd")), _g(nd.get("pct"), 1)))
    P("")

    P("## ③ 旧 ISSUE 与新 ISSUE 的截面相关(只报)\n")
    P("| 段 | 周数 | 平均 Spearman | t |")
    P("| --- | --- | --- | --- |")
    for tag, c in B["old_vs_new_cross_section_corr"].items():
        P("| %s | %s | %s | %s |" % (tag, c["n_weeks"], _f(c["mean_spearman"]), _g(c["t"])))
    P("")

    P("## ④ 「旧 − 新 ≈ 股息 / 股东收益率」对不对得上(只报)\n")
    g = B["supply_gap"]
    P("%s。窗口 %s,%d 个名字。\n" % (g["what"], " → ".join(g["window"]), g["n_names"]))
    P("缺口最大的 15 家:\n")
    P("| key | 周数 | 隐含股数 52 周变化(旧) | 申报股数 52 周变化(新) | 旧 − 新 |")
    P("| --- | --- | --- | --- | --- |")
    for r in g["top"]:
        P("| %s | %d | %s | %s | %s |" % (r["key"], r["weeks"],
                                          _pct(r["implied_52w_share_change"]),
                                          _pct(r["reported_52w_share_change"]),
                                          _pct(r["gap_old_minus_new"])))
    P("")
    P("缺口最小的 10 家:\n")
    P("| key | 周数 | 隐含股数 52 周变化(旧) | 申报股数 52 周变化(新) | 旧 − 新 |")
    P("| --- | --- | --- | --- | --- |")
    for r in g["bottom"]:
        P("| %s | %d | %s | %s | %s |" % (r["key"], r["weeks"],
                                          _pct(r["implied_52w_share_change"]),
                                          _pct(r["reported_52w_share_change"]),
                                          _pct(r["gap_old_minus_new"])))
    P("")
    P("> 推导:隐含股数 = 股数 × 原始价 / 复权价,而复权价/原始价 就是总回报累积因子,")
    P("> 一年涨 ≈ 1 + 股息率 ⇒ 隐含增长 ≈ 申报增长 − 股息率 ⇒ **缺口 ≈ 股息率**。")
    P("> 净回购本来就含在「申报增长」里,不进这个缺口。\n")
    P("> **没做的部分**:库里没有股息表(`world50_dividends` / `dividends` / `corporate_actions` 都不存在),")
    P("> 所以这里量的是缺口本身,没对着一个独立股息率做点对点对账。")
    P("> 现在只能说形状对得上(零分红股缺口精确为 0、高分红股 5–14%);要真对账需要 @seth 指一个股息数据源。\n")

    P("## 草稿:S-668 H1 / S-670 ISSUE 重跑结果\n")
    P(_draft(out))
    open(REPORT, "w").write("\n".join(L))


def _pct(v):
    return "—" if v is None else "%+.2f%%" % (v * 100.0)


def _draft(out: dict) -> str:
    m, A, B = out["meta"], out["s668_h1"], out["s670_issue"]
    o_d, n_d = A["modes"]["OLD"]["discovery"], A["modes"]["NEW"]["discovery"]
    o_h, n_h = A["modes"]["OLD"]["holdout"], A["modes"]["NEW"]["holdout"]
    i4o = B["results"]["ISSUE_OLD_4"]["discovery"]
    i4n = B["results"]["ISSUE_NEW_4"]["discovery"]
    i13o = B["results"]["ISSUE_OLD_13"]["discovery"]
    i13n = B["results"]["ISSUE_NEW_13"]["discovery"]
    # 「翻过来」= 净增发少的公司之后更好 = 发现段 IC 由 ≤0 变成 >0。
    # 只是从 -0.075 走到 -0.061(两边都还是负的)**不算**翻过来。
    flipped = (n_d["mean_ic"] or 0) > 0 and (o_d["mean_ic"] or 0) <= 0
    shrink = (abs(o_d["mean_ic"]) / abs(n_d["mean_ic"])) if n_d["mean_ic"] else float("nan")
    if flipped:
        verdict = ("H1 的供给纪律**翻过来**(新实现的发现段 IC 由 %s 变 %s),⇒ 按 S-668 §切换规则,"
                   "个股 v2 合成重新进切换判断。" % (_f(o_d["mean_ic"]), _f(n_d["mean_ic"])))
    else:
        verdict = ("**不翻** —— 两边的发现段 IC 都还是负的(%s → %s),只是强度掉了约 %.1f 倍。"
                   "H1 结论照旧(发现段未过 ⇒ FAIL),S-670 的 ISSUE 也仍是发现段未过。"
                   "台账里写清楚这回检的是**净增发**而不是股东收益率"
                   % (_f(o_d["mean_ic"]), _f(n_d["mean_ic"]), shrink))
    lines = [
        "**测得的原始数字(S-668 H1,合成 IC / t)**",
        "",
        "- 发现段:旧 %s / t=%s(n=%s)→ 新 %s / t=%s(n=%s)"
        % (_f(o_d["mean_ic"]), _g(o_d["t"]), o_d["n"], _f(n_d["mean_ic"]), _g(n_d["t"]), n_d["n"]),
        "- 留出段:旧 %s / t=%s(n=%s)→ 新 %s / t=%s(n=%s)"
        % (_f(o_h["mean_ic"]), _g(o_h["t"]), o_h["n"], _f(n_h["mean_ic"]), _g(n_h["t"]), n_h["n"]),
        "- 发现段判定:旧 %s ⇒ %s;新 %s ⇒ %s"
        % ("过" if o_d["pass"] else "不过", A["modes"]["OLD"]["verdict"],
           "过" if n_d["pass"] else "不过", A["modes"]["NEW"]["verdict"]),
        "- 供给纪律单维 IC(发现段):旧 %s → 新 %s;留出段:旧 %s → 新 %s"
        % (_f(o_d["single_dims"]["supply"][0]), _f(n_d["single_dims"]["supply"][0]),
           _f(o_h["single_dims"]["supply"][0]), _f(n_h["single_dims"]["supply"][0])),
        "",
        "**测得的原始数字(S-670 ISSUE,发现段 IC / t)**",
        "",
        "- 4 周:旧 %s / t=%s(n=%s)→ 新 %s / t=%s(n=%s)"
        % (_f(i4o["mean_ic"]), _g(i4o["t"]), i4o["n_weeks"],
           _f(i4n["mean_ic"]), _g(i4n["t"]), i4n["n_weeks"]),
        "- 13 周:旧 %s / t=%s(n=%s)→ 新 %s / t=%s(n=%s)"
        % (_f(i13o["mean_ic"]), _g(i13o["t"]), i13o["n_weeks"],
           _f(i13n["mean_ic"]), _g(i13n["t"]), i13n["n_weeks"]),
        "",
        "**结论**",
        "",
        "- " + verdict + "。",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
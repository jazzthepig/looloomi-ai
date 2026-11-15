#!/usr/bin/env python3
"""T-393 —— S-869 面板补全(C 道):把 C 道这几条策略「自己原来那份回测 / 账本」的逐日净值,
导成 docs/research/s869_extra_panel_c.csv(格式 family,d,nav,funded)。

规矩(照卡):
  · 不改任何原脚本一行、不重新调参;只 import 它们的函数、用它们自己的数据,原样导出;
  · funded = 1 = 净值占用本金(持有资产类);0 = 票 / 保证金的盈亏曲线;
  · 某条拿不到逐日净值就写明原因、跳过,不拿别的东西顶;
  · 每一段净值都在 meta 里写出处(脚本、参数、首末日、台账号)+ 自检。

用法:python3 docs/research/t393_export_panel_c.py [family ...](默认全部)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

R = "/Volumes/CometCloudAI/cometcloud-local/research/"
OUT_CSV = os.path.join(HERE, "s869_extra_panel_c.csv")
OUT_META = os.path.join(HERE, "s869_extra_panel_c.meta.json")
OUT_PART = os.path.join(HERE, "_t393_panel_parts.json")     # 中途落盘,防止长跑丢进度

PANEL: dict[str, dict[str, float]] = {}      # family → {d: nav}
META: dict[str, dict] = {}


def _put(family: str, days: list[str], nav: list[float], funded: int) -> None:
    d = {a: float(b) for a, b in zip(days, nav)}
    bad = [k for k, v in d.items() if not np.isfinite(v)]
    if bad:
        raise ValueError(f"{family}: 净值有非有限值 {bad[:3]}")
    PANEL[family] = d
    META.setdefault(family, {})["funded"] = funded
    META[family]["n_days"] = len(d)
    META[family]["first_d"] = min(d)
    META[family]["last_d"] = max(d)


def _trim_to_active(days: list[str], nav: list[float], active_idx: int) -> tuple[list[str], list[float]]:
    """从第一个真正有仓位的日子起(前面空仓的平段不稀释状态统计)。"""
    return days[active_idx:], nav[active_idx:]


# ── ① World50 EW / EW×Mom(t361 面板 + t099 回放)────────────────────────────
def fam_world50() -> None:
    import t361_world50_panel as T361
    import t099_world50_replay as T099

    pj = os.path.join(R, "w50_daily", "panel_t361.json")
    panel = json.load(open(pj)) if os.path.exists(pj) else T361.build()
    months, ret, mcap, cls = panel["months"], panel["ret"], panel["mcap"], panel["cls"]
    snap = {m: {k: float(v) for k, v in s.items() if v} for m, s in mcap.items()}
    closes = {k: T099.closes_from_returns(v) for k, v in ret.items()}

    # 月末日期:当月最后一个「基准股」有价日(ACWI/AGG/QQQ/SPY),没有就退到全宇宙最晚
    cj = json.load(open(os.path.join(R, "w50_daily", "close.json")))
    cdates, cclose = cj["dates"], cj["close"]
    bench_last, all_last = {}, {}
    for sym, vals in cclose.items():
        for d, v in zip(cdates, vals):
            if v is None:
                continue
            m = d[:7]
            if all_last.get(m, "") < d:
                all_last[m] = d
            if cls.get(sym) == "benchmark" and bench_last.get(m, "") < d:
                bench_last[m] = d
    mark = {m: bench_last.get(m) or all_last.get(m) for m in months}

    for arm in ("EW", "EWxMom"):
        a = T099.run_arm(arm, months, ret, snap, cls, closes)
        am, ar = a["months"], a["ret"]
        # 自检:EW×Mom 的月度序列必须与脚本落盘的那份一致(t361 自己存过)
        if arm == "EWxMom":
            rp = os.path.join(R, "w50_daily", "world50_replay_t361.json")
            if os.path.exists(rp):
                old = json.load(open(rp))["arms"]["EWxMom"]
                ok = (old.get("months") == am and len(old.get("ret") or []) == len(ar)
                      and max(abs(float(x) - float(y)) for x, y in zip(old["ret"], ar)) < 1e-12)
                META.setdefault("_selfcheck", {})["world50_EWxMom_matches_saved_replay"] = bool(ok)
                if not ok:
                    raise RuntimeError("EWxMom 月度序列与 world50_replay_t361.json 对不上")
        days, nav, prev = [], [], 1.0
        for m, r in zip(am, ar):
            if r is None or not np.isfinite(r):
                continue
            d = mark.get(m)
            if d is None:
                continue
            prev *= (1.0 + float(r))
            days.append(d)
            nav.append(prev)
        _put(f"World50_{arm}", days, nav, 1)
        META[f"World50_{arm}"].update({
            "source": "docs/research/t361_world50_panel.py(面板)+ docs/research/t099_world50_replay.py(run_arm)",
            "ledger": "w50_daily/world50_replay_t361.json(T-361 自己的回放产物;EW 的月度序列由同一 run_arm 重算)",
            "params": f"arm={arm};成分 12 月选、季末重设权重、季内漂移;窗口 {am[0]}→{am[-1]}({len(am)} 个月)",
            "daily_rule": "月度回放:当月收益记在当月最后一个基准股有价日(ACWI/AGG/QQQ/SPY 中最晚的一个),"
                          "两个月末之间净值不变(面板按净值不变补齐 ⇒ 那些天收益 0)",
            "note": "funded=1(满仓持有资产);面板会按 funded 口径扣现金利率",
        })


# ── ② 跨资产趋势袖套(t364 / S-841 写死的规则)──────────────────────────────
def fam_t364() -> None:
    import t364_cross_asset_trend as T364

    df = T364.fetch_ohlcv()                    # 用它自己的缓存 CSV(不改数据)
    syms = {s: T364.Sym(s, df) for s in T364.SYMS}
    sl = T364.build_sleeve(syms)
    nav = sl["nav"]
    cal = list(nav.index)
    vals = [float(x) for x in nav.values]
    # 第一个真正有仓位的日子:第一个非零毛敞口的月末之后的第一个交易日
    pos = sl["pos"]
    me = [d for d in pos.index if float(pos.loc[d].abs().sum()) > 0]
    if not me:
        raise RuntimeError("袖套没有任何持仓")
    first_me = me[0]
    ai = next(i for i, d in enumerate(cal) if d > first_me)
    days, vals = _trim_to_active([str(d.date()) for d in cal], vals, ai)
    _put("T364_cross_asset_trend", days, vals, 1)
    META["T364_cross_asset_trend"].update({
        "source": "docs/research/t364_cross_asset_trend.py(函数 build_sleeve,一字未改)",
        "ledger": "T-364 / S-841(S-835 候选三);产物 docs/research/t364_results.json",
        "params": f"SYMS={T364.SYMS};月末调仓;信号 = 过去 252 日收益的符号;仓位 = 符号×(10%÷60 日年化波动)÷5;"
                  f"毛敞口上限 {T364.GROSS_CAP};每单位换手 5 bp;日历 {str(cal[0].date())}→{str(cal[-1].date())}"
                  f"({len(cal)} 个交易日)",
        "daily_rule": "袖套本身就是逐交易日净值(cal = 五个 ETF 的共同交易日),直接原样导出;"
                      "起点取第一个非零毛敞口月末之后的第一个交易日(前面空仓的平段不留)",
        "note": "funded=1(持有资产类)。袖套自己的净值里闲置仓位(毛敞口中位 0.62)不计现金利息,"
                "而面板按 funded 口径会扣满额现金利率 ⇒ 这一条的「超额」略偏保守",
    })


# ── ③ 新上市做空 S681 H1(发现段 + 留出段两本账)────────────────────────────
def fam_s681_h1() -> None:
    import short_lab_common as sl
    import s681_h1_new_listing as H1
    import t159_bear_short as t159

    um = sl.load_um()
    fund = sl.daily_funding(sl.load_funding())
    allt = H1.tickets_for(um, fund)
    nb = sl.nav_bars(um)
    last = max(a["d"][-1] for a in um.values())
    disc = sl.in_window(allt, *sl.DISCOVERY)
    hold = [t for t in allt if t["signal_d"] >= sl.HOLDOUT_FROM]

    def curve(tickets, d_to):
        tk = [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
               "exit_d": None if t["still"] else t["exit_d"], "entry_px": t["entry_px"],
               "stop_px": t["stop_px"], "exit_px": None if t["still"] else t["exit_px"]} for t in tickets]
        return list(t159.nav(tk, nb, 0.005, cap=10, d_to=d_to))

    for name, tickets, d_to in (("S681_H1_disc", disc, "2024-03-31"), ("S681_H1_holdout", hold, last)):
        cv = curve(tickets, d_to)
        if not cv:
            raise RuntimeError(f"{name}: 资金曲线为空")
        st = t159.stats(cv)
        # 自检:我自己的曲线统计必须与原脚本 sl.money() 给的完全一致
        ref = sl.money(tickets, nb, d_to)
        for k in ("days", "end", "annualised", "mdd", "taken", "skipped", "closed", "peak_gross"):
            if ref.get(k) is None or st.get(k) is None:
                continue
            if abs(float(ref[k]) - float(st.get(k))) > 1e-12:
                raise RuntimeError(f"{name}: 自检失败 {k}: 我的 {st.get(k)} ≠ sl.money 的 {ref.get(k)}")
        for k in ("d0", "d1"):
            if ref.get(k) != st.get(k):
                raise RuntimeError(f"{name}: 自检失败 {k}: {st.get(k)} ≠ {ref.get(k)}")
        days = [r["d"] for r in cv]
        nav = [float(r["equity"]) for r in cv]
        _put(name, days, nav, 0)
        META[name].update({
            "source": "docs/research/s681_h1_new_listing.py(函数 tickets_for)+ docs/research/t159_bear_short.py(nav / stats)",
            "ledger": "S-681 H1(台账 2026-10-25 13:21 UTC)",
            "params": f"S={H1.S}(+50% 硬止损),N={H1.N}(持有 60 天),进场 = 上市第 {H1.ENTRY_AFTER} 天开盘;"
                      f"每票风险 0.5%、最多同时 10 张;d_to={d_to};票数 {len(tickets)}",
            "daily_rule": "t159.nav 的逐日盯市权益曲线(每天按收盘价盯市);首日净值 1.0",
            "selfcheck": f"与原脚本 sl.money() 的统计逐项一致(end={ref['end']:.6f} mdd={ref['mdd']:.6f} "
                         f"annualised={ref['annualised']:.4f} taken={ref['taken']} skipped={ref['skipped']} "
                         f"closed={ref['closed']})",
            "note": "funded=0(票 / 保证金的盈亏曲线,面板不扣现金利率)",
        })


# ── ④ 反转规则 A 30 天版(S-840 自己重写的那份:U 本位永续日线)────────────────
def fam_s840_h30() -> None:
    # s840 原来按命令行取两个参数(sys.argv[1]=t342_daily.csv, sys.argv[2]=研究目录);
    # 这里照它原来的写法喂进去,不改它一行。
    argv0 = list(sys.argv)
    sys.argv = ["s840_rule_a_rewrite.py", os.path.join(REPO, "docs/research/t342_daily.csv"),
                "/Volumes/CometCloudAI/cometcloud-local/research/"]
    try:
        import s840_rule_a_rewrite as S840
    finally:
        sys.argv = argv0

    for name, funding in (("S840_ruleA_H30", False), ("S840_ruleA_H30_funding", True)):
        S, tk = S840.sleeve(30, funding=funding)
        days = [str(d) for d in S840.DAYS]
        vals = [float(x) for x in S]
        # 起点:第一张票进场的前一天(= 净值开始不等于 1 的那一天)
        first = next((i for i, v in enumerate(vals) if v != 1.0), None)
        if first is None:
            raise RuntimeError("规则 A 没有任何成交")
        days, vals = _trim_to_active(days, vals, first)
        _put(name, days, vals, 0)
        META[name].update({
            "source": "docs/research/s840_rule_a_rewrite.py(函数 sleeve(30))",
            "ledger": "S-840(台账 2026-11-13 05:58 UTC;第二台引擎 + 第二份数据:U 本位永续日线)",
            "params": f"H=30(持有 30 天),funding={funding};固定 10 个仓位、两腿等额、同币不重复;"
                      f"单边成本 10 bp;事件数 {len(S840.EVENTS)}",
            "daily_rule": "袖子自己的逐日历日净值(S 从第一张票进场前一天起为 1)",
            "note": "funded=0(票 / 保证金的盈亏曲线,面板不扣现金利率)。"
                    + ("这一版计资金费(与 S-840 的 funding_rows 同口径)。" if funding else "这一版不计资金费(与 S-840 的 rows 同口径)。"),
        })


# ── ⑤ 山寨空篮 S-847(T-372 主口径:状态成立的周才开仓)──────────────────────
def fam_t372() -> None:
    # 先把在册的那份回测结果读在手里(import 会把它重写一遍)
    ref_path = os.path.join(HERE, "t372_results.json")
    ref = json.load(open(ref_path)) if os.path.exists(ref_path) else {}

    import t372_s847_basket as T372

    P, F, IB, COST = T372.P, T372.F, T372.IB, T372.COST
    DAYS, PIDX = T372.DAYS, T372.PIDX
    rows = [r for r in T372.WK if r["on"]]          # 主口径:状态成立的周才开仓
    if not rows:
        raise RuntimeError("没有状态成立的周")
    days, nav = [], []
    eq, maxdiff = 1.0, 0.0
    for r in rows:
        if not r["n"]:
            # 篮子为空的那一周:原脚本整周记 0(连 BTC 腿也不开),照做
            continue
        d = r["d"]
        a, b = d + 1, d + 7                        # 周一收盘建仓、周日收盘平仓
        sel = np.array([PIDX[p] for p in r["pairs"]], dtype=int)
        w = np.array(r["w"], dtype=float)
        cum = 0.0
        for t in range(a, b + 1):
            add = 0.0
            if t > a:                              # 价格腿:按进场价分摊到每天
                if sel.size:
                    add += float((-w * (P[sel, t] - P[sel, t - 1]) / P[sel, a]).sum())
                add += float((P[IB, t] - P[IB, t - 1]) / P[IB, a])
            if sel.size:                           # 资金费:空头收正费率
                add += float((w * F[sel, t]).sum())
            add += -float(F[IB, t])
            if t == a:
                add += -COST * (r["notional"] + 1.0)     # 开仓成本(一半)
            if t == b:
                add += -COST * (r["notional"] + 1.0)     # 平仓成本(另一半)
            cum += add
            days.append(str(DAYS[t]))
            nav.append(eq * (1.0 + cum))           # 本周内:固定名义 ⇒ 净值线性随累计盈亏
        maxdiff = max(maxdiff, abs(cum - r["ret"]))
        eq = eq * (1.0 + cum)
    if maxdiff > 1e-9:
        raise RuntimeError(f"逐日加总与脚本的周收益对不上:max diff {maxdiff:.3e}")

    # 自检:与在册的那份回测(T-372 自己写的 t372_results.json)对齐
    ref_stats = ref.get("stats", {})
    mine = {"n_on": len(rows), "mean_on": float(np.mean([r["ret"] for r in rows])),
            "sum_on": float(np.sum([r["ret"] for r in rows]))}
    for k, v in mine.items():
        if k in ref_stats and abs(float(ref_stats[k]) - float(v)) > 1e-9:
            raise RuntimeError(f"与在册回测对不上 {k}:我的 {v} ≠ {ref_stats[k]}")

    _put("T372_alt_short_basket", days, nav, 0)
    META["T372_alt_short_basket"].update({
        "source": "docs/research/t372_s847_basket.py(周仓 build_weeks 的主口径 WK + 它自己的 P / F 矩阵)",
        "ledger": "S-847(台账 2026-11-13 09:44 UTC);产物 docs/research/t372_results.json",
        "params": f"状态 = state_daily(entity=panel, feature=stable_supply_30d) < 0,用该周日的读数;"
                  f"篮子 = U 本位永续非 BTC 非稳定币,过去 30 天成交额前 {T372.TOPN},"
                  f"剔除过去 7 天资金费合计 < {T372.CROWDSUM} 的,等权且单币 ≤ {T372.CAP};"
                  f"仓位:空篮子名义 1、多 BTC 名义 1;每腿每边 {T372.COST};"
                  f"周数 {len(T372.WK)}、其中状态成立 {len(rows)} 周;窗口 {T372.WK[0]['date']}→{T372.WK[-1]['date']}",
        "daily_rule": "周一收盘建仓、周日收盘平仓;逐日盯市(价格腿按进场价分摊到每天,资金费按日累计,"
                      "成本开仓 / 平仓各半);状态不成立的周不开仓、净值不变",
        "selfcheck": f"逐日加总与脚本的周收益逐周一致(max diff {maxdiff:.2e});"
                     f"与在册 t372_results.json 的 stats 对齐(n_on={mine['n_on']} mean_on={mine['mean_on']:.6f})",
        "note": "funded=0(票 / 保证金的盈亏曲线,面板不扣现金利率)。"
                "注意:这一族自己的闸门就是「稳定币在抽」,所以它的盈亏只会落在面板的「抽」格里 —— "
                "这是策略自带的闸门,不是面板算出来的",
    })


FAMS = {
    "world50": fam_world50,
    "t364": fam_t364,
    "s681": fam_s681_h1,
    "s840": fam_s840_h30,
    "t372": fam_t372,
}


def main() -> None:
    # 接着上次跑(分批跑时)合并
    if os.path.exists(OUT_PART):
        try:
            old = json.load(open(OUT_PART))
            PANEL.update({k: {d: float(v) for d, v in v2.items()} for k, v2 in old.get("panel", {}).items()})
            for k, v in old.get("meta", {}).items():
                if k.startswith("_"):
                    META.setdefault(k, {}).update(v)
                else:
                    META.setdefault(k, {}).update(v)
            print(f"[merge] 接上 {OUT_PART}: {len(PANEL)} 族", flush=True)
        except Exception:
            print("[merge] 旧分片读不了,重来", flush=True)
    want = sys.argv[1:] or list(FAMS)
    for k in want:
        fn = FAMS.get(k)
        if fn is None:
            print("NO SUCH FAMILY", k, flush=True)
            continue
        try:
            fn()
            print(f"[ok] {k}: {sorted(PANEL)[-1]} n={len(PANEL[sorted(PANEL)[-1]])}", flush=True)
        except Exception:
            META.setdefault("_errors", {})[k] = traceback.format_exc()[-1500:]
            print(f"[FAIL] {k}\n{traceback.format_exc()[-2000:]}", flush=True)
        json.dump({"panel": PANEL, "meta": META}, open(OUT_PART, "w"), default=str)

    rows = []
    for fam in sorted(PANEL):
        for d in sorted(PANEL[fam]):
            rows.append(f"{fam},{d},{PANEL[fam][d]!r},{META[fam]['funded']}")
    with open(OUT_CSV, "w") as f:
        f.write("family,d,nav,funded\n")
        f.write("\n".join(rows) + "\n")
    json.dump(META, open(OUT_META, "w"), ensure_ascii=False, indent=1, default=str)
    print(f"WROTE {OUT_CSV} · {len(PANEL)} 族 · {len(rows)} 行", flush=True)


if __name__ == "__main__":
    main()

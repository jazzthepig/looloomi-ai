#!/usr/bin/env python3
"""T-179 — CIS 页上公司「股数 52 周变化」逐家核对(改按申报股数之后)。

背景(Seth 10-22 夜,台账「S-668 H1 / S-670 ISSUE 更正」):
    原来的股数 = 市值 ÷ ohlcv_daily 复权收盘,把股息与分拆算成了回购。
    现在股数直接来自 world50_mcap_weekly.shares(source=shares_x_close_v3)。

本脚本做四件事:
  1. 取 CIS v2 个股宇宙(cis_v2_daily 最新一天 grp=equity)。
  2. 用 shares 列算 52 周变化;并排给出旧推法(市值 ÷ 复权收盘)的 52 周变化 ——
     两者之差就是「股息 / 分拆」在旧推法里被误记成回购的量。
  3. 台阶:窗口内单周 shares 变化 |Δ| > 2% 的周与日期。
  4. 自动口径探针(每条都是一个 B 类嫌疑,不是结论):
       - non_integer : shares 不是整数 ⇒ 不像申报封面/companyconcept 的原始计数
       - implied_jump : (mcap/shares)/close 这个「隐含价 / 收盘」之比自身跳变 > 2%
                        ⇒ 单位、汇率、ADR 比例或收盘口径在那一周切换了
                        (若那一周 shares 同时跳,那是公司行为;若没跳,是我们)
输出:
  /Volumes/CometCloudAI/cometcloud-local/research/t179/share_change_audit.csv
  /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-179_share_change_audit.md

外部证据(EDGAR)只在 ANNOTATION 里以人工判读结果的形式出现,
不进任何计算路径,不入库(规则 3b)。
"""
from __future__ import annotations

import csv
import json
import os
import urllib.request
from bisect import bisect_right as _bisect_right
from collections import Counter
from datetime import date, timedelta

if "SUPABASE_URL" not in os.environ or "SUPABASE_KEY" not in os.environ:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里,退出")
URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = os.environ["SUPABASE_KEY"]

HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

OUT_DIR = "/Volumes/CometCloudAI/cometcloud-local/research/t179"
RPT_DIR = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input"

WINDOW_DAYS = 364          # 52 周
STEP_PCT = 0.02            # 台阶阈值:单周 shares 变化 |Δ| > 2%
FLAG_PCT = 0.05            # 进名单的阈值:52 周变化 |Δ| > 5%
# 只取窗口前 1 年的上下文,用来分辨「窗口内的台阶」和「更早就换过口径」
FETCH_FROM = date(2024, 6, 1)


def q(path: str) -> list[dict]:
    """PostgREST 分页读。必须带 order= 主键排序,否则翻页边界会漂(T-170/T-173)。"""
    assert "order=" in path, "分页读必须带 order="
    out, off = [], 0
    while True:
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(
            URL + path + sep + "limit=1000&offset=" + str(off), headers=HDR
        )
        rows = json.loads(urllib.request.urlopen(req, timeout=180).read().decode())
        out.extend(rows)
        if len(rows) < 1000:
            return out
        off += 1000


def d(s: str) -> date:
    return date.fromisoformat(s[:10])


# ---------------------------------------------------------------- 1. 宇宙
def universe() -> tuple[list[str], str]:
    day = q("cis_v2_daily?select=d&order=d.desc&limit=1")[0]["d"]
    rows = q(
        "cis_v2_daily?select=symbol&d=eq." + day + "&grp=eq.equity&order=symbol.asc"
    )
    return sorted({r["symbol"] for r in rows}), day


# ---------------------------------------------------------------- 2. shares 周序列
def shares_series(syms: list[str]) -> dict[str, list[dict]]:
    rows = q(
        "world50_mcap_weekly?select=key,d,shares,mcap_usd&source=eq.shares_x_close_v3"
        "&shares=not.is.null&d=gte." + FETCH_FROM.isoformat()
        + "&order=key.asc,d.asc"
    )
    series: dict[str, list[dict]] = {}
    for r in rows:
        if r["key"] in syms:
            series.setdefault(r["key"], []).append(
                {"d": d(r["d"]), "shares": float(r["shares"]), "mcap": float(r["mcap_usd"])}
            )
    return series


# ---------------------------------------------------------------- 3. 旧推法需要的收盘
def closes(syms: list[str]) -> dict[str, dict[date, tuple[str, float]]]:
    """symbol -> {date: (source, close)}。

    **必须按 source 过滤,不能只按 asset_class**:ohlcv_daily 里 coingecko_pro_ohlc
    的加密行带着 asset_class='Equity'(2026-10-23 实测:T 的 eodhd 行还没到,
    取到的是币价 0.00494;STX 同时是 Seagate 与一个币)。asset_class=neq.Crypto
    挡不住这批 —— 只能认 eodhd / yfinance 这两个股票源。"""
    rows = q(
        "ohlcv_daily?select=symbol,asset_class,source,trade_date,close"
        "&symbol=in.(" + ",".join(syms) + ")&source=in.(eodhd,yfinance)"
        "&trade_date=gte." + FETCH_FROM.isoformat() + "&order=symbol.asc,trade_date.asc"
    )
    m: dict[str, dict[date, tuple[str, float]]] = {}
    for r in rows:
        if r["close"] is None:
            continue
        sym, day, src = r["symbol"], d(r["trade_date"]), r["source"]
        cur = m.setdefault(sym, {}).get(day)
        rank = {"eodhd": 0, "yfinance": 1}
        if cur is None or rank.get(src, 9) < rank.get(cur[0], 9):
            m[sym][day] = (src, float(r["close"]))
    return m


def close_asof(px: dict[str, dict[date, tuple[str, float]]], sym: str, day: date):
    """市值日期当天或之前最近的一个收盘(最多回看 7 天);再往前没有就用之后的第一个。

    注意:world50_mcap_weekly 的 d 可以比 ohlcv_daily 最后一个收盘还新 1-2 天
    (周五收盘 vs 周更跑在收盘之后),所以只向后找会大面积落空。
    这只是「取价」,不是零分布 / 盈亏 / A-B —— 那三类一律走 apparatus.py。"""
    ser = px.get(sym)
    if not ser:
        return None
    days = sorted(ser)
    i = _bisect_right(days, day) - 1
    if i >= 0:
        gap = (day - days[i]).days
        return ser[days[i]][1] if gap <= 7 else None
    if days:
        return ser[days[0]][1]
    return None


# ---------------------------------------------------------------- 4. 计算
def steps(seq: list[dict], key: str) -> list[tuple[date, float]]:
    out = []
    for a, b in zip(seq, seq[1:]):
        if a[key] > 0:
            ch = b[key] / a[key] - 1.0
            if abs(ch) > STEP_PCT:
                out.append((b["d"], ch))
    return out


def main() -> None:
    syms, asof = universe()
    print("CIS v2 equity universe:", len(syms), "as of", asof)
    ser = shares_series(syms)
    px = closes(syms)
    print("shares series:", len(ser), "close symbols:", len(px))

    rows_out = []
    for sym in syms:
        seq = sorted(ser.get(sym, []), key=lambda r: r["d"])
        if len(seq) < 8:
            rows_out.append(
                {
                    "key": sym, "new_52w_pct": None, "old_52w_pct": None,
                    "delta_pp": None, "new_shares": None, "old_shares": None,
                    "base_date": None, "last_date": None, "n_weeks": len(seq),
                    "steps": "NO_DATA", "non_integer": "", "implied_jump": "",
                    "ratio_last": None, "ratio_base": None, "implied_52w_pct": None,
                }
            )
            continue

        last = seq[-1]
        base_day = last["d"] - timedelta(days=WINDOW_DAYS)
        base = [r for r in seq if r["d"] <= base_day]
        if not base:
            continue
        base = base[-1]

        new_ch = last["shares"] / base["shares"] - 1.0

        # 旧推法:股数 = 市值 ÷ 复权收盘
        c_now = close_asof(px, sym, last["d"])
        c_old = close_asof(px, sym, base["d"])
        if c_now and c_old:
            old_now = last["mcap"] / c_now
            old_old = base["mcap"] / c_old
            old_ch = old_now / old_old - 1.0
            # implied = (市值 ÷ 收盘) ÷ 股数 = 收盘口径的漂移倍数(旧推法的偏差源)
            implied_ch = (old_now / last["shares"]) / (old_old / base["shares"]) - 1.0
        else:
            old_ch, implied_ch = None, None

        # 窗口内的 shares 台阶
        win = [r for r in seq if r["d"] > base["d"]]
        sh_steps = steps(win, "shares")

        # 隐含价 / 收盘 之比的台阶 —— 单位 / 汇率 / ADR 比例 / 收盘口径切换
        implied_seq = []
        for r in seq:
            c = close_asof(px, sym, r["d"])
            if c and r["shares"] > 0:
                implied_seq.append({"d": r["d"], "ip": (r["mcap"] / r["shares"]) / c})
        step_dates = {a for a, _ in sh_steps}
        ij_all = steps(implied_seq, "ip")
        # 只有「那一周 shares 没动、隐含价却动了」才是我们的口径问题;
        # shares 同时动的,是公司行为落在复权因子上。
        ij_ours = [x for x in ij_all if x[0] not in step_dates]

        # 口径探针:ratio = (mcap / shares) / close。ratio == 1 ⇒ 市值用的就是这个收盘;
        # ratio 偏离 1 ⇒ 市值那一侧与收盘那一侧不是同一个口径(复权 / 原始 / 汇率 / ADR)。
        # 两个锚点各记一次:老窗口内是否本来就对不齐。
        ip_at = {}
        for r in implied_seq:
            ip_at[r["d"]] = r["ip"]
        ratio_last = round(ip_at.get(last["d"], float("nan")), 4)
        ratio_base = round(ip_at.get(base["d"], float("nan")), 4)

        ni = [r["d"] for r in seq if abs(r["shares"] - round(r["shares"])) > 1.0]

        rows_out.append(
            {
                "key": sym,
                "new_52w_pct": round(new_ch * 100, 2),
                "old_52w_pct": round(old_ch * 100, 2) if old_ch is not None else None,
                "delta_pp": round((new_ch - old_ch) * 100, 2) if old_ch is not None else None,
                "new_shares": round(last["shares"]),
                "old_shares": round(base["shares"]),
                "base_date": base["d"].isoformat(),
                "last_date": last["d"].isoformat(),
                "n_weeks": len(seq),
                "steps": "; ".join(f"{a.isoformat()} {b*100:+.1f}%" for a, b in sh_steps),
                "non_integer": f"{len(ni)}/{len(seq)}" if ni else "",
                "implied_jump": "; ".join(f"{a.isoformat()} {b*100:+.1f}%" for a, b in ij_ours),
                "ratio_last": ratio_last,
                "ratio_base": ratio_base,
                "implied_52w_pct": round(implied_ch * 100, 2) if implied_ch is not None else None,
            }
        )

    rows_out.sort(key=lambda r: (-abs(r["new_52w_pct"] or 0), r["key"]))
    flagged = [r for r in rows_out if r["new_52w_pct"] is not None and abs(r["new_52w_pct"]) / 100 > FLAG_PCT]

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(RPT_DIR, exist_ok=True)
    fields = [
        "key", "new_52w_pct", "old_52w_pct", "delta_pp", "new_shares", "old_shares",
        "base_date", "last_date", "n_weeks", "steps", "non_integer", "implied_jump",
        "ratio_last", "ratio_base", "implied_52w_pct", "category", "evidence",
    ]
    for r in rows_out:
        r.setdefault("category", "")
        r.setdefault("evidence", "")
        r.update(ANNOTATION.get(r["key"], {}))
    with open(OUT_DIR + "/share_change_audit.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows_out:
            w.writerow({k: r.get(k, "") for k in fields})

    with open(OUT_DIR + "/t179_summary.json", "w") as fh:
        json.dump(
            {"asof": asof, "universe": len(syms), "rows": rows_out, "flagged": len(flagged)},
            fh, indent=1,
        )

    print("flagged |52w| > 5%:", len(flagged), "of", len(rows_out))
    for r in flagged:
        print(
            f"  {r['key']:6s} new={r['new_52w_pct']:+7.2f}%  old={r['old_52w_pct']}  "
            f"d={r['delta_pp']}  ni={r['non_integer']}  ij={r['implied_jump'][:60]}"
        )
    print("--- delta |pp| > 3 (old vs new disagreement) ---")
    for r in rows_out:
        if r["delta_pp"] is not None and abs(r["delta_pp"]) > 3:
            print(f"  {r['key']:6s} new={r['new_52w_pct']:+7.2f}% old={r['old_52w_pct']:+7.2f}% d={r['delta_pp']:+7.2f}pp")
    print("--- non-integer shares ---")
    for r in rows_out:
        if r["non_integer"]:
            print(f"  {r['key']:6s} {r['non_integer']}")
    print("--- implied ratio jumps ---")
    for r in rows_out:
        if r["implied_jump"]:
            print(f"  {r['key']:6s} {r['implied_jump'][:110]}")
    print("--- mcap/close 口径对不齐 (|implied 52w| > 3%, 即旧推法的偏差源) ---")
    n = sum(1 for r in rows_out if r["implied_52w_pct"] is not None and abs(r["implied_52w_pct"]) > 3)
    print("   ", n, "of", len(rows_out))
    print("--- ratio_last != 1 (最后一行的市值与收盘不是一个口径) ---")
    m = [r for r in rows_out if r["ratio_last"] and abs(r["ratio_last"] - 1) > 0.02]
    print("   ", len(m), "symbols; ratio_last range",
          round(min(r["ratio_last"] for r in m), 3) if m else None,
          round(max(r["ratio_last"] for r in m), 3) if m else None)

    from collections import Counter as _C
    print("--- 类别计数 ---")
    print("   ", dict(_C(r["category"] for r in rows_out if r["category"])))


# ---------------------------------------------------------------- 人工判读(证据)
# 这里是**注释**,不是计算输入:compute 路径一次也没读过它。
# 外部证据只以结论 + 申报号的形式写在这里,原始 JSON 不入库(T-179 卡,规则 3b)。
ANNOTATION: dict[str, dict] = {
    "TSLA": {"category": "A", "evidence": "台阶与申报封面股数逐个对得上:10-K 0001628280-26-003952 (end 2026-01-23) 3,752,431,984 = 库里 2026-01-30 同值;10-Q 0001628280-26-049270 (end 2026-07-16) 3,949,547,394 = 库里 2026-10-21 同值。真增发"},
    "PANW": {"category": "A", "evidence": "10-Q 0001327567-26-000005 (end 2026-02-11) 816,000,000 = 库里 2026-02-20 台阶 697,000,000→816,000,000 (+17.07%);10-K 0001327567-26-000023 818,000,000 = 库里末值。真收购换股(CyberArk)"},
    "INTC": {"category": "A", "evidence": "10-K 0000050863-26-000011 (end 2026-01-16) 4,995,000,000 = 库里 2026-01-23;10-Q 0000050863-26-000157 5,044,000,000 = 库里末值。真增发(政府/战略投资)"},
    "CVX": {"category": "A", "evidence": "10-Q 0000093410-25-000108 (end 2025-09-30) 2,013,521,597 = 库里 2025-11-07 台阶 1,727,990,376→2,013,521,597 (+16.52%)。真事件:换股;末值 1,975,771,274 与 10-Q 0000093410-26-000167 逐位相同"},
    "UL": {"category": "A", "evidence": "20-F 0000217410-26-000007 (end 2025-12-31, filed 2026-03-12) 2,181,005,247 = 库里 2026-03-13 台阶后的值,逐位相同。真回购注销"},
    "CRM": {"category": "A", "evidence": "10-Q 0001108524-26-000127 (end 2026-05-21) 819,000,000 = 库里 2026-05-29 台阶后值;10-Q 0001108524-26-000190 823,000,000 = 末值。真回购"},
    "TTE": {"category": "A", "evidence": "20-F 0001104659-26-035876 (end 2025-12-31, filed 2026-03-27) 2,206,585,543 = 库里 2026-03-27 台阶后值,逐位相同。真回购注销"},
    "MPC": {"category": "A", "evidence": "10-Q 0001510295-26-000061 (end 2026-07-30) 280,824,763 = 库里末值,逐位相同。真回购"},
    "VLO": {"category": "A", "evidence": "10-Q 0001628280-26-050937 (end 2026-07-24) 287,927,461 = 库里末值,逐位相同。真回购"},
    "BKNG": {"category": "A", "evidence": "10-Q 0001075531-26-000037 (end 2026-07-27) 751,380,500 = 库里末值。库里的起点 810,247,297 已是 25:1 拆股后口径(申报 32,233,815×25≈806M),历史已正确复权"},
    "ADBE": {"category": "A", "evidence": "10-Q 0000796343-26-000156 (end 2026-09-18) 389,200,000 = 库里末值,逐位相同;起点 418,600,000 与 10-Q 0000796343-25-000107 相同。真回购"},
    "STX": {"category": "A", "evidence": "10-K 0001137789-26-000159 (end 2026-07-31) 226,644,518 = 库里末值,逐位相同;中途 218,073,067 = 10-Q 0001137789-26-000026。真股权激励 + 回购净额"},
    "ORCL": {"category": "A", "evidence": "10-Q 0001193125-26-389274 (end 2026-09-07) 3,023,736,000 = 库里 2026-09-11 台阶后值,逐位相同。真增发"},
    "T": {"category": "A", "evidence": "10-Q 0000732717-26-000372 (end 2026-10-15) 6,736,473,433 = 库里末值,逐位相同。−5.79% 是 5 次连续回购(每次都 <2%,单周台阶检测看不见);起点 7,150,385,480 比最近申报封面 7,089,449,495 高 0.86%,是申报滞后不是口径错"},
    "WFC": {"category": "A", "evidence": "10-Q 0000072971-26-000302 (end 2026-07-17) 3,023,999,336 = 库里末值,逐位相同。真回购"},
    "BAC": {"category": "A", "evidence": "10-Q 0000070858-26-000394 (end 2026-07-30) 6,992,748,365 = 库里末值,逐位相同。真回购"},
    "DELL": {"category": "A", "evidence": "us-gaap CommonStockSharesOutstanding 0001571996-26-000046 (end 2026-07-31) 640,000,000 = 库里末值;652,000,000 = 10-K 0001571996-26-000008。真回购。起点 675,000,000 比 10-Q 0001571996-25-000127 的 667,000,000 高 1.2%(申报滞后一档)"},
    "VZ": {"category": "A", "evidence": "10-Q 0000732712-26-000046 (end 2026-06-30) 4,154,775,202 = 库里末值,逐位相同;起点 4,216,324,808 与 10-Q 0000732712-25-000116 的 4,216,425,489 差 0.002%。−1.46% 是真的股息/回购,旧推法的 −9.64% 里约 8.2pp 是复权收盘带来的假象"},
    "MO": {"category": "A", "evidence": "10-Q 0000764180-26-000094 (end 2026-07-22) 1,669,743,926 = 库里末值,逐位相同;起点 1,679,890,953 与 0000764180-25-000130 的 1,678,671,552 差 0.07%。−0.60% 是真的"},
    "WELL": {"category": "B", "evidence": "起点股数陈旧:库里 2025-10-17 是 641,308,062,但 EDGAR 申报封面 0000766704-25-000040 (end 2025-09-30) 已经是 684,240,531 —— 起点低了 6.3%,所以 +12.39% 被高估。EDGAR 后续 696,631,868 (10-K 0000766704-26-000010) / 704,870,377 (10-Q 0000766704-26-000021) 推出的真实 52 周变化只有 +3%~+5%。修:起点周改用 dei 封面股数(见 T-179 报告 B-2)"},
    "CMCSA": {"category": "B", "evidence": "库里 3,564,000,000 全是整数百万,像分类相加或估算而非封面原值;且隐含比值 ratio_base=1.1241 —— 起点周市值比 shares×close 高 12.4%,像只记了主类股数(多类股合计漏了别类)。EDGAR companyfacts 里 CMCSA 完全没有 dei/us-gaap 的 shares 概念,封面股数不按标准概念报,自动核不了。修:人工核 CMCSA 各注册类(该局修不入库,交 Seth)"},
}

if __name__ == "__main__":
    main()
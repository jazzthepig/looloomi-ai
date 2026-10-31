#!/usr/bin/env python3
"""T-216 · 台账 M-222 的数字与重算结果的一致性检查(只读)。

跑法:python3 docs/research/t216_check_ledger.py
读:t216_pit_recompute.json(由 t216_pit_recompute.py 生成)+ 台账 markdown 原文。
判:台账正文里写的每个头条数字,必须与 JSON 里重算出来的值逐位相等;不等即 FAIL。
不读 .env、不打印 key、不改任何文件、不跑 24 格。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSON_PATH = HERE / "t216_pit_recompute.json"
LEDGER_PATH = HERE / "M-222_T005_prereg_rework_2026-10-31.md"

r = json.loads(JSON_PATH.read_text())
md = LEDGER_PATH.read_text()

pit = r["pit"]
v5 = r["v5"]
g88 = r["v5_vs_90_88"]
beta = r["beta"]["by_prefix"]

fails: list[str] = []
checks: list[tuple[str, bool, str]] = []


def chk(name: str, got, want, extra: str = "") -> None:
    ok = got == want
    checks.append((name, ok, f"got={got!r} want={want!r} {extra}".strip()))
    if not ok:
        fails.append(name)


def md_has(label: str, needle: str) -> None:
    ok = needle in md
    checks.append((f"台账正文含 {label}", ok, needle))
    if not ok:
        fails.append(f"台账正文缺 {label}: {needle}")


# ---- 1. regime PIT 重算(卡面 ①)
bh = "guard_db:binance_hist|K19|lag"
chk("PIT binance_hist lag1 RISK_OFF 天", pit[f"{bh}1"]["risk_off_days"], 401)
chk("PIT binance_hist lag1 live 天", pit[f"{bh}1"]["live_days"], 296)
chk("PIT binance_hist lag1 60/40 OOS live", pit[f"{bh}1"]["splits"]["60/40"]["live_oos"], 26)
chk("PIT binance_hist lag3 RISK_OFF 天", pit[f"{bh}3"]["risk_off_days"], 401)
chk("PIT binance_hist lag3 live 天", pit[f"{bh}3"]["live_days"], 294)
chk("PIT binance_hist lag7 RISK_OFF 天", pit[f"{bh}7"]["risk_off_days"], 401)
chk("PIT binance_hist lag7 live 天", pit[f"{bh}7"]["live_days"], 290)
chk("lag 轴退化:三档 RISK_OFF 天相同",
    len({pit[f"{bh}{l}"]["risk_off_days"] for l in (1, 3, 7)}), 1)
pq = "local_parquet|K19|lag"
chk("PIT parquet lag1 判据可用天", pit[f"{pq}1"]["criterion_days"], 637)
chk("PIT parquet lag1 RISK_OFF 天", pit[f"{pq}1"]["risk_off_days"], 328)
chk("PIT parquet lag1 live 天", pit[f"{pq}1"]["live_days"], 226)
chk("PIT parquet lag1 60/40 OOS live", pit[f"{pq}1"]["splits"]["60/40"]["live_oos"], 26)
cg = "guard_db:coingecko|K19|lag1"
chk("PIT coingecko lag1 RISK_OFF 天(选源敏感性)", pit[cg]["risk_off_days"], 365)

# ---- 2. V5 现状(改前的三个数)
chk("V5 风控天(RISK_OFF+STAGFLATION)", v5["risk_days_total"], 290)
chk("V5 live 天", v5["live_days_total"], 349)
chk("V5 60/40 OOS live 天", v5["splits"]["60/40"]["v5_live_days_oos"], 88)

# ---- 3. 90 vs 88(卡面 ⑤)
chk("OOS phase!=CASH 天数(=90)", g88["oos_phase_not_cash_days"], 90)
chk("OOS live 天数(=88)", g88["oos_live_days"], 88)
chk("OOS phase==CASH 天数(=245)", g88["oos_phase_cash_days"], 245)
chk("差的 2 天", g88["gap_days_phase_not_cash_but_risk"], ["2026-06-06", "2026-06-07"])
chk("avg_cash 恒等 245/335", g88["identity_245_over_335"], 0.7313432835820896)
chk("avg_cash 恒等 1-90/335", g88["identity_1_minus_90_over_335"], 0.7313432835820896)
chk("风控天口径 187/335 ≠ avg_cash", g88["identity_187_over_335_risk_only"] != 0.7313432835820896, True)

# ---- 4. β 带(卡面 ②)
chk("AB 落带数", beta["AB"]["in_band_0.5_0.9"], 3645)
chk("AB n", beta["AB"]["n"], 3645)
chk("D 落带数", beta["D"]["in_band_0.5_0.9"], 0)
chk("D n", beta["D"]["n"], 32805)
chk("Dv2 落带数", beta["Dv2"]["in_band_0.5_0.9"], 0)
chk("Dv2 n", beta["Dv2"]["n"], 486)
chk("结果总行数", r["beta"]["total_rows"], 36936)

# ---- 5. 加仓机制 / 选源(卡面 ③)
chk("w_add 全库 0 命中", r["code_grep"]["w_add"]["total"], 0)
chk("add_size 全库 0 命中", r["code_grep"]["add_size"]["total"], 0)
chk("守护库 2021-01-05 起有数据", r["inputs"]["guard_db_panel_from_2021_01_05"]["n_with_data"], 20)
chk("BTC 守护库总行数", r["inputs"]["btc_guard_db_rows"]["read"], 7764)

# ---- 6. 台账正文必须写出这些数(防转录错)
for label, needle in [
    ("改前 RISK_OFF 290", "**290**"), ("改后 RISK_OFF 401", "**401**"),
    ("改前 live 349", "**349**"), ("改后 live 296", "**296**"),
    ("改前 OOS 88", "**88**"), ("改后 OOS 26", "**26**"),
    ("β AB 3,645/3,645", "3,645 / 3,645"), ("β D 0/32,805", "0 / 32,805"),
    ("β Dv2 0/486", "0 / 486"),
    ("90 天口径", "**90**"), ("245 天口径", "**245**"),
    ("MA200 预热 637", "637"), ("守护库全覆盖 836", "836/836"),
    ("有效宽度 ≈ 8 格", "≈ 8 格"), ("lag 退化 401/401/401", "401/401/401"),
    ("选源三源", "同键三源"), ("零分布 95 分位", "零分布 95 分位"),
    ("T-038 裁定", "T-038"), ("phases_7d.csv", "phases_7d.csv"),
    ("2023-12-26 起点", "2023-12-26"), ("90 vs 88 标题", "90 vs 88"),
]:
    md_has(label, needle)

# ---- 7. 台账不得出现被撤销的断言 / 买卖词
forbidden = ["P(24 格里 ≥1 格过)≈1.0 的数", "BUY", "SELL", "ACCUMULATE", "AVOID"]
for bad in forbidden:
    ok = bad not in md
    checks.append((f"台账不含禁用表述 {bad!r}", ok, ""))
    if not ok:
        fails.append(f"台账含禁用表述 {bad!r}")

n_ok = sum(1 for _, ok, _ in checks if ok)
print(f"检查 {len(checks)} 项:通过 {n_ok},失败 {len(fails)}")
for name, ok, extra in checks:
    if not ok:
        print(f"  ✗ {name}  {extra}")
if fails:
    raise SystemExit(f"FAILED: {len(fails)} 项不一致 —— 台账与重算结果对不上")
print("✓ 台账 M-222 的每个头条数字都与 t216_pit_recompute.json 逐位一致")

"""T-044b:跨源价格一致性的常驻守卫 —— 每天把几个价源与 binance_hist 比一次,结果落表(S-484)。

判据用 lane A 写的 `agreement()`(T-044a,6 个回放测试):错一天(对数收益相关,滑动 30 天)、
持续偏离(>3% 连续 ≥5 天)、binance_hist 冻结行(≥3 天同价而对照源在动)。这里只做三件事:
**取近 45 天**(不取全史 —— 全史会把 2 月那段已知污染每天重报一遍,而且 PostgREST 一次只给 1,000 行,
不分页就只拿到最老的那 1,000 行)、**只看我们账本真在用的币**、**每天每源一行**(幂等 upsert,不是每个发现插一行)。

| 对照源 | 为什么 |
|---|---|
| coingecko_pro_ohlc | HL 账本与代币化倾斜按它记账 |
| asset_mcap_daily(price) | ① 的权重、风格表头都读它 |
| hyperliquid | 执行场所;有行才比 |

判活:`select source, max(d) from price_source_agreement_daily group by 1` = 今天(UTC)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

WINDOW_DAYS = 45
CANDIDATES = ("coingecko_pro_ohlc", "asset_mcap_daily", "hyperliquid")
EXTRA_SYMBOLS = ("HYPE", "ONDO", "PENDLE", "POLYX")
TABLE = "price_source_agreement_daily"
WRITES_TABLES = (TABLE,)
CODE_REF = "t044b-v1"


def symbols() -> list[str]:
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    return list(dict.fromkeys(list(DEFAULT_UNIVERSE) + list(EXTRA_SYMBOLS)))


def summarize(d: str, source: str, findings: list, n_compared: int) -> dict:
    """纯函数:一天一源一行。最严重的排前面,最多留 10 条。"""
    order = {"error": 0, "warn": 1, "info": 2}
    fs = sorted(findings, key=lambda f: (order.get(f.severity, 9), f.symbol))
    by_kind: dict[str, int] = {}
    for f in fs:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    return {"d": d, "source": source, "n_symbols": n_compared, "n_findings": len(fs),
            "n_error": sum(1 for f in fs if f.severity == "error"), "by_kind": by_kind,
            "worst": [{"symbol": f.symbol, "kind": f.kind, "severity": f.severity, "detail": f.detail,
                       "dates": f.dates} for f in fs[:10]],
            "code_ref": CODE_REF}


async def _panel(source: str, syms: list[str], start: str) -> dict[str, dict[str, float]]:
    from src.data.style.header import _read_all
    if source == "asset_mcap_daily":
        rows = await _read_all("asset_mcap_daily", {"select": "symbol,d,price", "order": "d.asc",
                                                    "symbol": "in.(" + ",".join(syms) + ")", "d": f"gte.{start}"})
        key_d, key_p = "d", "price"
    else:
        rows = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close", "order": "trade_date.asc",
                                               "source": f"eq.{source}", "symbol": "in.(" + ",".join(syms) + ")",
                                               "trade_date": f"gte.{start}"})
        key_d, key_p = "trade_date", "close"
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        if r.get(key_p) is None:
            continue
        out.setdefault(r["symbol"], {})[str(r[key_d])[:10]] = float(r[key_p])
    return out


async def run_once() -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.research.validation.t_044_price_source_agreement import SourcePanel, agreement

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    syms = symbols()
    base = await _panel("binance_hist", syms, start)
    if not base:
        return {"ok": False, "reason": "binance_hist 近 45 天一行都读不到 —— 没有基准就不比"}
    rows, total_err = [], 0
    for src in CANDIDATES:
        cand = await _panel(src, syms, start)
        findings, n = [], 0
        for s in syms:
            if s not in base or s not in cand or len(base[s]) < 10 or len(cand[s]) < 10:
                continue
            n += 1
            b = SourcePanel(s, "binance_hist", sorted(base[s]), [base[s][d] for d in sorted(base[s])])
            c = SourcePanel(s, src, sorted(cand[s]), [cand[s][d] for d in sorted(cand[s])])
            findings.extend(agreement(b, c))
        row = summarize(today.isoformat(), src, findings, n)
        total_err += row["n_error"]
        rows.append(row)
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d,source")
    if not w.ok:
        return {"ok": False, "reason": f"{TABLE} 写入失败:{w.why}"}
    brief = "; ".join(f"{r['source']} {r['n_findings']} 条({r['n_symbols']} 币)" for r in rows)
    return {"ok": True, "n_error": total_err, "rows": rows,
            "reason": f"近 {WINDOW_DAYS} 天对 binance_hist:{brief}"}

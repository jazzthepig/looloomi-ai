"""特征臂:把 CIS 当特征放进组合,三条臂前向对照(T-077 / S-528)。

## 为什么

Jazz 10-09:「CIS 的这个不是问题,是 feature —— 信号是过去的,我们要做的是未来;强信号之后会回撤,
底部会反弹,关键看组合怎样利用」。S-527:去 β、按周组合测试后,OUT 名字 17 个月跑输同类等权(超额 t −2.9,
与市场相关 −0.26,不是 β);BTC 在 50 日线下方时给出的 OUT 最差,UNDER 名字相对反弹。
只有 17 个月 CIS 历史,全在样本内 —— **回放只是描述,前向才是检验**。

## 三条臂(S-528 预注册)

- `cis_ew`     宇宙等权(对照)
- `cis_follow` 只持 OUT 名字等权(没有 OUT ⇒ 宇宙等权)—— 照标签字面做会怎样
- `cis_contra` OUT 权重 0;BTC_{d−1} 在 50 日均线下方时 UNDER 2 倍、其余 1 倍;上方时 UNDER 与 NEUTRAL 都 1 倍

宇宙:每周一 d,CIS 加密名字(去稳定币),d−1 有信号且有 binance_hist 收盘。满仓;成本 10bp × 换手。

## 判活判据(规则 5b ②)

    select max(d) from feature_arms_daily;   -- = 昨天(UTC)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

from src.data.signals.core_variants import _stats, simulate

TABLE = "feature_arms_daily"
WRITES_TABLES = (TABLE,)
CODE_REF = "T-077 feature arms v1"
ARMS = ("cis_ew", "cis_follow", "cis_contra")
REPLAY_START = pd.Timestamp("2025-05-12")
INCEPTION = pd.Timestamp("2026-10-11")
MA_DAYS = 50
CRYPTO_CLASSES = ("Crypto", "DeFi", "Gaming", "Infrastructure", "L1", "L2", "Memecoin", "RWA")
STABLES = frozenset({"USDT", "USDC", "DAI", "FDUSD", "USDE", "TUSD", "PYUSD", "USDS", "USD1"})


def cis_group(signal: Optional[str]) -> Optional[str]:
    """纯函数。五档合规信号 → OUT / UNDER / NEU;认不出 ⇒ None(不进宇宙)。"""
    s = (signal or "").strip().upper()
    if s in ("STRONG OUTPERFORM", "OUTPERFORM"):
        return "OUT"
    if s in ("UNDERPERFORM", "UNDERWEIGHT"):
        return "UNDER"
    if s == "NEUTRAL":
        return "NEU"
    return None


def arm_weights(arm: str, groups: Mapping[str, str], btc_below_ma: Optional[bool]) -> dict[str, float]:
    """纯函数。groups:名字 → OUT / UNDER / NEU(已是当天宇宙)。均线读不出 ⇒ 当作上方(不加倍)。"""
    names = sorted(groups)
    if not names:
        return {}
    if arm == "cis_ew":
        raw = {s: 1.0 for s in names}
    elif arm == "cis_follow":
        outs = [s for s in names if groups[s] == "OUT"]
        raw = {s: 1.0 for s in (outs or names)}
    elif arm == "cis_contra":
        up = 2.0 if btc_below_ma else 1.0
        raw = {s: (0.0 if groups[s] == "OUT" else up if groups[s] == "UNDER" else 1.0) for s in names}
    else:
        raise ValueError(f"未知臂 {arm}")
    tot = sum(raw.values())
    if tot <= 0:                                            # 全是 OUT ⇒ cis_contra 退回等权
        return {s: 1.0 / len(names) for s in names}
    return {s: v / tot for s, v in raw.items() if v > 0}


def build(px: pd.DataFrame, groups: pd.DataFrame, end: pd.Timestamp) -> tuple[list[dict], dict[str, Any]]:
    """纯函数。px:日收盘(行 = 日,列 = 名字,含 BTC);groups:同形状,值 = OUT / UNDER / NEU / None(d 当天的信号)。"""
    px = px.sort_index()
    days_all = pd.date_range(px.index.min(), max(px.index.max(), end), freq="D")
    px = px.reindex(days_all)
    groups = groups.reindex(index=days_all, columns=px.columns)
    btc = px["BTC"] if "BTC" in px.columns else pd.Series(index=days_all, dtype=float)
    below = btc < btc.rolling(MA_DAYS, min_periods=MA_DAYS).mean()
    below = below.where(btc.rolling(MA_DAYS, min_periods=MA_DAYS).mean().notna())
    rets = (px / px.shift(1) - 1).loc[(days_all >= REPLAY_START) & (days_all <= end)]
    rebal = [d for d in rets.index if d.weekday() == 0]
    targets: dict[str, dict] = {a: {} for a in ARMS}
    last_groups: dict[str, str] = {}
    for d in rebal:
        y = d - pd.Timedelta(days=1)
        g = {s: groups.at[y, s] for s in px.columns
             if s not in STABLES and isinstance(groups.at[y, s], str) and pd.notna(px.at[y, s])}
        if not g:
            continue
        b = below.get(y)
        for a in ARMS:
            targets[a][d] = arm_weights(a, g, None if pd.isna(b) else bool(b))
        last_groups = g
    arm_rets = {a: simulate(rets, targets[a]) for a in ARMS}
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for a, s in arm_rets.items():
        nav = (1 + s).cumprod()
        for d, v in s.items():
            rows.append({"d": d.date().isoformat(), "arm": a, "ret": round(float(v), 8), "nav": round(float(nav[d]), 8),
                         "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF, "computed_at": now})
    ev: dict[str, Any] = {"caveat": "CIS 历史只有 2025-05 起,回放全在样本内(S-527 就是在这段上看出来的)—— 前向才是检验(S-528)"}
    for name, (lo, hi) in {"replay_in_sample": (REPLAY_START, INCEPTION), "forward": (INCEPTION + pd.Timedelta(days=1), end)}.items():
        sel = (rets.index >= lo) & (rets.index <= hi)
        ev[name] = {a: _stats(s[sel]) for a, s in arm_rets.items()}
    ev["latest_universe"] = {k: sum(1 for v in last_groups.values() if v == k) for k in ("OUT", "UNDER", "NEU")}
    ev["latest_out"] = sorted(s for s, v in last_groups.items() if v == "OUT")
    return rows, ev


def groups_frame(sig_rows: list[dict]) -> pd.DataFrame:
    """纯函数。v_cis_signal_daily 的行 → 日 × 名字 的 OUT / UNDER / NEU。"""
    if not sig_rows:
        return pd.DataFrame()
    g = pd.DataFrame(sig_rows)
    g = g[g["asset_class"].isin(CRYPTO_CLASSES)]
    g["grp"] = g["signal"].map(cis_group)
    g = g.dropna(subset=["grp"])
    g["d"] = pd.to_datetime(g["d"])
    return g.pivot_table(index="d", columns="symbol", values="grp", aggfunc="last")


async def run_once() -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel
    from src.data.signals.core_cap import PRICE_SOURCE
    from src.data.style.header import _read_all

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    sig = await _read_all("v_cis_signal_daily", {"select": "symbol,asset_class,d,signal",
                                                 "asset_class": f"in.({','.join(CRYPTO_CLASSES)})",
                                                 "d": f"gte.{(REPLAY_START - pd.Timedelta(days=7)).date()}"})
    grp = groups_frame(sig)
    if grp.empty:
        return {"ok": False, "refused": True, "written": 0, "reason": "v_cis_signal_daily 读到 0 行"}
    names = sorted(set(grp.columns) - STABLES | {"BTC"})
    start = (REPLAY_START - pd.Timedelta(days=MA_DAYS + 30)).date().isoformat()
    p = await read_panel(names, start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))
    if px.index.max() < target:
        return {"ok": False, "refused": True, "written": 0, "reason": f"收盘只到 {px.index.max().date()}"}
    rows, ev = await asyncio.to_thread(build, px, grp, target)
    for i in range(0, len(rows), 2000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="d,arm")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"回放至 {target.date()}", "eval": ev}

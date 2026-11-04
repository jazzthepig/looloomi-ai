"""② β+:小股东待遇倾斜 —— 前向记录(S-711,Jazz 11-02「CIS 的核心维度 = 小股东待遇」)。

## 为什么有这本账

② 的「挑更好的资产」三次 ❌(S-694 / T-224 / T-225)全是用动量 / 杠杆类合成去「躲开最差档」。Jazz 给的**原因**不一样:
发行方把可分配利润留给小股东、不靠稀释和关联交易瓜分 —— 这是慢变量,和动量不相关。滞后的那一半(S-661)在历史上
留出段有效但控制规模后所剩无几;**这本账不回测,只前向**:从起点起每天按 `treatment_daily`(时点)记一条倾斜臂、
一条等权基准臂,90 天后按预注册判。

## 预注册(改任何一项 = 新起点,旧记录留档)

    面板                 CIS 的 25 个加密名字(cis_provider.CRYPTO_ASSETS),只在当天有真实收盘的币上分配
    基准臂 panel_hold    面板等权
    倾斜臂 treatment_tilt   等权 × 乘数后归一:分配率 ≥ 0.5(有收入且至少一半分给持有人)1.5 · 有收入但分配率 < 0.5 → 0.5 ·
                         没有协议收入(NULL,BTC 这类)1.0;乘数取**再平衡日前一天**的 treatment_daily(时点)
    再平衡               起点 + 每周一(UTC)收盘;成本 换手 × 10 bps;只持现货、无杠杆
    起点                 2026-11-04 收盘
    判据(S-711)        起点后 90 天:倾斜臂 − 基准臂 累计差 > 0,且 ≥ 随机乘数(同样的 1.5 / 0.5 / 1.0 个数随机分配,1,000 次,种子 711)
                         分布的 95 分位;按 regime 分段报。不够 90 天不谈结论。

## 不存状态 —— 每次从起点重算(同 tokenization_tilt)
判活:`select arm, max(d), count(*) from treatment_tilt_daily group by 1;`   -- UTC 06:00 后 max(d) 应 = 昨天
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

TABLE = "treatment_tilt_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"treatment_tilt_daily": ("d", "arm", "nav", "ret", "weights", "tilt_classes", "rebalanced", "turnover", "n_quoted",
                                           "n_filled", "barred", "source", "inception", "code_ref", "computed_at")}
ARMS = ("panel_hold", "treatment_tilt")
MULT = {"pays": 1.5, "keeps": 0.5, "none": 1.0}
PAYS_SHARE = 0.5
COST_BPS = 10.0
INCEPTION = pd.Timestamp("2026-11-04")
PRICE_SOURCE = "coingecko_pro_ohlc"
MIN_QUOTED_WEIGHT = 0.90
CODE_REF = "S-711 treatment_tilt v1"


def panel_universe() -> tuple[str, ...]:
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    return tuple(CRYPTO_ASSETS)


def classify(row: Optional[Mapping[str, Any]]) -> str:
    """纯函数。treatment_daily 的一行 → pays / keeps / none。"""
    if not row or row.get("revenue_30d") is None:
        return "none"
    share = row.get("holders_share")
    if share is None:
        return "none"
    return "pays" if float(share) >= PAYS_SHARE else "keeps"


def targets(arm: str, available: set[str], panel: tuple[str, ...], classes: Mapping[str, str]) -> dict[str, float]:
    names = [s for s in panel if s in available]
    if not names:
        return {}
    if arm == "panel_hold":
        return {s: 1.0 / len(names) for s in names}
    raw = {s: MULT[classes.get(s, "none")] for s in names}
    tot = sum(raw.values())
    return {s: v / tot for s, v in raw.items()}


def is_rebalance_day(d: pd.Timestamp, i: int) -> bool:
    return i == 0 or d.weekday() == 0


def compute_path(px: pd.DataFrame, panel: tuple[str, ...], classes_by_day: Mapping[str, Mapping[str, str]],
                 barred: list[str], source: str, end: pd.Timestamp | None = None) -> list[dict]:
    """纯函数:起点到 end 的每日行(两臂)。classes_by_day = {日期: {symbol: class}},按再平衡日前一天取(没有 ⇒ 全 none,并记下)。"""
    px = px.sort_index()
    days = [d for d in px.index if d >= INCEPTION and (end is None or d <= end)]
    if not days or days[0] != INCEPTION:
        raise ValueError(f"起点 {INCEPTION.date()} 那天没有面板行 —— 不从别的日子悄悄开始")
    from src.data.accounting.nav_kernel import run_nav
    rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for arm in ARMS:
        orders, used_classes = {}, {}
        for i, d in enumerate(days):
            if is_rebalance_day(d, i):
                row_px = px.loc[d]
                prev = (d - pd.Timedelta(days=1)).date().isoformat()
                cls = dict(classes_by_day.get(prev) or {})
                used_classes[d] = cls
                orders[d] = targets(arm, {s for s in row_px.index if pd.notna(row_px[s])}, panel, cls)
        book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT, label=arm,
                       renormalize_to_quoted=False, days=days)
        last_cls: dict = {}
        for d, b in zip(days, book):
            if d in used_classes:
                last_cls = used_classes[d]
            w = b["w"]
            rows.append({"d": d.date().isoformat(), "arm": arm, "nav": round(b["nav"], 8), "ret": round(b["ret"], 8),
                         "weights": {s: round(v, 5) for s, v in sorted(w.items(), key=lambda kv: -kv[1])},
                         "tilt_classes": {k: sum(1 for s in w if last_cls.get(s, "none") == k) for k in MULT} if arm == "treatment_tilt" else {},
                         "rebalanced": b["traded"], "turnover": round(b["turnover"], 6), "n_quoted": b["n_quoted"], "n_filled": b["n_filled"],
                         "barred": barred, "source": source, "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF, "computed_at": now})
    return rows


async def classes_history(start: str) -> dict[str, dict[str, str]]:
    """treatment_daily(≥ start)→ {d: {symbol: class}}。"""
    from src.data.style.header import _read_all
    rows = await _read_all("treatment_daily", {"select": "symbol,d,revenue_30d,holders_share", "d": f"gte.{start}", "order": "d.asc,symbol.asc"})
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        out.setdefault(str(r["d"])[:10], {})[r["symbol"]] = classify(r)
    return out


async def run_once() -> dict[str, Any]:
    """重算到昨天那根已收盘日线并整条 upsert。幂等。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel
    from src.data.signals.tokenization_tilt import closing_bars_final
    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if target < INCEPTION:
        return {"ok": True, "refused": True, "written": 0, "reason": f"起点 {INCEPTION.date()} 未到"}
    panel = panel_universe()
    start = (INCEPTION - pd.Timedelta(days=3)).date().isoformat()
    p = await read_panel(list(panel), start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))
    ready, stale, why = await closing_bars_final(p.symbols, target, PRICE_SOURCE)
    if not ready:
        return why
    px.loc[target, [c for c in px.columns if c not in ready]] = float("nan")
    classes = await classes_history(start)
    rows = await asyncio.to_thread(compute_path, px, panel, classes, list(p.barred), p.source, target)
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    last = {r["arm"]: r["nav"] for r in rows if r["d"] == target.date().isoformat()}
    cls = next((r["tilt_classes"] for r in rows if r["arm"] == "treatment_tilt" and r["d"] == target.date().isoformat()), {})
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"重算至 {target.date()}", "nav": last,
            "classes": cls, "barred": list(p.barred), "stale_in_source": stale}

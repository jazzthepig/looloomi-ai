"""S-700:按时点的 ① 回放臂 `cap_pit24` → `core_variants_daily`(逐月前 24 大市值、含死币,2019 起)。

## 为什么

`registry.core_nav` 10-02 之前那一段 = 库函数 `core_alpha_daily`:**今天**的 24 个名字回填到 2015。SOL / AVAX / APT / SUI 在 2019 不存在,
EOS / XEM / BSV / LUNA / FTT 在 2019–2022 真在前 24 里、后来归零或掉出去 —— 一个都不在。幸存者名单的历史收益偏高,状态层与评估层拿它当基准。

## 规则(台账 S-700 + 两条修订;**不改 `registry.core_nav`,不改任何前向账本**)

- 库函数 `core_pit_members` / `core_pit_daily`(migrations/2026-10-30_core_pit.sql):每月第一天按上月最后一个有数的日子的市值取前 24,
  排稳定币 / 包裹凭证 / 代币化债权,选成员那天 volume/mcap ≥ 1%;权重 = 市值加权、单币 ≤ 40%、每日再平衡 —— 与 `core_alpha_daily(alpha=1)` 同一套公式。
- 每天整条重算(数据补齐在跑,成员会变),写 `core_variants_daily` 臂 `cap_pit24`;前向行(d ≥ inception = 2026-10-30)由 forward_lock 冻结。
- `code_ref = S-700 core_pit v1`。一并写一份描述表(逐年 cap_pit24 vs 幸存者 ① vs BTC)进 loop_attempt detail —— 判读交 Jazz。

## 判活

    select max(d), min(d), count(*) from core_variants_daily where arm = 'cap_pit24';   -- min 2019-01 或 2019-07(看补齐),max = 昨天
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

TABLE = "core_variants_daily"
WRITES_TABLES = (TABLE,)
ARM = "cap_pit24"
N, CAP = 24, 0.40
START = "2019-01-01"
INCEPTION = "2026-10-30"
CODE_REF = "S-700 core_pit v1"


def nav_rows(rets: pd.Series, now_iso: str) -> list[dict]:
    """纯函数。日收益 → 臂的行(nav 从 1 复利)。"""
    rets = rets.sort_index().dropna()
    nav = (1 + rets).cumprod()
    return [{"d": d.date().isoformat(), "arm": ARM, "ret": round(float(v), 8), "nav": round(float(nav[d]), 8),
             "inception": INCEPTION, "code_ref": CODE_REF, "computed_at": now_iso} for d, v in rets.items()]


def _ann(x: pd.Series) -> Optional[float]:
    x = x.dropna()
    if len(x) < 30:
        return None
    g = float((1 + x).prod())
    return round(g ** (365.0 / len(x)) - 1, 4) if g > 0 else None


def _mdd(x: pd.Series) -> Optional[float]:
    x = x.dropna()
    if len(x) < 30:
        return None
    nav = (1 + x).cumprod()
    return round(float((nav / nav.cummax() - 1).min()), 4)


def yearly_table(pit: pd.Series, survivor: pd.Series, btc: pd.Series) -> dict[str, dict[str, Any]]:
    """纯函数。逐年:三条线的年化与最大回撤(描述,不判)。"""
    out: dict[str, dict[str, Any]] = {}
    for y in sorted({d.year for d in pit.index}):
        sel = lambda s: s[(s.index.year == y)]  # noqa: E731
        out[str(y)] = {"pit": {"ann": _ann(sel(pit)), "mdd": _mdd(sel(pit)), "days": int(sel(pit).dropna().shape[0])},
                       "survivor": {"ann": _ann(sel(survivor)), "mdd": _mdd(sel(survivor))},
                       "btc": {"ann": _ann(sel(btc)), "mdd": _mdd(sel(btc))}}
    return out


async def run_once() -> dict[str, Any]:
    from src.api.store import supabase_rpc_all
    from src.data.accounting.forward_lock import write_locked
    target = (datetime.now(timezone.utc).date() - pd.Timedelta(days=1)).isoformat()
    rows = await supabase_rpc_all("core_pit_daily", {"p_start": START, "p_end": target, "p_n": N, "p_cap": CAP}, {"order": "d.asc"})
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "refused": True, "written": 0, "reason": "core_pit_daily 读不到或 0 行"}
    pit = pd.Series({pd.Timestamp(r["d"]): float(r["ret"]) for r in rows if r.get("ret") is not None}).sort_index()
    if pit.empty or not math.isfinite(float(pit.iloc[-1])):
        return {"ok": False, "refused": True, "written": 0, "reason": "core_pit_daily 没有有效收益"}
    now = datetime.now(timezone.utc).isoformat()
    out = nav_rows(pit, now)
    w = await write_locked(TABLE, out, key="arm", on_conflict="d,arm")
    if not w["ok"]:
        return {"ok": False, "refused": False, "written": w["written"], "reason": f"写入失败:{w['why']}"}
    # 描述表:对幸存者 ①(core_alpha_daily alpha=1)与 BTC
    desc: dict[str, Any] = {}
    try:
        surv_rows = await supabase_rpc_all("core_alpha_daily", {"p_start": START}, {"alpha": "eq.1", "order": "d.asc"})
        surv = pd.Series({pd.Timestamp(r["d"]): float(r["ret"]) for r in surv_rows or [] if r.get("ret") is not None
                          and float(r.get("alpha", -1)) == 1.0}).sort_index()
        from src.data.style.header import _read_all
        b = await _read_all("asset_mcap_daily", {"select": "d,price", "symbol": "eq.BTC", "d": f"gte.{START}", "order": "d.asc"})
        btc = pd.Series({pd.Timestamp(r["d"]): float(r["price"]) for r in b if r.get("price")}).sort_index().pct_change()
        desc = {"yearly": yearly_table(pit, surv, btc), "first_d": pit.index.min().date().isoformat(),
                "n_days": int(len(pit)), "top_symbol_last": rows[-1].get("top_symbol"), "n_last": rows[-1].get("n")}
    except Exception as e:                                               # noqa: BLE001 —— 描述表读不到不影响臂落表
        desc = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    return {"ok": True, "refused": False, "written": w["written"], "reason": f"cap_pit24 {pit.index.min().date()} → {target}",
            "lock": w["lock"], "desc": desc}

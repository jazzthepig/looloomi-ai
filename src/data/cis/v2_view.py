"""CIS v2 影子的对外视图(`GET /api/v1/cis/v2`)。纯函数 `build_view` + 读库 `latest_view`。

- 加密:分数、档位(影子)、各维度组内分位、状态。
- 公司:**只给状态与质量事实**(市值、26 周波动、52 周股数变化),不给分数、不给档位(Jazz 10-22:合成与之后收益反向)。
- 影子进度:加密连续多少天 ≥ 95% 有分(Jazz 10-22:满 20 天即切到 v2)。
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from src.data.cis import v2

SWITCH_AFTER_DAYS = 20
MIN_COVERAGE = 0.95


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def company_facts(raw: dict) -> dict[str, Optional[float]]:
    size, stab, sup = (_num((raw or {}).get(k)) for k in ("size", "stability", "supply"))
    return {"market_cap_usd": round(math.exp(size)) if size is not None else None,
            "volatility_26w_weekly": round(-stab, 4) if stab is not None else None,
            "share_count_change_52w": round(-sup, 4) if sup is not None else None}


def shadow_streak(days: Iterable[tuple[str, int]], universe_n: int) -> int:
    """days = [(d, 当天有分的加密名字数)],任意顺序;从最近一天往回数,连续 ≥ 95% 的天数(日期必须连续)。"""
    import datetime as dt
    by = sorted(((dt.date.fromisoformat(str(d)[:10]), n) for d, n in days), reverse=True)
    streak, prev = 0, None
    for d, n in by:
        if prev is not None and (prev - d).days != 1:
            break
        if universe_n <= 0 or n / universe_n < MIN_COVERAGE:
            break
        streak, prev = streak + 1, d
    return streak


def build_view(rows: list[dict], streak: int, universe_n: int) -> dict[str, Any]:
    from src.api.contracts.disclosure import V2_BASIS, V2_BASIS_ZH
    d = max((str(r["d"])[:10] for r in rows), default=None)
    crypto, companies = [], []
    for r in sorted(rows, key=lambda r: (-(r.get("score") or -1), r["symbol"])):
        if r["grp"] == "crypto":
            crypto.append({"symbol": r["symbol"], "score": r.get("score"), "signal": r.get("signal"),
                           "watch": r.get("watch"), "percentile": r.get("pct"), "dimensions": r.get("ranks") or {},
                           "missing": r.get("missing") or [], "state": r.get("state")})
        else:
            companies.append({"symbol": r["symbol"], "facts": company_facts(r.get("raw") or {}), "state": r.get("state")})
    companies.sort(key=lambda c: -(c["facts"]["market_cap_usd"] or 0))
    return {"d": d, "code_ref": v2.CODE_REF, "status": "shadow", "official_cis": "v1",
            "basis": V2_BASIS, "basis_zh": V2_BASIS_ZH,
            "shadow": {"crypto_consecutive_days": streak, "switch_after_days": SWITCH_AFTER_DAYS,
                       "crypto_universe": universe_n},
            "crypto": crypto, "companies": companies}


async def latest_view() -> dict[str, Any]:
    import datetime as dt
    from src.data.cis.v2_shadow import crypto_universe
    from src.data.style.header import _read_all
    last = await _read_all("cis_v2_daily", {"select": "d", "code_ref": f"eq.{v2.CODE_REF}", "order": "d.desc", "limit": "1"})
    if not last:
        return {"d": None, "status": "shadow", "crypto": [], "companies": [], "why": "v2 影子还没有任何一天"}
    d = str(last[0]["d"])[:10]
    rows = await _read_all("cis_v2_daily", {"select": "symbol,d,grp,score,ranks,raw,missing,state,pct,signal,watch",
                                            "d": f"eq.{d}", "code_ref": f"eq.{v2.CODE_REF}"})
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=45)).isoformat()
    hist = await _read_all("cis_v2_daily", {"select": "d,score", "grp": "eq.crypto", "code_ref": f"eq.{v2.CODE_REF}",
                                            "d": f"gte.{lo}", "order": "d.asc,symbol.asc"})
    counts: dict[str, int] = {}
    for h in hist:
        if h.get("score") is not None:
            counts[str(h["d"])[:10]] = counts.get(str(h["d"])[:10], 0) + 1
    n = len(crypto_universe())
    return build_view(rows, shadow_streak(counts.items(), n), n)

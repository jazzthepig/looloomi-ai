"""T-099 —— 从 Supabase 直接导出 World50 回放面板(私有,不进 git)。替代「MCP SQL → 手抄 → 校验和」那条慢路。

用法(Mac 上,环境里有 SUPABASE_URL / SUPABASE_KEY;key 不打印、不写文件):
    python3 docs/research/t099_export_panel.py ~/Projects/looloomi-private/research_data/t099_panel.json [YYYY-MM 最后一个完整月]

产出格式与 t099_build_panel.py 相同:{"months", "ret", "mcap", "cls"} ——
  ret  = 月末收盘之比 − 1(股票 / 基准 / 黄金:ohlcv_daily source=eodhd 的复权收盘;加密:asset_mcap_daily 的价格)
  mcap = 每个季末:公司 = world50_mcap_weekly(MCAP_SOURCE)季末前 14 天内最后一个周点;
         加密 = asset_mcap_daily 季末前 7 天内最后一天;黄金 = 季末金价 × 可投资存量(world50_data.metal_mcap_usd)
只读;每条序列的行数打印出来,便于和上一版面板对账。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.universe.world50 import BENCHMARKS, CANDIDATES  # noqa: E402
from src.data.universe.world50_data import MCAP_SOURCE, metal_mcap_usd  # noqa: E402

FIRST_MONTH = "2015-01"
PAGE = 1000


def _get_all(client: httpx.Client, tail: str) -> list[dict]:
    """PostgREST 一页最多 1000 行:按 offset 翻到底。"""
    out: list[dict] = []
    while True:
        r = client.get(f"/rest/v1/{tail}&limit={PAGE}&offset={len(out)}")
        if r.status_code != 200:
            raise RuntimeError(f"读 {tail.split('?')[0]} HTTP {r.status_code}: {r.text[:160]}")
        rows = r.json()
        out += rows
        if len(rows) < PAGE:
            return out


def months_until(last: str) -> list[str]:
    y, m, out = 2015, 1, []
    while f"{y}-{m:02d}" <= last:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly_returns(series: list[tuple[str, float]], months: list[str]) -> list[Optional[float]]:
    """[(日期, 收盘)] → 每月月末收盘之比 − 1;上月或本月没有收盘 ⇒ None。纯函数。"""
    last: dict[str, float] = {}
    for d, c in sorted(series):
        if c and c > 0:
            last[d[:7]] = c
    prev_month = {m: (f"{int(m[:4]) - 1}-12" if m[5:] == "01" else f"{m[:4]}-{int(m[5:]) - 1:02d}") for m in months}
    return [(last[m] / last[prev_month[m]] - 1) if m in last and prev_month[m] in last else None for m in months]


def last_on_or_before(series: list[tuple[str, float]], d: str, within_days: int) -> Optional[float]:
    best = None
    for x, v in series:
        if x <= d:
            best = (x, v)
    if best is None or (date.fromisoformat(d) - date.fromisoformat(best[0])).days > within_days:
        return None
    return best[1]


def quarter_end_date(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:])
    nxt = date(y + (mm == 12), mm % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1).isoformat()


def main(out_path: str, last_month: Optional[str] = None) -> None:
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里")
    now = datetime.now(timezone.utc).date()
    last_month = last_month or (f"{now.year - 1}-12" if now.month == 1 else f"{now.year}-{now.month - 1:02d}")
    months = months_until(last_month)
    qes = [m for m in months if m[5:] in ("03", "06", "09", "12")]
    ret: dict[str, list] = {}
    mcap: dict[str, dict[str, float]] = {m: {} for m in qes}
    cls: dict[str, str] = {}
    with httpx.Client(base_url=base, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60) as c:
        for cand in list(CANDIDATES) + list(BENCHMARKS):
            k = cand.key
            if cand.cls == "crypto":
                rows = _get_all(c, f"asset_mcap_daily?select=d,price,mcap&symbol=eq.{k}&d=gte.2014-12-01&order=d")
                px = [(r["d"], float(r["price"])) for r in rows if r.get("price")]
                caps = [(r["d"], float(r["mcap"])) for r in rows if r.get("mcap")]
                for m in qes:
                    v = last_on_or_before(caps, quarter_end_date(m), 7)
                    if v:
                        mcap[m][k] = v
            else:
                rows = _get_all(c, f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.{k}"
                                   f"&trade_date=gte.2014-12-01&order=trade_date")
                px = [(r["trade_date"], float(r["close"])) for r in rows if r.get("close")]
                if cand.cls == "equity":
                    w = _get_all(c, f"world50_mcap_weekly?select=d,mcap_usd&key=eq.{k}&source=eq.{MCAP_SOURCE}&order=d")
                    wk = [(r["d"], float(r["mcap_usd"])) for r in w]
                    for m in qes:
                        v = last_on_or_before(wk, quarter_end_date(m), 14)
                        if v:
                            mcap[m][k] = v
                elif k == "XAUUSD":
                    for m in qes:
                        p = last_on_or_before(px, quarter_end_date(m), 7)
                        v = metal_mcap_usd("XAUUSD", p) if p else None
                        if v:
                            mcap[m][k] = v
            if not px:
                print(f"  {k}: 没有价格,跳过")
                continue
            ret[k] = monthly_returns(px, months)
            cls[k] = {"crypto": "crypto", "metal": "metal", "benchmark": "benchmark"}.get(cand.cls, "equity")
            print(f"  {k}: {len(px)} 天价格,{sum(r is not None for r in ret[k])} 个月收益")
    for m in qes:          # 有市值没收益的不要(回放里排不进也持不了)
        mcap[m] = {k: v for k, v in mcap[m].items() if k in ret}
    Path(out_path).expanduser().write_text(json.dumps({"months": months, "ret": ret, "mcap": mcap, "cls": cls}))
    print(f"写好 {out_path}:{len(ret)} 条收益序列,{sum(len(v) for v in mcap.values())} 个季末市值点,截至 {last_month}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

"""World50 研究面板(日频)—— 从 Supabase 直接导,供周度 / 双周动量研究(S-584)与 T-106 共用。私有数据,不进 git。

用法(Mac 上,环境里有 SUPABASE_URL / SUPABASE_KEY;key 不打印、不写文件):
    python3 docs/research/w50_export_daily.py /Volumes/CometCloudAI/cometcloud-local/research/w50_daily

写出(都是 JSON):
  close.json   {"dates": [...交易日 UTC...], "close": {key: [收盘或 null, 与 dates 对齐]}, "cls": {key: 类别}}
               股票 / 基准 / 黄金 = ohlcv_daily source=eodhd 的复权收盘(本币,本地上市没有换汇,注明);
               加密 = asset_mcap_daily 的价格。dates = 所有序列日期的并集。
  mcap.json    {key: [[日期, 美元市值], ...]} —— 公司 = world50_mcap_weekly(当时的 MCAP_SOURCE);
               加密 = asset_mcap_daily 每周五(或之前最近一天);黄金 = 金价 × 可投资存量(world50_data.metal_mcap_usd)。
只读;每条序列的行数打印出来。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.universe.world50 import BENCHMARKS, CANDIDATES  # noqa: E402
from src.data.universe.world50_data import MCAP_SOURCE, metal_mcap_usd  # noqa: E402

START = "2014-06-01"
PAGE = 1000


def _get_all(client: httpx.Client, tail: str) -> list[dict]:
    out: list[dict] = []
    while True:
        r = client.get(f"/rest/v1/{tail}&limit={PAGE}&offset={len(out)}")
        if r.status_code != 200:
            raise RuntimeError(f"读 {tail.split('?')[0]} HTTP {r.status_code}: {r.text[:160]}")
        rows = r.json()
        out += rows
        if len(rows) < PAGE:
            return out


def main(out_dir: str) -> None:
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_KEY 不在环境里")
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    series: dict[str, dict[str, float]] = {}
    mcap: dict[str, list[list]] = {}
    cls: dict[str, str] = {}
    with httpx.Client(base_url=base, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60) as c:
        for cand in list(CANDIDATES) + list(BENCHMARKS):
            k = cand.key
            if cand.cls == "crypto":
                rows = _get_all(c, f"asset_mcap_daily?select=d,price,mcap&symbol=eq.{k}&d=gte.{START}&order=d")
                px = {r["d"]: float(r["price"]) for r in rows if r.get("price")}
                mcap[k] = [[r["d"], float(r["mcap"])] for r in rows
                           if r.get("mcap") and date.fromisoformat(r["d"]).weekday() == 4]
            else:
                rows = _get_all(c, f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.{k}"
                                   f"&trade_date=gte.{START}&order=trade_date")
                px = {r["trade_date"]: float(r["close"]) for r in rows if r.get("close")}
                if cand.cls == "equity":
                    w = _get_all(c, f"world50_mcap_weekly?select=d,mcap_usd&key=eq.{k}&source=eq.{MCAP_SOURCE}&order=d")
                    if w:
                        mcap[k] = [[r["d"], float(r["mcap_usd"])] for r in w]
                elif k == "XAUUSD":
                    mcap[k] = [[d, metal_mcap_usd("XAUUSD", p)] for d, p in sorted(px.items())
                               if date.fromisoformat(d).weekday() == 4 and metal_mcap_usd("XAUUSD", p)]
            if not px:
                print(f"  {k}: 没有价格")
                continue
            series[k] = px
            cls[k] = {"crypto": "crypto", "metal": "metal", "benchmark": "benchmark"}.get(cand.cls, "equity")
            print(f"  {k}: {len(px)} 天价格,{len(mcap.get(k, []))} 个市值点")
    dates = sorted({d for s in series.values() for d in s})
    close = {k: [s.get(d) for d in dates] for k, s in series.items()}
    (out / "close.json").write_text(json.dumps({"dates": dates, "close": close, "cls": cls}))
    (out / "mcap.json").write_text(json.dumps(mcap))
    print(f"写好 {out}:{len(series)} 条价格序列 × {len(dates)} 天,{len(mcap)} 条市值序列")


if __name__ == "__main__":
    main(sys.argv[1])

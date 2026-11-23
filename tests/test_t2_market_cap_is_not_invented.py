"""S-906(2026-11-23):盘中引擎在 CoinGecko 取不到时把市值编成「成交额 × 20」,公开接口上挂了四天。

实测:`/api/v1/cis/universe` 里 ETH 的 `market_cap` = 77 亿(真实约 2,100 亿),每个加密名字的量 / 市值恰好都是 5%。
那是为个别改名币写的兜底;CG 一停,它成了全体加密名字的市值来源(硬规则 9:生产路径不放编的数,宁缺勿造)。
现在:价 × 本库最近一份流通量;没有快照 ⇒ 0(这套代码里 0 = 缺)。
"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.cis import cg_less_fallback as fb  # noqa: E402


def _universe_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse((ROOT / "src/data/cis/cis_provider.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "calculate_cis_universe")


def test_no_market_cap_is_derived_from_volume_anymore() -> None:
    """那个函数里:任何「含 volume 的名字 × 常数」的乘法,都不许出现在给 market_cap 赋值的语句里。"""
    fn = _universe_fn()
    bad = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        tgt = ast.unparse(node.targets[0])
        if "market_cap" not in tgt and tgt not in ("cg_mc",):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mult):
                names = {n.id for n in ast.walk(sub) if isinstance(n, ast.Name)}
                consts = [n for n in ast.walk(sub) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))]
                if any("vol" in x.lower() for x in names) and consts:
                    bad.append(f"第 {node.lineno} 行:{ast.unparse(node)[:90]}")
    assert not bad, f"市值又在从成交额乘常数推出来:{bad}"
    src = ast.unparse(fn)
    assert "mcap_from_supply(" in src and "latest_supply(" in src, "取不到 CG 市值时要走「价 × 本库流通量」"


def test_the_detector_sees_the_old_line() -> None:
    old = ast.parse("async def calculate_cis_universe():\n    rec = {}\n    volume = 1.0\n    rec['market_cap'] = volume * 20\n")
    fn = old.body[0]
    hit = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and "market_cap" in ast.unparse(n.targets[0])
           and any(isinstance(s, ast.BinOp) and isinstance(s.op, ast.Mult) for s in ast.walk(n.value))]
    assert hit, "探测器认不出原来那一行就等于没查"


def test_mcap_from_supply_is_price_times_circulating_or_nothing() -> None:
    assert fb.mcap_from_supply(1724.33, {"circ": 122_237_000.0, "total": None, "d": "2026-11-20"}) == 1724.33 * 122_237_000.0
    for price, snap in ((None, {"circ": 1.0}), (0, {"circ": 1.0}), (10.0, None), (10.0, {}), (10.0, {"circ": 0}),
                        (10.0, {"circ": None}), (float("nan"), {"circ": 1.0})):
        assert fb.mcap_from_supply(price, snap) is None, (price, snap)


def test_latest_supply_takes_the_newest_snapshot_and_skips_names_without_one(monkeypatch) -> None:
    import src.data.style.header as hd
    seen = {}

    async def read_all(table, params):
        seen.update({"table": table, **params})
        return [{"coin_id": "bitcoin", "d": "2026-11-18", "circulating_supply": 19_990_000, "total_supply": 19_990_000},
                {"coin_id": "bitcoin", "d": "2026-11-20", "circulating_supply": 20_114_000, "total_supply": 20_114_000},
                {"coin_id": "ethereum", "d": "2026-11-20", "circulating_supply": None, "total_supply": 1.0},
                {"coin_id": "solana", "d": "2026-11-20", "circulating_supply": 0, "total_supply": 1.0}]
    monkeypatch.setattr(hd, "_read_all", read_all)
    out = asyncio.run(fb.latest_supply({"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "HYPE": "hyperliquid"},
                                       today=dt.date(2026, 11, 23)))
    assert out == {"BTC": {"circ": 20_114_000.0, "total": 20_114_000.0, "d": "2026-11-20"}}, "流通量缺 / 为 0 的不算有快照"
    assert seen["table"] == "coin_supply_daily" and seen["d"] == "gte.2026-10-09", "只看最近 45 天 —— 更旧的流通量不拿来算今天的市值"
    assert asyncio.run(fb.latest_supply({}, today=dt.date(2026, 11, 23))) == {}

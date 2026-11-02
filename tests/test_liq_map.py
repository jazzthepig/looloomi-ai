"""T-221 强平地图:每个地址只取最近一次快照、按强平价距离分档、不送地址、对永续深度的倍数。"""
import datetime as dt
import gzip
import json

import pytest

from src.data.market import liq_map as lm
from src.exec_host import liqmap

NOW_MS = 1_762_070_400_000


def _p(addr, coin, szi, liq, ts=NOW_MS - 60_000):
    return {"ts": ts, "address": addr, "coin": coin, "szi": szi, "liquidationPx": liq, "entryPx": 1.0}


def test_latest_round_per_address_and_bands():
    recs = [_p("a", "BTC", 1.0, 95_000, ts=NOW_MS - 20 * 60_000),          # 旧一轮
            _p("a", "BTC", 2.0, 98_500), _p("a", "ETH", -10.0, 2_100),     # 最近一轮
            _p("b", "BTC", 0.5, None), _p("c", "BTC", 1.0, 50_000),
            _p("d", "BTC", 1.0, 99_000, ts=NOW_MS - 3 * 3600_000)]         # 太旧,不算
    pos = liqmap.latest_positions(recs, NOW_MS)
    assert sorted((p["address"], p["coin"]) for p in pos) == [("a", "BTC"), ("a", "ETH"), ("b", "BTC"), ("c", "BTC")]
    rows = liqmap.buckets(pos, {"BTC": 100_000.0, "ETH": 2_000.0})
    by = {(r["coin"], r["side"], r["band_lo"]): r for r in rows}
    assert by[("BTC", "long", 0.0)]["notional_usd"] == 200_000.0, "强平价 98.5k 离 100k 2% 以内"
    assert by[("ETH", "short", 0.05)]["notional_usd"] == 20_000.0, "空头强平价在上方 5% 处"
    assert by[("BTC", "long", None)]["n_positions"] == 1, "没有强平价的单列"
    assert ("BTC", "long", 0.5) not in by, "离现价 50% 的不算近处风险"
    assert all("address" not in r for r in rows)


def test_shock_table_against_perp_depth():
    rows = [{"coin": "BTC", "side": "long", "band_lo": 0.0, "notional_usd": 2e6}, {"coin": "BTC", "side": "long", "band_lo": 0.05, "notional_usd": 6e6},
            {"coin": "BTC", "side": "short", "band_lo": 0.10, "notional_usd": 1e6}, {"coin": "BTC", "side": "long", "band_lo": None, "notional_usd": 9e9}]
    t = {(r["coin"], r["shock"]): r for r in liqmap.shock_table(rows, {"BTC": {"bid": 4e6, "ask": 5e6}})}
    assert t[("BTC", 0.05)]["forced_sell_usd"] == 2e6 and t[("BTC", 0.10)]["forced_sell_usd"] == 8e6
    assert t[("BTC", 0.10)]["sell_vs_bid_depth"] == 2.0 and t[("BTC", 0.15)]["forced_buy_usd"] == 1e6


def test_railway_side_rejects_addresses_and_buckets_by_hour():
    good = [{"coin": "BTC", "side": "long", "band_lo": 0.0, "band_hi": 0.02, "notional_usd": 1.0, "n_positions": 1, "mark": 1.0},
            {"coin": "BTC", "side": "long", "band_lo": None, "band_hi": None, "notional_usd": 2.0, "n_positions": 1}]
    out, bad = lm.clean(good, "2026-11-02T09:37:00+00:00")
    assert bad == [] and out[0]["ts"].startswith("2026-11-02T09:00") and [r["band"] for r in out] == ["0-2", "none"]
    _, bad = lm.clean([{**good[0], "address": "0xabc"}], "2026-11-02T09:00:00Z")
    assert bad and "地址" in bad[0]


def test_host_ships_the_map_through_the_outbox(tmp_path, monkeypatch):
    import src.exec_host.whales as wh
    from src.api.routers import executor as api
    from src.exec_host import runner as rn
    from tests.test_exec_host import MASTER, FakeRailway, _outbox, _plan
    now = dt.datetime.fromtimestamp(NOW_MS / 1000, dt.timezone.utc)
    rec = tmp_path / "whales"
    rec.mkdir()
    with gzip.open(rec / f"{now.date().isoformat()}.jsonl.gz", "wt") as f:
        for r in (_p("a", "BTC", 2.0, 98_000), _p("b", "ETH", -10.0, 2_100)):
            f.write(json.dumps(r) + "\n")
    monkeypatch.setattr(wh, "DEFAULT_REC_DIR", rec)
    monkeypatch.setattr(rn.time, "time", lambda: NOW_MS / 1000)

    class V:
        def perp_mids(self):
            return {"BTC": 100_000.0, "ETH": 2_000.0}
    cfg = rn.Config({"EXECUTOR_MODE": "dry_run", "HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t",
                     "EXECUTOR_STATE_DIR": str(tmp_path / "st")})
    e = rn.Executor(cfg, V(), FakeRailway(_plan()), clock=lambda: now)
    sent = e.ship_liq_map(now)
    assert sent and sent["kind"] == "liqmap" and sent["detail"]["n_accounts"] == 2
    rep = _outbox(e)[-1]
    assert api.vet_report(rep)[1] == [] and "address" not in json.dumps(rep["detail"]["rows"])

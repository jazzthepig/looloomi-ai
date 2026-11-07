"""散户投机手续费写端(11-07):只取那三类、按累计费用排、今天那一格不落。"""
import datetime as dt

from src.data.market import degen_activity as g


def test_pick_keeps_only_retail_categories_by_all_time_fees():
    ps = [{"slug": "pump.fun", "name": "pump.fun", "category": "Launchpad", "totalAllTime": 10},
          {"slug": "uniswap", "name": "Uniswap", "category": "Dexs", "totalAllTime": 99},
          {"slug": "trojan", "name": "Trojan", "category": "Telegram Bot", "totalAllTime": 3},
          {"slug": "axiom", "name": "Axiom", "category": "Trading App", "totalAllTime": 7}]
    assert [p["slug"] for p in g.pick(ps, 2)] == ["pump.fun", "axiom"]


def test_rows_drop_today_and_bad_values():
    p = {"slug": "pump.fun", "name": "pump.fun", "category": "Launchpad"}
    t = lambda s: int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp())
    chart = [[t("2026-11-05"), 100], [t("2026-11-06"), -1], [t("2026-11-07"), 5], ["x", 1]]
    out = g.rows(p, chart, dt.date(2026, 11, 7))
    assert [(r["d"], r["fees_usd"]) for r in out] == [("2026-11-05", 100.0)]

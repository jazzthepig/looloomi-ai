"""S-700:按时点的 ① 回放臂 `cap_pit24` 与它的数据补齐。
钉住:补齐的映射必须核价(重叠不足 / 中位差过大 ⇒ 不写)、不在 binance_hist 的名字核 CoinGecko 回声 symbol(含改名别名)、
进度按版本记、臂的行从 1 复利、描述表只描述;迁移文件里排除名单与流动性地板存在。"""
import pathlib

import pandas as pd
import pytest

from src.data.market import mcap_deepen as md
from src.data.signals import core_pit as cp

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_price_gap_and_verdict_refuse_thin_overlap_and_wrong_mappings():
    cg = [{"d": f"2019-01-{i:02d}", "price": 100.0 * (1 + 0.001 * i)} for i in range(1, 32)]
    close_ok = {r["d"]: r["price"] * 1.01 for r in cg}                      # 差 1%
    g = md.price_gap(cg, close_ok)
    assert g["overlap"] == 31 and g["median_gap"] == pytest.approx(0.0099, abs=1e-3)
    assert md.verdict_for(g)[0] is True
    g2 = md.price_gap(cg, {k: v for k, v in list(close_ok.items())[:10]})
    assert md.verdict_for(g2) == (False, "重叠日 10 < 30,核不了价,不写")
    g3 = md.price_gap(cg, {r["d"]: r["price"] * 937.0 for r in cg})         # HYPE→Hyperlane 那种
    ok, why = md.verdict_for(g3)
    assert ok is False and "映射可疑" in why
    assert md.price_gap(cg, {}) == {"overlap": 0, "median_gap": None}


def test_symbol_echo_accepts_renames_and_rejects_other_coins():
    assert md.symbol_echo_ok("EOS", "eos") and md.symbol_echo_ok("LUNC", "lunc") and md.symbol_echo_ok("LUNC", "luna")
    assert md.symbol_echo_ok("NANO", "xno") and md.symbol_echo_ok("BTTOLD", "bttold")
    assert md.symbol_echo_ok("OM", "mantra") is False
    assert md.symbol_echo_ok("OM", "om") and not md.symbol_echo_ok("OM", "omfan") and not md.symbol_echo_ok("EOS", None)


def test_dead_names_have_coingecko_ids_and_cutoffs_are_before_successors():
    for sym, spec in md.DEAD_NAMES.items():
        assert spec["cg"] and spec["note"], sym
    assert md.WRITE_BEFORE["DYDX"] == "2023-10-30", "旧 dydx 让位给 dydx-chain(cg_coin_map 的那一条)"
    assert md.WRITE_BEFORE["KNCOLD"] < "2021-04-21" or md.WRITE_BEFORE["KNCOLD"] == "2021-04-21"
    assert md.DEAD_NAMES["OM"]["cg"] == "mantra-dao", "cg_coin_map 把 OM 映成了马赛球迷币"
    assert md.DEAD_NAMES["LUNC"]["cg"] == "terra-luna" and md.DEAD_NAMES["LUNA"]["cg"] == "terra-luna-2"


def test_progress_is_per_version():
    rows = [{"detail": {"v": 1, "done": {"new:EOS": "ok", "ext:BTC": "error"}}},
            {"detail": {"v": 0, "done": {"new:EOS": "error"}}},
            {"detail": {"v": 1, "done": {"ext:BTC": "ok"}}}]
    assert md.done_from(rows) == {"new:EOS": "ok", "ext:BTC": "error"}, "同一名字以最新一轮为准;旧版本不算"


def test_arm_rows_compound_from_one_and_carry_inception():
    rets = pd.Series([0.1, -0.05, 0.02], index=pd.to_datetime(["2019-01-02", "2019-01-03", "2019-01-04"]))
    rows = cp.nav_rows(rets, "now")
    assert [r["nav"] for r in rows] == [pytest.approx(1.1), pytest.approx(1.045), pytest.approx(1.0659)]
    assert {r["arm"] for r in rows} == {"cap_pit24"} and rows[0]["inception"] == "2026-10-30" and rows[0]["code_ref"] == cp.CODE_REF


def test_yearly_table_describes_without_judging():
    idx = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    pit = pd.Series(0.001, index=idx)
    surv = pd.Series(0.002, index=idx)
    btc = pd.Series(0.0, index=idx)
    t = cp.yearly_table(pit, surv, btc)
    assert set(t) == {"2020", "2021"} and t["2020"]["pit"]["ann"] < t["2020"]["survivor"]["ann"]
    assert t["2021"]["btc"]["ann"] == 0.0 and t["2021"]["pit"]["mdd"] == 0.0 and t["2020"]["pit"]["days"] == 366
    assert not any(k in str(t).lower() for k in ("buy", "sell", "verdict", "pass", "fail"))


def test_migration_pins_exclusions_and_liquidity_floor():
    sql = (ROOT / "migrations" / "2026-10-30_core_pit.sql").read_text(encoding="utf-8")
    for s in ("'USDT'", "'WBTC'", "'STETH'", "'FIGR_HELOC'", "core_pit_min_turnover", "a.volume / a.mcap >= core_pit_min_turnover()"):
        assert s in sql, s
    assert "p_cap" in sql and "greatest(w0 - p_cap, 0)" in sql, "单币上限与 core_alpha_daily 同一套公式"
    assert "ex as (select cw.d" not in sql, "上限的再分配用窗口函数,不自连接(自连接在 8 年上要几分钟)"

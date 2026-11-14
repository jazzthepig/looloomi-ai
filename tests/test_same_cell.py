"""今天这一格的历史(src/data/state/same_cell.py,S-864 / T-369 ⑫):只描述;数字旁边永远带段数与对照的 p。"""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import same_cell as sc            # noqa: E402


def _research():
    sp = importlib.util.spec_from_file_location("s864", ROOT / "docs/research/s864_same_cell.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_the_production_cells_are_the_research_cells():
    """研究脚本(A 道跑出 S-864 那张表的那一份)与生产模块是同一套定义 —— 在合成数据上逐日对格子,再对今天这一格的每个数。"""
    R = _research()
    days, close, dist, taker, stable, y_d, y_v = R.S.synthetic()
    mine = sc.cells(days, close, dist, stable, y_d, y_v)
    theirs = R.cells(days, close, dist, stable, y_d, y_v)
    assert mine == theirs and len(mine) > 2000
    s = sc.summary(days, close, dist, stable, y_d, y_v)
    out = R.run(days, close, dist, taker, stable, y_d, y_v)
    assert s["status"] == "ok" and s["cell"] == out["today_cell"] and s["asof"] == out["asof"]
    row = out["today_cell_row"]
    assert s["n_episodes"] == row["n_episodes"] and s["d30"] == row["d30"] and s["d30_by_episode_start"] == row["d30_by_episode_start"]
    assert s["uncond_d30"] == out["unconditional"]["d30"]
    assert s["p_shift_mean"] == out["control_today_cell"]["mean_30d"]["p_two_sided"]
    assert s["p_shift_down"] == out["control_today_cell"]["p_down_big_30d"]["p_two_sided"]


def test_a_cell_never_looks_ahead():
    R = _research()
    days, close, dist, taker, stable, y_d, y_v = R.S.synthetic()
    full = sc.cells(days, close, dist, stable, y_d, y_v)
    cut = days[len(days) // 2]
    half = sc.cells([d for d in days if d <= cut], {d: v for d, v in close.items() if d <= cut}, dist, stable, y_d, y_v)
    assert half and all(full[d] == half[d] for d in half), "截断到某一天之前的数据,那天之前的格子不许变"


def test_too_few_episodes_gives_no_numbers_and_unreadable_says_so():
    days = [dt.date(2019, 1, 1) + dt.timedelta(days=i) for i in range(900)]
    close = {d: 100.0 + i * 0.01 for i, d in enumerate(days)}
    flat = {d: 0.01 for d in days}
    s = sc.summary(days, close, flat, flat, days, [3.0 + i * 0.001 for i in range(900)])
    assert s["status"] == "thin" and s["n_episodes"] < sc.MIN_EPISODES and "d30" not in s, "一格只有一两段时给出中位数,就是拿一次历史当规律"
    assert "样本不足" in sc.line(s) and "%" not in sc.line(s)
    u = sc.summary(days, close, {}, {}, [], [])
    assert u["status"] == "unreadable" and "读不到" in sc.line(u)
    assert sc.line(None) is None


def test_the_line_always_carries_episodes_and_the_control():
    s = {"status": "ok", "cell_words": "利率升·稳定币抽·周线坏·线下", "n_episodes": 12, "n_days": 257, "separable": False, "p_shift_mean": 0.1485,
         "d30": {"median": 0.003, "p_down_big": 0.28, "p_up_big": 0.14}, "uncond_d30": {"p_down_big": 0.202, "p_up_big": 0.318}}
    t = sc.line(s)
    assert "12 段 / 257 天" in t and "中位 +0.3%" in t and "跌超 10% 28%" in t and "涨超 10% 14%" in t and "全样本 20% / 32%" in t
    assert "与随机平移分不开" in t and "p 0.1485" in t and "不是预测" in t
    assert "分得开" in sc.line({**s, "separable": True, "p_shift_mean": 0.01})


def test_two_p_definitions_are_both_reported_and_both_must_pass():
    """S-866:B 道独立选的双侧 p(两倍较小的单尾)与登记的那一种(离平移均值的距离)在 BTC 上是 0.08 对 0.15 ——
    落在 0.10 的两边。只报一个就是在挑;「分得开」要两个都过线。"""
    R = _research()
    days, close, dist, taker, stable, y_d, y_v = R.S.synthetic()
    s = sc.summary(days, close, dist, stable, y_d, y_v)
    assert s["p_shift_mean"] is not None and s["p_shift_mean_tail2"] is not None and s["p_line"] == sc.P_LINE == 0.05
    assert s["separable"] == (max(s["p_shift_mean"], s["p_shift_mean_tail2"]) < sc.P_LINE)
    base = {"status": "ok", "cell_words": "x", "n_episodes": 12, "n_days": 257, "separable": False, "p_shift_mean": 0.1485, "p_shift_mean_tail2": 0.082,
            "d30": {"median": 0.003, "p_down_big": 0.28, "p_up_big": 0.14}, "uncond_d30": {"p_down_big": 0.202, "p_up_big": 0.318}}
    assert "p 0.1485 / 0.082" in sc.line(base) and "分不开" in sc.line(base)


def test_other_assets_ride_the_same_cells_with_their_own_control():
    """S-866 ②:格子不变,只把之后 30 天换成另一只资产的收盘。同一条收盘换个名字 ⇒ 数字必须与 BTC 那一栏一字不差。"""
    R = _research()
    days, close, dist, taker, stable, y_d, y_v = R.S.synthetic()
    late = {d: v * 2 for d, v in close.items() if d >= days[900]}            # 历史短一截的资产(像 SOL)
    s = sc.summary(days, close, dist, stable, y_d, y_v, {"TWIN": dict(close), "LATE": late, "GONE": {}})
    o = s["others"]
    assert o["TWIN"]["status"] == "ok" and o["TWIN"]["d30"] == s["d30"] and o["TWIN"]["uncond_d30"] == s["uncond_d30"]
    assert o["TWIN"]["p_shift_mean"] == s["p_shift_mean"] and o["TWIN"]["n_episodes"] == s["n_episodes"]
    assert o["LATE"]["status"] in ("ok", "thin") and o["LATE"]["n_days"] <= s["n_days"]
    if o["LATE"]["status"] == "ok":
        assert o["LATE"]["uncond_d30"]["n_days"] < s["uncond_d30"]["n_days"], "历史短的资产,全样本也只能用它自己有的那些天"
    assert o["GONE"] == {"status": "unreadable"}
    t = sc.line(s)
    assert "TWIN 中位" in t and "GONE 读不到" in t and t.endswith("只描述,不是预测")
    assert "others" not in sc.summary(days, close, dist, stable, y_d, y_v), "没传别的资产 ⇒ 这一栏不出现(不是空壳)"


def test_it_is_wired_into_the_dossier_and_not_into_any_rule():
    dc = (ROOT / "src/data/execution/dossier_context.py").read_text(encoding="utf-8")
    assert "same_cell" in dc and "read_and_summarise" in dc and "same_cell.line" in dc
    assert sc.OTHERS == ("ETH", "SOL") and "for sym in OTHERS" in (ROOT / "src/data/state/same_cell.py").read_text(encoding="utf-8")
    for path in ("src/data/execution/exposure_decision.py", "src/data/execution/executor.py", "src/data/execution/host_plan.py"):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert "same_cell" not in src, f"{path} 读了同格历史 —— 这一栏只描述,不进敞口、不进计划(S-864 的后果第 ④ 条)"
    from src.data.execution import agent_judgment as aj
    assert aj.dossier_version({"context": {"checklists": {}, "same_cell": {"status": "ok"}}}) == "v5"
    assert aj.dossier_version({"context": {"checklists": {}}}) == "v4"

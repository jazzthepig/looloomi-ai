"""S-774 前向记录(11-07):充分统计量解出的 Ridge 与 sklearn 一致;百分位与周一的取法。"""
import numpy as np

from src.data.state import asset_flow_forecast as af


def _stats(X, y):
    up = [float(X[:, i] @ X[:, j]) for i in range(11) for j in range(i, 11)]
    return {"n": len(y), "sx": X.sum(0).tolist(), "sy": float(y.sum()), "sxy": (X.T @ y).tolist(), "sxx_upper": up}


def test_ridge_from_sufficient_statistics_matches_centered_closed_form_and_sklearn():
    rng = np.random.default_rng(774)
    X = rng.uniform(-1, 1, (5000, 11))
    y = X @ rng.normal(0, 0.05, 11) + 0.01 + rng.normal(0, 0.2, 5000)
    b0, beta = af.ridge_from_stats(_stats(X, y), alpha=10.0)
    Xc, yc = X - X.mean(0), y - y.mean()
    want = np.linalg.solve(Xc.T @ Xc + 10.0 * np.eye(11), Xc.T @ yc)
    assert np.allclose(beta, want, atol=1e-9) and abs(b0 - (y.mean() - X.mean(0) @ want)) < 1e-9
    try:
        from sklearn.linear_model import Ridge
    except ImportError:
        return
    m = Ridge(alpha=10.0).fit(X, y)
    assert np.allclose(beta, m.coef_, atol=1e-8) and abs(b0 - m.intercept_) < 1e-8


def test_forecast_rows_rank_and_monday():
    beta = np.zeros(11); beta[0] = 1.0
    rows = [{"symbol": "A", "vec": "[" + ",".join(["0.5"] + ["0"] * 10) + "]"},
            {"symbol": "B", "vec": [-0.5] + [0.0] * 10}, {"symbol": "C", "vec": None}]
    out = af.forecast_rows(rows, 0.0, beta, "2026-11-09", 1000)
    assert [(r["symbol"], r["pct"]) for r in out] == [("A", 1.0), ("B", 0.0)]


def test_mondays_due_walks_the_calendar_not_the_last_rows():
    """S-922:之前取「最新 8 行里的周一」,而每天 35 个币 ⇒ 8 行全是同一天,周一永远找不到(上线 19 天 0 行)。"""
    # 最新一天是周三 11-25:前向起点 11-09 之后的周一 = 11-09 / 11-16 / 11-23
    assert af.mondays_due("2026-11-25", set()) == ["2026-11-09", "2026-11-16", "2026-11-23"]
    assert af.mondays_due("2026-11-25", {"2026-11-09", "2026-11-23"}) == ["2026-11-16"]
    assert af.mondays_due("2026-11-23", set())[-1] == "2026-11-23"       # 最新一天本身是周一
    assert af.mondays_due("2026-11-22", set()) == ["2026-11-09", "2026-11-16"]
    assert af.mondays_due("2026-11-08", set()) == [] and af.mondays_due(None, set()) == []
    # 起点不是周一时,从它之后的第一个周一算
    import datetime as dt
    assert af.mondays_due("2026-11-25", set(), start=dt.date(2026, 11, 10)) == ["2026-11-16", "2026-11-23"]


def test_late_writes_are_marked_in_code_ref():
    import datetime as dt
    tue = dt.datetime(2026, 11, 24, 3, tzinfo=dt.timezone.utc)
    assert af.code_ref_for("2026-11-23", tue) == af.CODE_REF
    assert af.code_ref_for("2026-11-23", tue + dt.timedelta(days=1)) == af.CODE_REF        # 周一 + 2 天内算按时
    late = af.code_ref_for("2026-11-09", dt.datetime(2026, 11, 26, 9, tzinfo=dt.timezone.utc))
    assert late.startswith(af.CODE_REF) and "late-written 2026-11-26" in late
    beta = np.zeros(11)
    rows = af.forecast_rows([{"symbol": "A", "vec": [0.0] * 11}], 0.0, beta, "2026-11-09", 10, late)
    assert rows[0]["code_ref"] == late


def test_the_ridge_rpc_gets_its_own_timeout_and_the_result_reaches_the_loop():
    """训练统计 ~17 s;共用客户端 10 s 会超时并给熔断器记失败。预测结果要单独落一条循环痕迹。"""
    import inspect
    from pathlib import Path
    src = inspect.getsource(af._forecast_one)
    assert "timeout=RIDGE_TIMEOUT_S" in src and af.RIDGE_TIMEOUT_S > 30
    main = Path(__file__).resolve().parents[1].joinpath("src/api/main.py").read_text(encoding="utf-8")
    assert '_iteration_result("_asset_flow_forecast"' in main and af.LOOP_NAME == "_asset_flow_forecast"
    from src.data.state import asset_flow, feature_matrix
    assert "_with_forecast(out, now)" in inspect.getsource(asset_flow.refresh).split("needs_refresh(vmax, smax)")[1].split("supabase_rpc_write")[0], \
        "视图不刷的那一轮也要跑预测(补写上一轮没写成的周一)"
    assert '"forecast"' in inspect.getsource(feature_matrix.run_once)

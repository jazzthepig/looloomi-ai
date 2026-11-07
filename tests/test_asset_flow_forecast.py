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
    assert af.latest_monday(["2026-11-10", "2026-11-09", "2026-11-02"]) == "2026-11-09"

"""S-599 —— 季节性留出段(预注册见 REFUTATION_LEDGER §S-599):T-118 发现段前三名在 2021-01 → 2026-09 只读一次。

用法:python3 docs/research/s599_seasonality_holdout.py <w50_daily/close.json> <crypto_daily 目录> [输出 json]
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import block_permute, percentile_of  # noqa: E402
from src.data.evaluation.rr_matrix import FOMC_DECISION_DATES  # noqa: E402

LO, HI = "2021-01-01", "2026-09-30"
FOMC_2021 = ["2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15"]
FOMC = set(FOMC_2021) | {d.isoformat() for d in FOMC_DECISION_DATES}
TESTS = (("fomc_week", +1), ("month_02", +1), ("month_09", -1))


def masks(days: list[date]) -> dict[str, np.ndarray]:
    fomc = np.array([any((d + timedelta(days=o)).isoformat() in FOMC for o in range(7)) for d in days])
    return {"fomc_week": fomc, "month_02": np.array([d.month == 2 for d in days]), "month_09": np.array([d.month == 9 for d in days])}


def test(ret: np.ndarray, mask: np.ndarray, sign: int, seed: int) -> dict:
    ok = np.isfinite(ret)
    r, m = ret[ok], mask[ok]
    diff = float(r[m].mean() - r[~m].mean())
    rng = np.random.default_rng(seed)
    lab = m.astype(int)
    null = []
    for _ in range(1000):
        p = block_permute(lab, 10, rng)
        null.append(r[p == 1].mean() - r[p == 0].mean())
    pct = percentile_of(diff, null)
    one_sided = pct if sign > 0 else 1 - pct
    return {"diff_log_per_day": diff, "n_in": int(m.sum()), "n_out": int((~m).sum()), "pct": pct,
            "same_sign": bool(np.sign(diff) == sign), "passes": bool(np.sign(diff) == sign and one_sided >= 0.95),
            "passes_bonferroni": bool(np.sign(diff) == sign and one_sided >= 1 - 0.05 / 3)}


def series(dates: list[str], vals: list) -> tuple[list[date], np.ndarray]:
    pts = [(d, v) for d, v in zip(dates, vals) if v and LO <= d <= HI]
    ds = [date.fromisoformat(d) for d, _ in pts]
    px = np.array([v for _, v in pts], dtype=float)
    ret = np.full(len(px), np.nan)
    ret[1:] = np.log(px[1:] / px[:-1])
    gaps = np.array([0] + [(ds[i] - ds[i - 1]).days for i in range(1, len(ds))])
    ret[gaps > 1] = np.nan                  # 跨缺口的收益不算
    return ds, ret


def main(close_path: str, out_path: str | None = None) -> dict:
    c = json.loads(Path(close_path).read_text())
    res = {}
    for asset in ("ETH", "BTC"):
        ds, ret = series(c["dates"], c["close"][asset])
        mk = masks(ds)
        res[asset] = {name: test(ret, mk[name], sign, 599 + i) for i, (name, sign) in enumerate(TESTS)}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    for a, v in r.items():
        for k, x in v.items():
            print(a, k, f"diff {x['diff_log_per_day']*100:+.3f}pp/day n_in {x['n_in']} pct {x['pct']:.3f} same_sign {x['same_sign']} PASS {x['passes']} bonf {x['passes_bonferroni']}")

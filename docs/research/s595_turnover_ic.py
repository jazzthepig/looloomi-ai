"""S-595 判定:读 s595_turnover.sql 按年导出的周 IC(csv,数据根 research/s595/20YY.csv),平稳块自助(平均块 8 周,2,000 次)。

用法:python3 docs/research/s595_turnover_ic.py /Volumes/CometCloudAI/cometcloud-local/research/s595
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.evaluation.apparatus import stationary_bootstrap_index  # noqa: E402


def load(dir_: str) -> dict[str, np.ndarray]:
    rows = []
    for f in sorted(glob.glob(f"{dir_}/20*.csv")):
        for r in Path(f).read_text().strip().split(";"):
            p = r.split(",")
            rows.append((p[0], int(p[1]), *[float(x) if x else np.nan for x in p[2:]]))
    rows.sort()
    cols = ("d", "n", "ic_turn", "ic_jump", "rho_combo", "ic_turn_hiq", "ic_turn_loq")
    return {c: np.array([r[i] for r in rows]) for i, c in enumerate(cols)}


def one_sided_p_below_zero(x: np.ndarray, seed: int = 595) -> tuple[float, float]:
    x = x[np.isfinite(x)]
    idx = stationary_bootstrap_index(len(x), 8.0, 2000, np.random.default_rng(seed))
    bm = x[idx].mean(axis=1)
    return float(x.mean()), float((bm >= 0).mean())


if __name__ == "__main__":
    w = load(sys.argv[1])
    for k in ("ic_turn", "ic_jump"):
        m, p = one_sided_p_below_zero(w[k])
        print(f"{k}: mean {m:+.4f}, one-sided p(mean < 0) = {p:.4f}, weeks = {len(w[k])}")
    first = w["d"] < "2023-01-01"
    print("halves turn / jump:", np.nanmean(w["ic_turn"][first]), np.nanmean(w["ic_turn"][~first]),
          np.nanmean(w["ic_jump"][first]), np.nanmean(w["ic_jump"][~first]))
    print("rho(turn28, quality) mean:", np.nanmean(w["rho_combo"]),
          "| turn28 IC high / low quality half:", np.nanmean(w["ic_turn_hiq"]), np.nanmean(w["ic_turn_loq"]))

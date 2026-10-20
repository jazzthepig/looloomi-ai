"""S-628 判据:K 快鱼率 > N 快鱼率,周内打乱 K / N 标签 2,000 次,单侧 p < 0.05(台账预注册)。

周内打乱 ⇔ 每周 K 里的快鱼数 ~ 超几何(宇宙 n、快鱼 f、抽 k)。统计量 = 全期 K 快鱼数(每周 k 固定,
它与「K 率 − N 率」单调同向)。抽 2,000 次给预注册的 p;另给精确 p(逐周卷积)只报。
输入:s628_social_k_arm.sql 的输出存成 JSON(每行 n_univ / n_fish / n_k / k_fish)。
"""
from __future__ import annotations

import json
import random
import sys
from math import comb


def hyper_pmf(n: int, f: int, k: int) -> list[float]:
    tot = comb(n, k)
    return [comb(f, x) * comb(n - f, k - x) / tot if 0 <= k - x <= n - f else 0.0 for x in range(0, min(f, k) + 1)]


def exact_p(weeks: list[dict], key_k: str = "n_k", key_kf: str = "k_fish") -> float:
    dist = [1.0]
    for w in weeks:
        pmf = hyper_pmf(w["n_univ"], w["n_fish"], w[key_k])
        new = [0.0] * (len(dist) + len(pmf) - 1)
        for i, a in enumerate(dist):
            if a:
                for j, b in enumerate(pmf):
                    new[i + j] += a * b
        dist = new
    obs = sum(w[key_kf] for w in weeks)
    return sum(dist[obs:])


def mc_p(weeks: list[dict], n_iter: int = 2000, seed: int = 628, key_k: str = "n_k", key_kf: str = "k_fish") -> float:
    rng = random.Random(seed)
    obs = sum(w[key_kf] for w in weeks)
    hits = 0
    for _ in range(n_iter):
        s = 0
        for w in weeks:
            labels = [1] * w["n_fish"] + [0] * (w["n_univ"] - w["n_fish"])
            s += sum(rng.sample(labels, w[key_k]))
        hits += s >= obs
    return (hits + 1) / (n_iter + 1)


def summary(weeks: list[dict]) -> dict:
    K = sum(w["n_k"] for w in weeks)
    KF = sum(w["k_fish"] for w in weeks)
    U = sum(w["n_univ"] for w in weeks)
    F = sum(w["n_fish"] for w in weeks)
    KL = sum(w["n_kl"] for w in weeks)
    KLF = sum(w["kl_fish"] for w in weeks)
    return {"weeks": len(weeks), "K": K, "K_fish": KF, "K_rate": KF / K if K else None,
            "N": U - K, "N_fish": F - KF, "N_rate": (F - KF) / (U - K) if U > K else None,
            "p_mc2000": mc_p(weeks), "p_exact": exact_p(weeks),
            "Klevel": KL, "Klevel_fish": KLF, "Klevel_rate": KLF / KL if KL else None,
            "Klevel_N_rate": (F - KLF) / (U - KL) if U > KL else None,
            "Klevel_p_exact": exact_p(weeks, "n_kl", "kl_fish")}


if __name__ == "__main__":
    rows = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(summary(rows), indent=2, ensure_ascii=False))

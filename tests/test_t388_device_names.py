"""11-18 T-414:把 T-388 的三条断言补进仓库,并让 preflight 真的跑这个文件。

**这个文件原先只留在 lane-a 的工作树里,没随 lane-a/T-388 进仓** ⇒ preflight 从来没跑过它
(S-244:「测试存在 ≠ 测试被运行」)。本卡把它补进仓,同一提交里加 preflight 注册行
(先提注册会让 main 的 preflight 去跑一个还不存在的文件 ⇒ 直接红)。

**为什么这里的断言分两种世界**:T-388 的生产改动 —— `apparatus.p_two_sided_deviation` /
`p_two_sided_tail` 两个各有名的函数、`same_cell._shift_p` 改调这两个函数、`same_cell.line()`
印出格子日 —— 此刻**只在分支 `origin/lane-a/T-388` 上**(Seth 在审),还没进 main。所以:

  · T-388 并入后 ⇒ **强断言**:`tail2` 必须逐位等于 B 道口径;那一行必须印出格子日。
  · T-388 并入前 ⇒ **过渡断言**:旧口径必须原样在位(逐位不变),且与 B 道口径只许差
    「+1 修正」那点(≤ 2/(1+n))。

并入的那一刻,同一个文件自动升级为强断言 —— 不用再改它,也不用再动 preflight。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.evaluation import apparatus                         # noqa: E402
from src.data.evaluation.apparatus import p_lower, p_upper        # noqa: E402
from src.data.state import same_cell as sc                         # noqa: E402

#: T-388 的生产改动进 main 了没有 —— 进了 = 强断言,没进 = 过渡断言。
T388_MERGED = (hasattr(apparatus, "p_two_sided_tail")
               and hasattr(apparatus, "p_two_sided_deviation"))


def _old_shift_p(lab: np.ndarray, rets: np.ndarray, stat) -> dict:
    """11-14 之前的写法(T-388 之前 `same_cell._shift_p` 里的两行),留着做逐位对照。"""
    n = len(lab)
    rng = np.random.default_rng(sc.SEED)
    obs = stat(rets[lab])
    sims = np.array([stat(rets[np.roll(lab, int(k))]) for k in rng.integers(sc.MIN_SHIFT_D, n - sc.MIN_SHIFT_D, sc.N_SHIFT)])
    dev = float((np.abs(sims - sims.mean()) >= abs(obs - sims.mean())).mean())
    tail2 = min(1.0, 2.0 * min(float((sims <= obs).mean()), float((sims >= obs).mean())))
    return {"dev": round(dev, 4), "tail2": round(tail2, 4), "sims": sims, "obs": obs}


def _case(n: int = 900, seed: int = 5):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.03, n)
    lab = np.zeros(n, dtype=bool)
    lab[rng.choice(n, size=n // 12, replace=False)] = True
    return lab, rets


def test_the_deviation_p_is_bit_for_bit_the_old_one():
    """`p_shift_mean`(离平移均值的距离,S-864 登记的那一种)一个位都没变。"""
    lab, rets = _case()
    new = sc._shift_p(lab, rets, lambda x: float(x.mean()))
    old = _old_shift_p(lab, rets, lambda x: float(x.mean()))
    assert new["dev"] == old["dev"], "dev 必须与旧写法逐位相同"


def test_the_tail_p_now_is_the_one_the_ledger_registered():
    """`p_shift_mean_tail2` 要改成台账登记的那一种(S-866 B 道:`min(1, 2 × min(p_upper, p_lower))`)。

    旧写法用的是**原始占比**;B 道登记的 0.082 用的是 `p_upper`/`p_lower`(+1 修正)——
    同一个零分布上,原始占比给 0.081。差 0.001,方向是把生产模块对齐到台账登记的那个数。

    并入 T-388 前:必须还是旧口径(逐位不变),且与 B 道口径只许差 +1 修正那点;
    并入后:必须**逐位等于** B 道口径。
    """
    lab, rets = _case()
    new = sc._shift_p(lab, rets, lambda x: float(x.mean()))
    old = _old_shift_p(lab, rets, lambda x: float(x.mean()))
    sims, obs = old["sims"], old["obs"]
    blind = round(min(1.0, 2.0 * min(p_upper(obs, sims), p_lower(obs, sims))), 4)
    tol = 2 / (1 + len(sims))
    if T388_MERGED:
        assert new["tail2"] == blind, "tail2 必须等于 B 道登记的那一种"
    else:
        assert new["tail2"] == old["tail2"], "T-388 未并入时必须还是旧口径(逐位不变)"
        assert abs(new["tail2"] - blind) <= tol, "与 B 道口径只许差 +1 修正那点"
    assert abs(new["tail2"] - old["tail2"]) <= tol, "两种口径的差只许是 +1 修正那点"


def test_the_line_says_which_day_the_cell_is():
    """第一行真实数据(d = 11-14)的格子其实是 11-13 的(当时 stable_supply_30d 还没有 11-14 的值):
    字段里有 asof,那一行字里没有 —— 要印出来。

    并入 T-388 前:那一行还不印格子日(但也不许因为多了 asof 就炸);并入后:必须印出来。
    """
    s = {"status": "ok", "asof": "2026-11-13", "cell_words": "利率升·稳定币抽·周线坏·线下",
         "n_episodes": 12, "n_days": 257, "separable": False, "p_shift_mean": 0.1485, "p_shift_mean_tail2": 0.082,
         "d30": {"median": 0.003, "p_down_big": 0.28, "p_up_big": 0.14},
         "uncond_d30": {"p_down_big": 0.202, "p_up_big": 0.318}}
    t = sc.line(s)
    if T388_MERGED:
        assert "2026-11-13" in t and "格子日" in t, "这一格是哪一天的必须印出来"
    else:
        assert t and "格子日" not in t, "T-388 未并入时那一行还不印格子日"
    old = {k: v for k, v in s.items() if k != "asof"}
    assert sc.line(old) and "格子日" not in sc.line(old), "没有 asof 的旧字典不许炸,也不许编一个格子日出来"


def test_on_a_random_symmetric_sample_the_two_p_differ_by_more_than_two_over_n():
    """实测:零分布只是「对称」但抽样后均值不恰好是 0 时,两个 p 差的是 O(1/√n)(dev 用的是抽样均值),
    4000 个样本上差 0.002 > 2/n = 0.0005。精确对称(均值恰好 0)的零分布才满足 ≤ 2/n 那条。

    这条是给下一个人的:「对称零分布上两者相差 ≤ 2 / n」只在**精确对称**的零分布上成立。
    """
    if not T388_MERGED:
        pytest.skip("T-388 未并入 main:两个各有名的 p 函数还不存在(并入后本条自动生效)")
    from src.data.evaluation.apparatus import p_two_sided_deviation, p_two_sided_tail
    rng = np.random.default_rng(11)
    s = rng.normal(0.0, 1.0, 4000)
    a = float(np.quantile(s, 0.95))
    t, d = p_two_sided_tail(a, s), p_two_sided_deviation(a, s)
    assert abs(t - d) > 2 / len(s), "随机抽样(均值不恰好为 0)时差大于 2/n —— 那条界只对精确对称成立"
    half = np.array([1., 2., 3., 4., 5., 6., 7., 8., 9., 10.])
    sym = np.concatenate([half, -half, np.zeros(20)])
    assert abs(p_two_sided_tail(8.0, sym) - p_two_sided_deviation(8.0, sym)) <= 2 / len(sym)

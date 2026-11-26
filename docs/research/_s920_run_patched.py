"""跑 S-920 的脚本(Seth 写的,逐字不改),只补 sklearn 1.9.0 的一个边界崩溃。

崩溃现象(s920_run_crash_allnan_col.txt 存证):sklearn 1.9.0 的直方图分箱 `_find_binning_thresholds`
在「整列全缺」时崩:它先把缺失值剔掉,整列全缺 ⇒ 剩空数组 ⇒ `np.unique` 得空 ⇒
`sliding_window_view(distinct_values, 2)` 抛 `ValueError: window shape cannot be larger than input array shape`。
最小复现(与 S-920 无关):HistGradientBoostingClassifier 喂一列全 NaN ⇒ 同样的 ValueError。
S-920 踩到它的原因:2022 折的训练段(2021-12-02 之前平仓的票)里 `joint_z` 全缺 —— `joint_forecast_daily`
最早 2022-04-23 才有 z。

补法:把「整列全缺」按 sklearn 自己对「常数列(len(distinct_values)==1)」的既有处理办 —— 返回空的分箱阈值
⇒ 这一折里该特征不产生分裂(与常数列同一口径)。
不碰:s920_meta_label.py、模型超参、样本、判定口径、随机种子、特征集合。

用法(仓库根目录):
    python3 docs/research/_s920_run_patched.py --selftest
    nohup python3 docs/research/_s920_run_patched.py > docs/research/s920_run.txt 2>&1 &
"""
from __future__ import annotations

import runpy

import numpy as np
from sklearn.ensemble._hist_gradient_boosting import binning

_orig = binning._find_binning_thresholds


def _patched(col_data, max_bins, sample_weight=None):
    """整列全缺 ⇒ 按常数列处理(空阈值);其余原样。"""
    col = np.asarray(col_data, dtype=np.float64)
    if col.size and bool(np.isnan(col).all()):
        return np.asarray([], dtype=np.float64)
    return _orig(col, max_bins, sample_weight)


binning._find_binning_thresholds = _patched

if __name__ == "__main__":
    runpy.run_path("docs/research/s920_meta_label.py", run_name="__main__")

# T-089 v2 First-Version Report

_2026-10-13T11:36:29+00:00_

## Panel provenance

```json
{
  "backend": "s",
  "start": "2023-01-02",
  "end": "2026-10-12",
  "n_days": 1380,
  "sources": {
    "core_u": "synthetic(seed=20261013, priors per M-558)",
    "multiplier": "synthetic(seed=20261014, priors per M-558)",
    "portfolio_layer": "synthetic(seed=20261015, priors per M-558)",
    "cis_tilt": "synthetic(seed=20261016, priors per M-558)",
    "btc": "synthetic(seed=20261017, priors per M-558)"
  },
  "demo_sim_pack": {
    "multiplier": {
      "pct_vs_random": 0.96,
      "mu_post_ann": 0.07,
      "sigma_ann": 0.18
    },
    "portfolio_layer": {
      "pct_vs_random": 0.95,
      "mu_post_ann": 0.04,
      "sigma_ann": 0.14
    },
    "cis_tilt_note": "\u65e0 A \u8def\u8bc1\u636e(\u6ca1\u6709 holdout) \u2014 \u8d70\u7eaf B \u8def, evidence = \u8d85\u989d \u2265 MIN_DAYS"
  }
}
```

## 命令行

```

--backend synthetic

```

## 三段总收益 / 回撤 / 夏普(模拟基金 vs BTC vs ① vs 随机对照)



| window | metric | fund | core_u (①) | BTC | random_p50 | random_p95 | excess_vs_① | pct_vs_random |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W1 | total_return | +2.03% | -42.78% | +65.04% | +12.85% | +79.44% | +20.46% | 34% |
| W1 | max_dd       | -52.05% | -67.72% | -45.65% |  |  |  |  |
| W1 | sharpe       | +0.21 | -0.24 | +0.72 |  |  |  |  |
| W2 | total_return | -2.48% | -38.43% | -67.42% | -25.36% | +16.23% | +18.27% | 83% |
| W2 | max_dd       | -35.12% | -56.58% | -82.16% |  |  |  |  |
| W2 | sharpe       | +0.14 | -0.25 | -0.77 |  |  |  |  |

## 随机对照(500 次,Dirichlet α=1,固定 avg=1 - w_core[D])

- 取 6 个决策日的 weights / evidence_path 抽样(只用来定性核对合成器对不对,不参与统计):

  - 2023-01-02: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2023-08-20: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2024-04-06: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2024-11-22: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2025-07-10: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2026-02-25: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}

# T-089 v2 First-Version Report

_2026-10-13T11:36:33+00:00_

## Panel provenance

```json
{
  "backend": "d",
  "start": "2025-01-01",
  "end": "2026-10-12",
  "n_days": 650,
  "sources": {
    "btc": "real:research/t060/raw/btc_eth_coingecko.csv (CoinGecko)",
    "core_u": "synthetic-on-priors(seed=20261014)",
    "multiplier": "synthetic-on-priors(seed=20261015)",
    "portfolio_layer": "synthetic-on-priors(seed=20261016)",
    "cis_tilt": "synthetic-on-priors(seed=20261017)"
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

--backend csv

```

## 三段总收益 / 回撤 / 夏普(模拟基金 vs BTC vs ① vs 随机对照)


| window | metric | fund | core_u (①) | BTC | random_p50 | random_p95 | excess_vs_① | pct_vs_random |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W2 | total_return | -2.48% | -38.43% | -19.16% | -25.37% | +16.56% | +18.27% | 83% |
| W2 | max_dd       | -35.12% | -56.58% | -53.06% |  |  |  |  |
| W2 | sharpe       | +0.14 | -0.25 | -0.14 |  |  |  |  |

## 随机对照(500 次,Dirichlet α=1,固定 avg=1 - w_core[D])

- 取 6 个决策日的 weights / evidence_path 抽样(只用来定性核对合成器对不对,不参与统计):

  - 2025-01-01: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2025-04-19: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2025-08-05: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2025-11-21: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2026-03-09: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}
  - 2026-06-25: weights = {'core_cap': 0.19999999999999996, 'multiplier': 0.4, 'portfolio_layer': 0.4}
    path = {'multiplier': 'simulated', 'portfolio_layer': 'simulated', 'cis_tilt': 'off'}

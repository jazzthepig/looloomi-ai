# CometCloud — Open-Source Strategies

A few of our earlier, profitable strategies, released under MIT. These are **directional /
CIS-gated strategies** — genuinely tradeable, but they are *not* our edge. Our moat is the
upstream **causal** layer (forced-supply / positioning / narrative) and the conviction
kernel, which stay proprietary. What's here is the honest, replicable base.

Run them with [Freqtrade](https://www.freqtrade.io/). They pull live CIS signals from the
public CometCloud API (`https://looloomi.ai/api/v1`) — no key required.

| Strategy | File | Style | Honest status |
|---|---|---|---|
| **Swing Overlay (MTF)** | `SwingOverlayV7_MTF.py` | 4h-regime + 15m RSI-cross, long/short | Profitable in backtest, **in-sample** (Sharpe ~6, CAGR ~32%, PF 1.9, win 66%, DD ~3%, n≥500 trades). Directional TA — commodity, not our moat. Owes a walk-forward OOS. |
| **CIS Value / On-Chain** | `ValueOnChainStrategy.py` | F+O quality gate, daily | Reference implementation of CIS-gated value. Shows the engine; no standalone backtest claimed. |
| **CIS Breakout** | `BreakoutStrategy.py` | S+M momentum gate, 4h | Reference implementation of CIS-gated momentum. Same. |

## Honesty note (house rule)

We publish numbers we've measured and label what we haven't. The swing metrics above are
**in-sample** — strong, but not the same as a walk-forward-validated live edge. We don't
dress backtests as live track records. If a strategy here has no number, it's because we
haven't run a clean backtest on it, not because we're hiding a bad one.

## License

MIT — see `LICENSE`. Use them, fork them, improve them. If you build something good on the
CIS API, we'd like to hear about it.

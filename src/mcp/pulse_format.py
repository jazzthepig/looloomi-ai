"""宏观脉搏工具的输出排版(纯函数,不依赖 MCP 运行时 —— 测试直接调)。

2026-11-23:CoinGecko 停供期间 `cometcloud_get_macro_pulse` 对所有 agent 报
`TypeError: unsupported format string passed to NoneType.__format__` —— 上游取不到 BTC 占比时那个值是 None(不是 0),
而原来直接 `f"{dom:.1f}"`。**缺就写 n/a**:不报错,也不编一个 0(「读不到」塌成「0」比报错更难发现)。
"""
from __future__ import annotations

from typing import Any, Mapping


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v != 0 else None


def macro_pulse_markdown(data: Mapping[str, Any]) -> str:
    data = data if isinstance(data, Mapping) else {}
    # 平铺字段(data_layer v2 起);旧部署回落到嵌套结构
    fng_n = data.get("fng") or {}
    cg_n = data.get("data") or {}
    btc_n = data.get("btc") or {}
    fg = data.get("fear_greed_index", fng_n.get("value"))
    fg_label = data.get("fear_greed_label", fng_n.get("value_classification")) or "—"
    dom = _num(data.get("btc_dominance", (cg_n.get("market_cap_percentage") or {}).get("btc")))
    btc_px = _num(data.get("btc_price", btc_n.get("usd")))
    mc = _num(data.get("total_market_cap_usd"))
    tvl = _num(data.get("defi_tvl_usd"))
    try:
        fg_s = str(int(float(fg))) if fg is not None else "n/a"
    except (TypeError, ValueError):
        fg_s = "n/a"
    lines = [
        "# Macro Pulse",
        "",
        f"**Regime**: {data.get('macro_regime') or '—'}",
        f"**Fear & Greed**: {fg_s} — {fg_label}",
        f"**BTC Dominance**: {f'{dom:.1f}%' if dom is not None else 'n/a'}",
        f"**BTC Price**: {f'${btc_px:,.0f}' if btc_px is not None else 'n/a'}",
    ]
    if mc is not None:
        lines.append(f"**Total Crypto Market Cap**: ${mc / 1e9:.1f}B")
    if tvl is not None:
        lines.append(f"**DeFi TVL**: ${tvl / 1e9:.1f}B")
    return "\n".join(lines)

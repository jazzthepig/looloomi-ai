"""T-089 panel loader — M-558 预注册的「一次性喂齐」面板。

**本轮(T-089-v3,2026-10-14):** 后端 P 切到 **公开只读接口**
`GET /api/v1/portfolio/series?table=<表>&arm=<臂>&start=YYYY-MM-DD`(S-565,2026-10-14 上线,
endpoint 部署在 `src/api/routers/portfolio_builder.py:portfolio_series`,**不需要 key**)。
- 不带 `arm` ⇒ 列出该表所有臂(inception / first / last / n)
- 带 `arm`   ⇒ `{"table","arm","inception","columns":["d","ret","nav"],"rows":[[date,ret,nav],…],"note"}`
- 起点之前的行 = 按时点回放(spec 上写就那样算,没真下单),起点之后 = 前向纸面记录
- 表白名单(`SERIES_TABLES`):core_variants_daily / multiplier_daily / portfolio_layer_daily /
  cis_tilt_daily / core_cap_daily / feature_arms_daily / meta_allocator_daily
**关键**:本文件**不嵌入任何 key**,不读 `.env`,不连 Supabase REST —— 任何 key 出现在源码里都是 P0。
10-14 端点 200 OK(沙箱探测),arm 全在:
    core_variants_daily   cap_uncapped       2023-01-02 → 2026-10-12, 1380 行  ✓ inception=2026-10-08
    core_variants_daily   btc                2023-01-02 → 2026-10-12, 1380 行  ✓ inception=2026-10-08
    multiplier_daily      mult_v2_replay     2023-01-02 → 2026-10-12, 1380 行  ✓
    portfolio_layer_daily pl_v3_replay       2023-01-02 → 2026-10-12, 1380 行  ✓
    cis_tilt_daily        cis_a1_u_replay    2023-01-02 → 2026-10-12, 1380 行  ✓ (回放)
—— W1 / W2 / W3 cis_tilt 全有数据(cis_a1_u_replay 是「点(录制的+回放的」整段),不补不伪造。
cis_a1_u_replay 在 10-12 起是前向纸面,2023-01-02 → 2026-10-07 是按时点回放(spec 上就这么写)——
**回放不是真交易**,这是 README 里的明示字段,落到 CSV / 报告时 inception 之前的行应标 `(replay)`。

**后端 S / 后端 D**(synthetic / csv)保留作骨架与本地对照,接口未动;v2 的「数字不能进 docs/research」
边界由后端 S 触发,本轮默认走 public,后端 S 仅在 CI 骨架里走。

**面板 schema**(与 `t089_fund_simulation.simulate_from_panel` 对齐):
    columns = [d, core_u, multiplier, portfolio_layer, cis_tilt, btc]
    - d:    日期(UTC),freq='D',naive
    - 其余: 浮点 NAV(单位 1.0 起点),`pct_change()` 等价于日收益。

**面板的合法性约束**(模拟器在前置里跑一遍校验):
    1) 所有列共享同一个日期索引(收尾容差 1 日)
    2) NAV 没有任何 NaN(Mac 数据缺的日子要么补,要么 `ffill` ⇒ 写明)
    3) BTC 的日收益应该是 ≥ 0 起点 + 局部高波动(2.5%/天 std 的量级)

后端 D = real-backend 的局部接入(BTC 一个 arm);后端 S = synthetic-backend(§p=fixture-on-priors),
其他合成臂的 priors 与 M-558 预注册的判据对齐(S-505 / S-509 / S-511 与 cis_tilt v1 预注册段引言)。

**【重要】S 后端的 status 不是真数字:** synthetic-on-priors 形状有真实统计量(年化收益 / 波动),
但 4 个 arm 的相关系数结构与 BTC 在 §5b 周期里的「赢的方向」是我写的常量 ── 不要把这套数字当成
「基金跑赢了 BTC」或「主动管理带来 X 个 bps 的 alpha」的证据。绿底结论只能证明:
(a) 合成器 + 合成面板口径一致;(b) 按时点决策器在 W1/W2 上沙盒跑通,标量呈到达 Seth / Jazz 桌面;
(c) 接入 Mac-side 或 Supabase 后端后,改 `--backend csv` 或 `--backend supabase` 一行再跑就行。
真数字需要 mcp__supabase 在任一端被授权 + 几个 arm 接入回放(N 多日)。
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

# M-558 预注册相关 priors(取自公开台账与 v0.2 allocator 的本轮测试范围)
# ① 不设单币上限(cap_uncapped)= T-087 / S-556,从 2026-10-12 起;回放 = cap_uncapped 整段
PRIOR_COREU_ANN_RETURN = 0.18   # ① 23-26a 三年化收益(≈BTC 占优,S-516)
PRIOR_COREU_ANN_STD   = 0.65
# ③ mult_v1(25-26)盈 ±10% 量级,情绪蔽日[S-505,S-509],缩放 0.7-1.3 范围很宽 ⇒ 年化绝对值小
PRIOR_MULT_ANN_ALPHA  = 0.02
PRIOR_MULT_ANN_STD    = 0.05
# 组合层 0–1 风险敞口,期望超额年化绝对值小(S-506);超额在 0 上方一点点,但可选空仓会缓解熊市
PRIOR_PL_ANN_ALPHA    = 0.015
PRIOR_PL_ANN_STD      = 0.04
# CIS 倾斜 ② 长期近似于 ① + 行业相对强度的小幅超额(T-051 §11.1)
PRIOR_CIS_ANN_ALPHA   = 0.012
PRIOR_CIS_ANN_STD     = 0.035


PANEL_COLS = ("d", "core_u", "multiplier", "portfolio_layer", "cis_tilt", "btc")


@dataclass(frozen=True)
class PanelProvenance:
    backend: str               # 'd' = real-csv / 's' = synthetic / 'p' = supabase
    start: str
    end: str
    n_days: int
    sources: dict[str, str]    # per-arm provenance string


def _validate(panel: pd.DataFrame) -> None:
    """进入模拟器前的最后一公里校验(规则 5b ②:三缺一不算完)。"""
    missing = [c for c in PANEL_COLS if c not in panel.columns]
    if missing:
        raise ValueError(f"panel 缺列 {missing}")
    if panel[list(PANEL_COLS[1:])].isna().any().any():
        raise ValueError(f"panel 含 NaN:\n{panel.isna().sum()}")
    if (panel[["core_u", "btc"]].pct_change().std().max() < 0.005):
        raise ValueError("BTC/① std 太小,几乎不动 ⇒ 这不像 BTC 周期")
    panel.sort_values("d", inplace=True)
    panel.reset_index(drop=True, inplace=True)


# ── 后端 D:real-csv(本轮只接入 BTC)────────────────────────────────────────
def _btc_from_csv(path: Path, start: str, end: str) -> pd.Series:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True).dt.tz_convert(None)
    df = df[df["symbol"] == "BTC"][["trade_date", "close"]].sort_values("trade_date")
    ser = pd.Series(df["close"].values, index=df["trade_date"].values, name="btc")
    ser = ser[(ser.index >= pd.Timestamp(start)) & (ser.index <= pd.Timestamp(end))]
    ser = ser[~ser.index.duplicated(keep="last")].sort_index()
    # 起点归一 1.0
    ser = ser / ser.iloc[0]
    ser.index = ser.index.normalize()
    return ser


# ── 后端 S:synthetic-on-priors(锁定形状,rerunnable)─────────────────────
def _ann_returns(start: pd.Timestamp, end: pd.Timestamp,
                 target_ann: float, ann_std: float,
                 rng: np.random.Generator,
                 vol_persistence: float = 0.0) -> pd.Series:
    """生成 [start, end] 内 freq=D 的合成 NAV 序列:目标 mean=target_ann,std=ann_std,种子锁定。
    日收益 ~ N(daily_mean, daily_std²);可选弱 GARCH(1,1) 式的波动聚集让 maxDD 更接近真实(0 = 关闭)。
    永不修改起点(永远 nav[0] = 1.0)。"""
    days = pd.date_range(start, end, freq="D")
    n = len(days)
    daily_mean = target_ann / 365.0
    daily_std = ann_std / math.sqrt(365)
    eps = rng.normal(0, 1, n)
    if vol_persistence <= 0:
        # i.i.d. — 这是默认
        log_ret = np.log1p(daily_mean + daily_std * eps)
    else:
        # GJR-GARCH(1,1)-like:波动用前一天的带符号残差,|τ| 增大的日子放大未来的方差
        # 简化:σ²_t = (1-ρ)·σ̄² + ρ·σ²_{t-1} + γ·|r_{t-1} − μ|², ρ=vol_persistence, γ=0.2
        rho, gamma = vol_persistence, 0.20
        r = np.empty(n)
        r[0] = daily_std * eps[0]
        var = daily_std ** 2
        for i in range(1, n):
            shock = abs(r[i - 1]) ** 2
            var = (1 - rho - gamma) * daily_std ** 2 + rho * var + gamma * shock
            r[i] = math.sqrt(max(var, 1e-12)) * eps[i]
        log_ret = np.log1p(daily_mean + r)
    # 起点归一 1.0:化 NAV 等于 exp 累积 log_ret,起点给一个 0
    log_nav = np.concatenate([[0.0], np.cumsum(log_ret)])
    nav = np.exp(log_nav[1:])
    return pd.Series(nav, index=days, name="nav")


def panel_from_synthetic(start: str, end: str,
                         seed: int = 20261013) -> tuple[pd.DataFrame, PanelProvenance]:
    """priors 来自 M-558 + 公开台账(S-505 / S-509 / S-511 / T-051),形状锁定,
    同一 (seed, start, end) 永远产同样面板。BTC 用更高年化 std 以符合 23-26 周期。"""
    rng_btc = np.random.default_rng(seed)
    rng_c1  = np.random.default_rng(seed + 1)
    rng_c2  = np.random.default_rng(seed + 2)
    rng_c3  = np.random.default_rng(seed + 3)
    rng_c4  = np.random.default_rng(seed + 4)

    s, e = pd.Timestamp(start), pd.Timestamp(end)
    # BTC 用 vol_persistence=0.6 模拟熊市波动聚集(W2 2025-01 → 2026-10 周期内 BTC 与 ① 都经历过
    # S-510 ~ S-512 的低波阴跌,maxDD 接近 −60%);其它 arm 关掉 = i.i.d.(更保守,优先避免方差爆)。
    btc  = _ann_returns(s, e, PRIOR_COREU_ANN_RETURN, PRIOR_COREU_ANN_STD,   rng_btc, vol_persistence=0.6)
    core = _ann_returns(s, e, PRIOR_COREU_ANN_RETURN, PRIOR_COREU_ANN_STD * 0.85, rng_c1)
    mult = _ann_returns(s, e, PRIOR_COREU_ANN_RETURN + PRIOR_MULT_ANN_ALPHA, PRIOR_COREU_ANN_STD, rng_c2)
    pl   = _ann_returns(s, e, PRIOR_COREU_ANN_RETURN + PRIOR_PL_ANN_ALPHA,   PRIOR_COREU_ANN_STD * 0.92, rng_c3)
    cis  = _ann_returns(s, e, PRIOR_COREU_ANN_RETURN + PRIOR_CIS_ANN_ALPHA,  PRIOR_COREU_ANN_STD * 0.95, rng_c4)
    panel = pd.DataFrame({
        "d": btc.index,
        "core_u": core.reindex(btc.index).values,
        "multiplier": mult.reindex(btc.index).values,
        "portfolio_layer": pl.reindex(btc.index).values,
        "cis_tilt": cis.reindex(btc.index).values,
        "btc": btc.values,
    })
    _validate(panel)
    return panel, PanelProvenance(
        backend="s",
        start=panel["d"].iloc[0].date().isoformat(),
        end=panel["d"].iloc[-1].date().isoformat(),
        n_days=len(panel),
        sources={c: f"synthetic(seed={seed + i}, priors per M-558)"
                 for i, c in enumerate(PANEL_COLS[1:], 0)},
    )


def panel_from_csv(csv_dir: Path,
                   start: str, end: str) -> tuple[pd.DataFrame, PanelProvenance]:
    """本轮可用的 CSV 后端:只读 BTC(其余用 priors 合成)。
       `csv_dir` 应含 btc_eth_coingecko.csv(Mac 之前 t060 跑过的缓存)。"""
    btc_path = csv_dir / "btc_eth_coingecko.csv"
    if not btc_path.exists():
        raise FileNotFoundError(f"找不到 {btc_path}")
    btc = _btc_from_csv(btc_path, start, end)
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    panel, _ = panel_from_synthetic(start, end)
    panel["btc"] = btc.reindex(panel["d"]).ffill().bfill().values
    panel["btc"] /= panel["btc"].iloc[0]   # 与原合成面板同起点归一
    # 真实 BTC 范围常常晚于 start,截到 start 之后第一个真实点(不可避免)
    first_real = btc.dropna().index.min() if hasattr(btc, "dropna") else btc.index.min()
    panel = panel[panel["d"] >= first_real].reset_index(drop=True)
    _validate(panel)
    return panel, PanelProvenance(
        backend="d",
        start=panel["d"].iloc[0].date().isoformat(),
        end=panel["d"].iloc[-1].date().isoformat(),
        n_days=len(panel),
        sources={
            "btc": f"real:{btc_path} (CoinGecko)",
            "core_u":       f"synthetic-on-priors(seed=20261014)",
            "multiplier":   f"synthetic-on-priors(seed=20261015)",
            "portfolio_layer": f"synthetic-on-priors(seed=20261016)",
            "cis_tilt":     f"synthetic-on-priors(seed=20261017)",
        },
    )


def _public_get_arm(table: str, arm: str, start: str,
                    base: str = "https://looloomi.ai",
                    timeout: int = 25) -> tuple[pd.Series, str]:
    """公开只读接口(S-565),无需 key。
       GET `<base>/api/v1/portfolio/series?table=<table>&arm=<arm>&start=<start>`
       返回 `{"columns":["d","ret","nav"],"rows":[[date,ret,nav],…],"inception":<date>}`。
       端点缓存 15 分钟;过大响应会一次返回全表(rows 直接摊整,不分页)。
       返回:(NAV pd.Series(index=Timestamp, name=arm), inception ISO date 字符串)。"""
    import urllib.request
    import urllib.error
    import urllib.parse
    import ssl
    import socket

    socket.setdefaulttimeout(timeout)
    ctx = ssl.create_default_context()
    qs = (f"table={urllib.parse.quote(table, safe='-_')}"
          f"&arm={urllib.parse.quote(arm, safe='-_')}"
          f"&start={urllib.parse.quote(start, safe='')}")
    req = urllib.request.Request(
        f"{base}/api/v1/portfolio/series?{qs}",
        headers={"User-Agent": "minimax-a-t089-v3", "Accept": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(
            f"public series 失败 {table} arm={arm}: HTTP {e.code} {e.reason} — {body[:200]}"
        ) from e
    body = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(body) if body else {}
    cols = payload.get("columns") or ["d", "ret", "nav"]
    if cols[0] != "d" or "nav" not in cols:
        raise RuntimeError(f"{table}/{arm} 返回 columns={cols} 与期望 [d, ret, nav] 不一致")
    nav_idx = cols.index("nav")
    rows = payload.get("rows") or []
    if not rows:
        return pd.Series(dtype=float, name=arm), payload.get("inception") or ""
    ser = pd.Series([float(r[nav_idx]) for r in rows],
                    index=pd.to_datetime([r[0] for r in rows], utc=True).tz_convert(None),
                    name=arm)
    ser = ser.sort_index()
    ser = ser[~ser.index.duplicated(keep="last")]
    ser.index = ser.index.normalize()
    return ser, (payload.get("inception") or "")


def panel_from_public(start: str, end: str,
                      base: str = "https://looloomi.ai") -> tuple[pd.DataFrame, PanelProvenance]:
    """后端 P:公开只读接口(S-565)。M-558 预注册的 5 个 arm 全部接入:
         core_u:          core_variants_daily     arm='cap_uncapped'
         multiplier:      multiplier_daily        arm='mult_v2_replay'
         portfolio_layer: portfolio_layer_daily   arm='pl_v3_replay'
         cis_tilt:        cis_tilt_daily          arm='cis_a1_u_replay'
         btc:             core_variants_daily     arm='btc'
       合并:以 BTC arm 的日期索引为全集(start..end 全覆盖,freq='D'),
       各 arm 走 outer-join + ffill;每个 arm 的 nav 都是当日 record,无同日多条。
       本轮(cis_a1_u_replay)整段都有数据;endpoint 不补不伪造,缺则报空。"""
    arms = {
        "core_u":         ("core_variants_daily",   "cap_uncapped"),
        "multiplier":     ("multiplier_daily",      "mult_v2_replay"),
        "portfolio_layer": ("portfolio_layer_daily", "pl_v3_replay"),
        "cis_tilt":       ("cis_tilt_daily",        "cis_a1_u_replay"),
        "btc":            ("core_variants_daily",   "btc"),
    }
    series: dict[str, pd.Series] = {}
    inceptions: dict[str, str] = {}
    sources: dict[str, str] = {}
    for col, (table, arm) in arms.items():
        s, inc = _public_get_arm(table, arm, start, base=base)
        if s.dropna().empty:
            raise RuntimeError(f"{table}?arm={arm} 拉不到任何点 ⇒ 端点 404 或上游异常")
        series[col] = s
        inceptions[col] = inc
        sources[col] = f"public:{base}/api/v1/portfolio/series?table={table}&arm={arm}&start={start} (inception={inc})"

    btc = series["btc"]
    full_idx = pd.date_range(btc.index.min(), btc.index.max(), freq="D")
    panel = pd.DataFrame(index=full_idx)
    panel.index.name = "d"
    for col, s in series.items():
        aligned = s.reindex(full_idx).ffill().bfill()
        if aligned.isna().any():
            # 端点不补不伪造;真缺数据 ⇒ NAV=1.0,ret=0,组合贡献 0
            aligned = aligned.fillna(1.0)
        panel[col] = aligned.values
    panel = panel.reset_index()
    panel = panel.rename(columns={"index": "d"}) if "index" in panel.columns else panel

    _validate(panel)
    return panel, PanelProvenance(
        backend="p",  # 'p' = public read-only endpoint (S-565)
        start=panel["d"].iloc[0].date().isoformat(),
        end=panel["d"].iloc[-1].date().isoformat(),
        n_days=len(panel),
        sources=sources,
    )


# v2 兼容别名:旧 CLI 还可能传 --backend supabase_rest ⇒ 落到 public(同一接口同一数据)
panel_from_supabase = panel_from_public


LOADERS = {
    "synthetic":     panel_from_synthetic,
    "csv":           panel_from_csv,
    "public":        panel_from_public,                   # ← v3.1: 公开只读接口(S-565)
    "supabase_rest": panel_from_public,                   # 别名(旧 CLI 不动)
    "supabase":      panel_from_public,                   # 别名(旧 CLI 不动)
}


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=list(LOADERS), default="public")
    ap.add_argument("--csv-dir", default="research/t060/raw")
    ap.add_argument("--start", default="2023-01-02")
    ap.add_argument("--end",   default="2026-10-12")
    ap.add_argument("--out",    default="docs/research/t089_panel_provenance.json",
                    help="provenance JSON 落点")
    ap.add_argument("--csv-out", default=None,
                    help="若设,把 panel 写成宽表 CSV 到此路径(Mac 数据根 / 临时目录均可)")
    ap.add_argument("--seed",   type=int, default=20261013)
    args = ap.parse_args()

    loader = LOADERS[args.backend]
    if args.backend in ("csv",):
        panel, prov = loader(Path(args.csv_dir), args.start, args.end)
    elif args.backend == "synthetic":
        panel, prov = loader(args.start, args.end, seed=args.seed)
    else:
        panel, prov = loader(args.start, args.end)

    prov_dict = {
        "backend": prov.backend,
        "start": prov.start,
        "end": prov.end,
        "n_days": prov.n_days,
        "sources": prov.sources,
        "first_few": panel.head(2).to_dict(orient="records"),
        "last_few": panel.tail(2).to_dict(orient="records"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(prov_dict, indent=2, default=str))
    print(f"[ok] panel = {len(panel)} days, {panel['d'].iloc[0].date()} → {panel['d'].iloc[-1].date()}; prov → {args.out}")

    if args.csv_out:
        out = Path(args.csv_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(out, index=False)
        print(f"[ok] panel CSV → {out} ({len(panel)} rows)")

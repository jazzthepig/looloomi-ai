"""T-089 panel loader — M-558 预注册的「一次性喂齐」面板。

**本轮(T-089-v3.1,2026-10-14,v3 第二段):** 后端 P 切到 **公开只读接口**
`GET /api/v1/portfolio/series?table=<表>&arm=<臂>&start=YYYY-MM-DD`(S-565,2026-10-14 上线,
endpoint 部署在 `src/api/routers/portfolio_builder.py:portfolio_series`,**不需要 key**)。

§Seth-1014a 三处修订:
  1) `panel_from_public` 删 ffill / bfill / fillna(1.0) — 缺失如实留 NaN;
     各 arm 的 first / last / n / 内部缺口写进 provenance;**缺口 > 1 天直接报错**;
     inception 前无数据的臂按「该臂尚不存在」处理(NaN 留到全集,模拟器自行甄别)。
  2) 删 `panel_from_synthetic` / `panel_from_csv` 两个后端(priors 是编造的,
     不得留在 docs/research;只留后端 P)。
  3) 校验改逐列做:每列 std 单独检查;断言每列首行 NAV = 1.0,若不则显式归一并写 provenance。

**后端 P 接口约定**(白名单,see SERIES_TABLES):
  - 不带 `arm` ⇒ 列出该表所有臂(inception / first / last / n)
  - 带 `arm`   ⇒ `{"table","arm","inception","columns":["d","ret","nav"],"rows":[…],"note"}`
  - 起点之前的行 = 按时点回放(spec 上写就那样算,没真下单),起点之后 = 前向纸面记录
  - 表白名单:core_variants_daily / multiplier_daily / portfolio_layer_daily /
    cis_tilt_daily / core_cap_daily / feature_arms_daily / meta_allocator_daily

**面板 schema**(与 `t089_fund_simulation.simulate_from_panel` 对齐):
    columns = [d, core_u, multiplier, portfolio_layer, cis_tilt, btc]
    - d:    日期(UTC),freq='D',naive
    - 其余: 浮点 NAV(单位 1.0 起点)或 NaN(臂尚未存在 / 端点无数据)

**面板的合法性约束**(模拟器在前置里跑一遍校验):
  1) 所有列共享同一个日期索引(以 BTC 索引为全集)
  2) 列内不允许内部缺口(连续两日间距 > 1 天直接报错)
  3) NaN 是合法的(inception 前该臂尚未存在)
  4) 每列首行若是数值,必须 = 1.0(否则显式归一并写 provenance)
  5) 每列 std 单独检查(> 0.005),不合并取 max
"""
from __future__ import annotations

import argparse
import json
import ssl
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PANEL_COLS = ("d", "core_u", "multiplier", "portfolio_layer", "cis_tilt", "btc")

SERIES_TABLES = {
    "core_variants_daily", "multiplier_daily", "portfolio_layer_daily",
    "cis_tilt_daily", "core_cap_daily", "feature_arms_daily", "meta_allocator_daily",
}


@dataclass(frozen=True)
class ArmProvenance:
    """单臂 provenance — first / last / n / 内部最大缺口 / inception(端点声明的前向起点)"""
    arm: str
    table: str
    url: str
    n: int                       # 数据行数
    first: str | None            # 首日 ISO,缺数据 ⇒ None
    last: str | None             # 末日 ISO,缺数据 ⇒ None
    inception: str | None        # 端点声明的前向起点(2026-10-08 一类)
    max_gap_days: int            # 内部最大缺口(连续两日间距 - 1)
    n_gaps_gt1: int              # > 1 天的缺口数
    first_value: float | None    # 首行 NAV
    last_value: float | None     # 末行 NAV
    normalized: bool             # 是否做过显式归一(若首行 != 1.0)


@dataclass(frozen=True)
class PanelProvenance:
    backend: str                 # 'p' = public read-only endpoint
    start: str                   # 全集首日(BTC 索引起点)
    end: str                     # 全集末日(BTC 索引终点)
    n_days: int                  # 全集长度
    arms: dict[str, ArmProvenance] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "start": self.start,
            "end": self.end,
            "n_days": self.n_days,
            "arms": {k: vars(v) for k, v in self.arms.items()},
            "notes": self.notes,
        }


# ── 校验 ─────────────────────────────────────────────────────────────────
def _validate(panel: pd.DataFrame, prov: PanelProvenance) -> pd.DataFrame:
    """逐列校验(§Seth-1014a #3)。

    规则:
      (a) 所有必需列存在
      (b) 每列首行若是数值,必须 = 1.0;否则显式归一并写 provenance
      (c) 每列 std > 0.005(逐列,不合 max)
      (d) 每列无内部缺口(已在 _inspect_arm 里报过;此处再防)
      (e) 索引连续 freq='D'
    """
    missing = [c for c in PANEL_COLS if c not in panel.columns]
    if missing:
        raise ValueError(f"panel 缺列 {missing}")

    panel = panel.sort_values("d").reset_index(drop=True)

    # (e) 索引连续
    d = pd.to_datetime(panel["d"])
    if len(d) >= 2:
        diffs = d.diff().dropna().dt.days
        if (diffs != 1).any():
            raise ValueError(
                f"panel 日期索引不连续(freq!='D');最大间距={int(diffs.max())} 天,出现于 idx={int(diffs.idxmax())}"
            )

    # (b) 首行 NAV = 1 断言
    for col in PANEL_COLS[1:]:
        first_val = panel[col].iloc[0]
        if pd.isna(first_val):
            # 首行为 NaN ⇒ 臂尚未存在,合法;把 NaN 视为起点
            continue
        if abs(float(first_val) - 1.0) > 1e-9:
            # 显式归一
            panel[col] = panel[col] / float(first_val)
            # 同步改 provenance 标记
            new_arms = {}
            for k, ap in prov.arms.items():
                if k == col:
                    new_arms[k] = ArmProvenance(
                        **{**vars(ap), "normalized": True,
                           "first_value": 1.0,
                           "last_value": float(panel[col].iloc[-1])}
                    )
                else:
                    new_arms[k] = ap
            object.__setattr__(prov, "arms", new_arms)
            prov.notes.append(f"{col} 首行 NAV={first_val} ≠ 1.0,已显式归一")

    # (c) std 逐列
    for col in PANEL_COLS[1:]:
        s = panel[col].dropna()
        if len(s) < 2:
            raise ValueError(f"列 {col} 有效行 < 2,无法校验 std")
        if s.std() < 0.005:
            raise ValueError(
                f"列 {col} std={s.std():.6f} < 0.005,几乎不动 ⇒ 不像这条 arm 的真实波动"
            )

    # (d) 内部缺口 — 已在 _inspect_arm 触发,这里再确认 NaN 不出现在 arm 的"已知区间"内
    for col, ap in prov.arms.items():
        if ap.first is None or ap.last is None:
            continue
        s = panel.set_index("d")[col]
        s = s.loc[ap.first:ap.last]
        n_nan_inside = int(s.isna().sum())
        if n_nan_inside > 0:
            raise ValueError(
                f"列 {col} 在 first={ap.first} → last={ap.last} 区间内出现 {n_nan_inside} 个 NaN;"
                f"这与 endpoint 声明冲突(端点说该臂是连续的)"
            )

    return panel


# ── 内部缺口检测 ──────────────────────────────────────────────────────────
def _inspect_arm(name: str, table: str, ser: pd.Series, url: str, inc: str) -> ArmProvenance:
    """计算单臂的 provenance:first/last/n/最大缺口。

    - NaN 序列 ⇒ 该臂从未存在(inception 前无数据)
    - 否则:内部缺口 = 连续两日间距 - 1,> 1 报错
    """
    if ser.dropna().empty:
        return ArmProvenance(
            arm=name, table=table, url=url, n=0,
            first=None, last=None, inception=inc or None,
            max_gap_days=0, n_gaps_gt1=0,
            first_value=None, last_value=None, normalized=False,
        )
    s = ser.dropna().sort_index()
    s.index = s.index.normalize()
    s = s[~s.index.duplicated(keep="last")]
    n = len(s)
    first = s.index.min().date().isoformat()
    last = s.index.max().date().isoformat()
    if n >= 2:
        diffs = s.index.to_series().diff().dropna().dt.days
        max_gap = int(diffs.max())
        n_gaps_gt1 = int((diffs > 1).sum())
    else:
        max_gap, n_gaps_gt1 = 0, 0
    if max_gap > 1:
        raise ValueError(
            f"{name} ({table}) 内部最大缺口 {max_gap} 天(> 1);"
            f"端点声明该臂连续,触发 §Seth-1014a #1 报错过线"
        )
    return ArmProvenance(
        arm=name, table=table, url=url, n=n,
        first=first, last=last, inception=inc or None,
        max_gap_days=max_gap, n_gaps_gt1=n_gaps_gt1,
        first_value=float(s.iloc[0]), last_value=float(s.iloc[-1]),
        normalized=False,
    )


# ── 公开只读端点 ─────────────────────────────────────────────────────────
def _public_get_arm(table: str, arm: str, start: str,
                    base: str = "https://looloomi.ai",
                    timeout: int = 25) -> tuple[pd.Series, str]:
    """GET `<base>/api/v1/portfolio/series?table=<table>&arm=<arm>&start=<start>`
    返回 NAV pd.Series(index=Timestamp, name=arm) 与 inception ISO 字符串。
    端点缓存 15 分钟;过大响应一次返回全表(rows 直接摊整)。"""
    socket.setdefaulttimeout(timeout)
    ctx = ssl.create_default_context()
    qs = (f"table={urllib.parse.quote(table, safe='-_')}"
          f"&arm={urllib.parse.quote(arm, safe='-_')}"
          f"&start={urllib.parse.quote(start, safe='')}")
    req = urllib.request.Request(
        f"{base}/api/v1/portfolio/series?{qs}",
        headers={"User-Agent": "minimax-a-t089-v3.1", "Accept": "application/json"},
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
                      base: str = "https://looloomi.ai",
                      arms_map: dict[str, tuple[str, str]] | None = None
                      ) -> tuple[pd.DataFrame, PanelProvenance]:
    """后端 P:公开只读接口(S-565)。M-558 预注册的 5 个 arm 全部接入:
         core_u:          core_variants_daily     arm='cap_uncapped'
         multiplier:      multiplier_daily        arm='mult_v2_replay'
         portfolio_layer: portfolio_layer_daily   arm='pl_v3_replay'
         cis_tilt:        cis_tilt_daily          arm='cis_a1_u_replay'
         btc:             core_variants_daily     arm='btc'
       合并:以 BTC arm 的日期索引为全集(start..end 全覆盖,freq='D'),
       **不 ffill / bfill / fillna(1.0)**;inception 前没有数据的臂保持 NaN
       (模拟器按"该臂尚未存在"处理)。

    缺口 > 1 天 ⇒ 报错(§Seth-1014a #1);首行 NAV != 1 ⇒ 显式归一并写 provenance。
    """
    if arms_map is None:
        arms_map = {
            "core_u":          ("core_variants_daily",   "cap_uncapped"),
            "multiplier":      ("multiplier_daily",      "mult_v2_replay"),
            "portfolio_layer": ("portfolio_layer_daily", "pl_v3_replay"),
            "cis_tilt":        ("cis_tilt_daily",        "cis_a1_u_replay"),
            "btc":             ("core_variants_daily",   "btc"),
        }

    # 1) 拉每臂
    series: dict[str, pd.Series] = {}
    inceptions: dict[str, str] = {}
    ap_list: dict[str, ArmProvenance] = {}
    for col, (table, arm) in arms_map.items():
        if table not in SERIES_TABLES:
            raise ValueError(f"表 {table} 不在白名单 SERIES_TABLES")
        s, inc = _public_get_arm(table, arm, start, base=base)
        url = f"{base}/api/v1/portfolio/series?table={table}&arm={arm}&start={start}"
        series[col] = s
        inceptions[col] = inc
        ap_list[col] = _inspect_arm(col, table, s, url, inc)

    # 2) 全集 = BTC 索引(若 BTC 空 ⇒ 报错;BTC 是全集骨架)
    btc = series.get("btc", pd.Series(dtype=float))
    if btc.dropna().empty:
        raise RuntimeError("BTC 臂拉不到任何点 ⇒ 端点 404 或上游异常;BTC 是全集骨架")
    full_idx = pd.date_range(btc.index.min(), btc.index.max(), freq="D")

    # 3) outer-join 到全集;**缺失保持 NaN**(§Seth-1014a #1)
    panel = pd.DataFrame({"d": full_idx})
    for col, s in series.items():
        panel[col] = s.reindex(full_idx).values

    # 4) Provenance 容器
    prov = PanelProvenance(
        backend="p",
        start=full_idx.min().date().isoformat(),
        end=full_idx.max().date().isoformat(),
        n_days=len(full_idx),
        arms=ap_list,
        notes=[],
    )

    # 5) 校验 + 必要归一
    panel = _validate(panel, prov)

    return panel, prov


# v2 兼容别名:旧 CLI 可能传 --backend supabase_rest / supabase ⇒ 落到 public
panel_from_supabase = panel_from_public


# v3 唯一允许的后端
LOADERS = {
    "public":        panel_from_public,
    "supabase_rest": panel_from_public,
    "supabase":      panel_from_public,
}


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=list(LOADERS), default="public")
    ap.add_argument("--start", default="2023-01-02")
    ap.add_argument("--end",   default="2026-10-12")
    ap.add_argument("--out",    default="docs/research/t089_panel_provenance.json",
                    help="provenance JSON 落点")
    ap.add_argument("--csv-out", default=None,
                    help="若设,把 panel 写成宽表 CSV 到此路径(Mac 数据根 / 临时目录均可)")
    args = ap.parse_args()

    loader = LOADERS[args.backend]
    panel, prov = loader(args.start, args.end)

    prov_dict = prov.to_jsonable()
    prov_dict["first_few"] = panel.head(2).to_dict(orient="records")
    prov_dict["last_few"] = panel.tail(2).to_dict(orient="records")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(prov_dict, indent=2, default=str))
    print(f"[ok] panel = {len(panel)} days, {panel['d'].iloc[0].date()} → {panel['d'].iloc[-1].date()}; prov → {args.out}")

    if args.csv_out:
        out = Path(args.csv_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(out, index=False)
        print(f"[ok] panel CSV → {out} ({len(panel)} rows)")

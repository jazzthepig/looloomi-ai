"""T-099 —— 把 Supabase 导出的原始文本拼成回放用的 panel.json(数据只在私有仓库,不进公开仓库)。

用法:python3 docs/research/t099_build_panel.py <raw_dir> <panel.json>

raw_dir 里的文件(MCP SQL 导出,逐行 `KEY|v1,v2,...`,空 = 缺):
  ret_*.txt        月收益,单位 bp(2015-01 … 2026-09,141 个)
  mcap_eq.txt      公司季末市值,单位 10 亿美元(2015-03 … 2026-09,47 个季末;world50_mcap_weekly v2,季末前 14 天内最后一个周点)
  mcap_other.txt   加密季末市值(10 亿美元,asset_mcap_daily)+ XAUUSD_PRICE 季末金价(美元 / 盎司)
  checksums_*.txt  导出时 SQL 端算的 KEY:Σ:个数:Σ(位置×值),拼之前逐行核对(转录错一个数就停)
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.universe.world50_data import metal_mcap_usd  # noqa: E402

N_MONTHS, N_QUARTERS = 141, 47
CRYPTO = {"BTC", "ETH", "XRP", "BNB", "SOL"}
BENCH = {"ACWI", "AGG", "QQQ", "SPY"}


def months() -> list[str]:
    return [f"{y}-{m:02d}" for y in range(2015, 2027) for m in range(1, 13)][:N_MONTHS]


def quarter_ends() -> list[str]:
    return [m for m in months() if m[5:] in ("03", "06", "09", "12")]


def read_lines(path: str) -> dict[str, list[str]]:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            k, v = line.split("|")
            out[k] = v.split(",")
    return out


def checksums(raw: str) -> dict[str, tuple[int, int, int]]:
    cs = {}
    for f in glob.glob(f"{raw}/checksums_*.txt"):
        for tok in Path(f).read_text().split():
            k, s, n, w = tok.rsplit(":", 3)
            cs[(Path(f).stem, k)] = (int(s), int(n), int(w))
    return cs


def verify(kind: str, key: str, vals: list[str], scale: float, cs: dict) -> None:
    xs = [(i + 1, round(float(x) * scale)) for i, x in enumerate(vals) if x != ""]
    got = (sum(x for _, x in xs), len(xs), sum(i * x for i, x in xs))
    exp = cs.get((kind, key))
    if exp is None:
        raise SystemExit(f"{key}: 没有 {kind} 校验和")
    if got[:2] != exp[:2] or (exp[2] != 0 and got[2] != exp[2]):
        raise SystemExit(f"{key}: 转录与 SQL 校验和不符 got={got} exp={exp}")


def build(raw: str) -> dict:
    cs = checksums(raw)
    ms, qs = months(), quarter_ends()
    assert len(qs) == N_QUARTERS
    ret: dict[str, list] = {}
    for f in sorted(glob.glob(f"{raw}/ret_*.txt")):
        for k, vals in read_lines(f).items():
            if len(vals) != N_MONTHS:
                raise SystemExit(f"{k}: {len(vals)} 个月,应为 {N_MONTHS}")
            kind = "checksums_eq" if ("checksums_eq", k) in cs else "checksums_other"
            verify(kind, k, vals, 1, cs)
            ret[k] = [None if x == "" else int(x) / 1e4 for x in vals]
    mcap: dict[str, dict[str, float]] = {q: {} for q in qs}
    for k, vals in read_lines(f"{raw}/mcap_eq.txt").items():
        verify("checksums_mcap", k, vals, 10, cs)
        for q, x in zip(qs, vals):
            if x != "":
                mcap[q][k] = float(x) * 1e9
    other = read_lines(f"{raw}/mcap_other.txt")
    for k, vals in other.items():
        if len(vals) != N_QUARTERS:
            raise SystemExit(f"{k}: {len(vals)} 个季末")
        for q, x in zip(qs, vals):
            if x == "":
                continue
            if k == "XAUUSD_PRICE":
                mcap[q]["XAUUSD"] = metal_mcap_usd("XAUUSD", float(x))
            elif float(x) > 0:
                mcap[q][k] = float(x) * 1e9
    cls = {k: ("crypto" if k in CRYPTO else "metal" if k == "XAUUSD" else "benchmark" if k in BENCH else "equity")
           for k in ret}
    missing = sorted({k for snap in mcap.values() for k in snap} - set(ret))
    if missing:
        raise SystemExit(f"有市值没收益:{missing}")
    return {"months": ms, "ret": ret, "mcap": mcap, "cls": cls}


if __name__ == "__main__":
    panel = build(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(panel))
    print(len(panel["ret"]), "条收益序列 ·", sum(len(v) for v in panel["mcap"].values()), "个季末市值点")

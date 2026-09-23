"""HL 4 币组合的决策内核 —— 回放和每日流程共用这一份代码(S-412)。

一个能力只有一条活路(SPINE 法则一):历史回放 `jev_replay_s412.py` 和之后的每日「只算不发」
都调这里的同一组函数。回放里算出来的仓位,就是实盘那天会算出来的仓位。

## 结构

    特征(只用 ≤t 的数据)
      → T3 基准权重(0/⅓/⅔/1)
      → 回答四类小问题:机械代理 或 Jev
      → Tom 组合规则(两臂相同,写死)
      → 限制换手(每周一次;变化 < 0.2 不动;总仓位上限 1.5)

Jev 只回答小问题,组合由代码做 —— 这是 TypeSafe 文档推荐的用法,
也是把 Tom 的硬规则(永不给亏损仓位加仓)留在代码里、不交给模型的办法。
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

COINS = ("BTC", "ETH", "SOL", "HYPE")
COST_SPOT = 12e-4           # 7bps 手续费 + 5bps 滑点,每单位换手
COST_PERP = 7.5e-4          # 4.5bps + 3bps

# ── 组合规则参数(S-412 预注册,改 = 新 S 编号)────────────────────────────
CROWDED_MULT = 0.5
PRESS_ADD = 0.5
MAX_COIN_W = 1.5
CAPITULATION_PROBE = 0.25
DEFEND_MULT = 0.5
TRADE_BAND = 0.2
MAX_GROSS = 1.5
NOUL_YES = 0.6
CHOICE_MIN_CONF = 0.3


# ───────────────────────── 数据 ─────────────────────────

def _hl_post(body: dict) -> Any:
    for k in range(10):
        try:
            r = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(body).encode(),
                                       headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(r, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(4 * (k + 1))
                continue
            raise
    raise RuntimeError("HL 429 持续")


def fetch_hl(cache: Path, coins=COINS) -> None:
    """HL 原生日线 + 全部小时资金费。已有缓存文件的币跳过。"""
    cache.mkdir(parents=True, exist_ok=True)
    for c in coins:
        if (cache / f"{c}.json").exists():
            continue
        cs = _hl_post({"type": "candleSnapshot", "req": {"coin": c, "interval": "1d", "startTime": 0,
                                                          "endTime": int(time.time() * 1000)}})
        fr, t = [], 0
        while True:
            b = _hl_post({"type": "fundingHistory", "coin": c, "startTime": t})
            time.sleep(0.35)
            if not b:
                break
            fr += b
            nt = b[-1]["time"] + 1
            if len(b) < 500 or nt <= t:
                break
            t = nt
        (cache / f"{c}.json").write_text(json.dumps({"candles": cs, "funding": fr}))
        print(f"  已抓 {c}: {len(cs)} 根日线, {len(fr)} 条资金费", flush=True)


def load_hl(cache: Path, coins=COINS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """→ (收盘价, 每日资金费合计)。丢掉今天未收盘的 K 线;没有资金费的日子保持 NaN。"""
    close, fund = {}, {}
    for c in coins:
        d = json.loads((cache / f"{c}.json").read_text())
        close[c] = pd.Series({pd.Timestamp(x["t"], unit="ms").normalize(): float(x["c"])
                              for x in d["candles"]}).sort_index()
        f = pd.DataFrame(d["funding"])
        f["d"] = pd.to_datetime(f["time"], unit="ms").dt.normalize()
        fund[c] = f.groupby("d")["fundingRate"].apply(lambda v: v.astype(float).sum())
    px = pd.DataFrame(close)
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    px = px[px.index < today]
    return px, pd.DataFrame(fund).reindex(px.index)


# ───────────────────────── 特征与基准 ─────────────────────────

def features_at(px: pd.DataFrame, fd: pd.DataFrame, t: pd.Timestamp) -> dict[str, dict]:
    """t 日收盘时每个币的特征。只用 ≤t 的数据。T3 未定义(不足 200 天)的币不出现。"""
    out = {}
    for c in px.columns:
        s = px[c].loc[:t].dropna()
        if len(s) < 201:
            continue
        p = s.iloc[-1]
        r = s.pct_change().iloc[-30:]
        f7 = fd[c].loc[:t].iloc[-7:]
        out[c] = {
            "ret_20d": p / s.iloc[-21] - 1,
            "ret_60d": p / s.iloc[-61] - 1,
            "ret_120d": p / s.iloc[-121] - 1,
            "vol_30d_ann": r.std() * math.sqrt(365),
            "dist_from_ma200": p / s.iloc[-200:].mean() - 1,
            "drawdown_from_200d_high": p / s.iloc[-200:].max() - 1,
            "funding_7d_ann": (f7.mean() * 365) if f7.notna().sum() >= 5 else None,
        }
    return out


def t3_base(f: dict) -> float:
    return sum(f[k] > 0 for k in ("ret_20d", "ret_60d", "ret_120d")) / 3


# ───────────────────────── 四类问题:统一的答案形状 ─────────────────────────

@dataclass
class Answers:
    trend_confirmed: dict[str, bool]
    crowded: dict[str, bool]
    capitulation: dict[str, bool]
    mode: str                                   # press | neutral | defend
    raw: dict = field(default_factory=dict)     # Jev 原始回答,落盘用


def mechanical_answers(feats: dict[str, dict]) -> Answers:
    tc, cr, cp = {}, {}, {}
    for c, f in feats.items():
        tc[c] = bool(f["ret_20d"] > 0 and f["ret_60d"] > 0 and f["ret_120d"] > 0 and f["dist_from_ma200"] > 0)
        cr[c] = bool((f["funding_7d_ann"] is not None and f["funding_7d_ann"] > 0.30) or f["dist_from_ma200"] > 0.50)
        cp[c] = bool(f["drawdown_from_200d_high"] < -0.40 and f["ret_20d"] < -0.20)
    b = feats.get("BTC")
    if b and b["dist_from_ma200"] > 0 and b["ret_60d"] > 0:
        mode = "press"
    elif b and b["dist_from_ma200"] < 0 and b["ret_60d"] < 0:
        mode = "defend"
    else:
        mode = "neutral"
    return Answers(tc, cr, cp, mode)


# ───────────────────────── Jev:问题、调用、回答 ─────────────────────────

def _anon_state(feats: dict[str, dict], book: dict[str, dict], ids: dict[str, str]) -> dict:
    assets = {}
    for c, f in feats.items():
        a = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()}
        a["current_weight"] = round(book.get(c, {}).get("w", 0.0), 3)
        a["return_since_last_decision"] = round(book.get(c, {}).get("ret_since", 0.0), 4)
        assets[ids[c]] = a
    return {"assets": dict(sorted(assets.items()))}


def jev_questions(asset_ids: list[str]) -> dict[str, dict]:
    q = {}
    for a in asset_ids:
        q[f"{a}__trend_confirmed"] = {
            "type": "noul",
            "instructions": f"For `assets.{a}`: is its uptrend confirmed, rather than a spike or false breakout likely to fail?",
            "criteria": {"true": "a sustained uptrend supported across short, medium and long horizons",
                         "false": "no uptrend, or a move that looks like a trap"}}
        q[f"{a}__crowded"] = {
            "type": "noul",
            "instructions": f"For `assets.{a}`: is positioning crowded or euphoric, a late-stage move likely to mean-revert?",
            "criteria": {"true": "stretched far above trend, expensive funding, euphoric",
                         "false": "not crowded"}}
        q[f"{a}__capitulation"] = {
            "type": "noul",
            "instructions": f"For `assets.{a}`: has a deep decline reached capitulation, with selling exhausted?",
            "criteria": {"true": "a deep decline where selling looks exhausted",
                         "false": "decline still orderly, or not deep"}}
    q["book_mode"] = {
        "type": "choice",
        "instructions": "For this group of liquid crypto assets as a whole, which stance fits the next week?",
        "criteria": {"press": "risk-on and confirmed trend across the group: be big when right",
                     "neutral": "mixed evidence",
                     "defend": "risk-off or breaking trends: cut exposure, do not hope"}}
    return q


class JevClient:
    """研究/影子盘用:**fail-closed**,任何错误都抛出;按请求体哈希缓存。key 只从环境变量读。"""

    URL = "https://api.typesafe.ai/v1/systemone"
    MODEL = "jev-latest"

    def __init__(self, cache_file: Path, api_key: Optional[str]):
        self.cache_file = cache_file
        self.api_key = api_key
        self.cache: dict[str, dict] = {}
        self.calls = 0
        self.input_tokens = 0
        if cache_file.exists():
            for line in cache_file.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.cache[row["h"]] = row["resp"]

    def evaluate(self, state: dict, questions: dict) -> dict:
        body = {"model": self.MODEL, "state": state, "questions": questions}
        h = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if h in self.cache:
            return self.cache[h]
        if not self.api_key:
            raise RuntimeError("缓存里没有这一条,且 JEV_API_KEY 未设置")
        import httpx
        for k in range(6):
            r = httpx.post(self.URL, json=body, timeout=30,
                           headers={"Authorization": f"Bearer {self.api_key}"})
            if r.status_code == 200:
                resp = r.json()
                break
            if r.status_code in (429, 500, 502, 503, 529):
                time.sleep(2 ** k)
                continue
            raise RuntimeError(f"Jev HTTP {r.status_code}: {r.text[:200]}")
        else:
            raise RuntimeError("Jev 重试 6 次仍失败")
        self.calls += 1
        self.input_tokens += int((resp.get("usage") or {}).get("input_tokens") or 0)
        self.cache[h] = resp
        with self.cache_file.open("a") as fh:
            fh.write(json.dumps({"h": h, "resp": resp}) + "\n")
        return resp


def jev_answers(client: JevClient, feats: dict, book: dict, rng: random.Random) -> Answers:
    coins = list(feats)
    labels = [f"asset_{i}" for i in range(1, len(coins) + 1)]
    rng.shuffle(labels)                                  # 每次调用重新打乱,不让编号携带身份
    ids = dict(zip(coins, labels))
    resp = client.evaluate(_anon_state(feats, book, ids), jev_questions(sorted(labels)))
    ans = resp["answers"]
    tc = {c: ans[f"{ids[c]}__trend_confirmed"]["noul"] >= NOUL_YES for c in coins}
    cr = {c: ans[f"{ids[c]}__crowded"]["noul"] >= NOUL_YES for c in coins}
    cp = {c: ans[f"{ids[c]}__capitulation"]["noul"] >= NOUL_YES for c in coins}
    m = ans["book_mode"]
    mode = m["choice"] if m.get("confidence", 0) >= CHOICE_MIN_CONF else "neutral"
    return Answers(tc, cr, cp, mode, raw={"ids": ids, "answers": ans})


# ───────────────────────── Tom 组合规则 + 限制换手 ─────────────────────────

def tom_targets(feats: dict, ans: Answers, book: dict) -> dict[str, float]:
    tgt = {}
    for c, f in feats.items():
        w = t3_base(f)
        if ans.crowded[c]:
            w *= CROWDED_MULT
        winning = book.get(c, {}).get("w", 0.0) > 0 and book.get(c, {}).get("ret_since", 0.0) > 0
        if ans.mode == "press" and ans.trend_confirmed[c] and winning:     # 永不给亏损仓位加仓
            w = min(MAX_COIN_W, w + PRESS_ADD)
        if t3_base(f) == 0 and ans.capitulation[c]:
            w = max(w, CAPITULATION_PROBE)
        if ans.mode == "defend":
            w *= DEFEND_MULT
        tgt[c] = w
    return tgt


def apply_turnover_limits(tgt: dict[str, float], current: dict[str, float]) -> dict[str, float]:
    out = {}
    for c, w in tgt.items():
        cur = current.get(c, 0.0)
        out[c] = w if abs(w - cur) >= TRADE_BAND else cur
    gross = sum(abs(v) for v in out.values()) / max(len(out), 1)
    if gross > MAX_GROSS:
        out = {c: v * MAX_GROSS / gross for c, v in out.items()}
    return out

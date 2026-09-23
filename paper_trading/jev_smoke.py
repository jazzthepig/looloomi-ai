"""Jev 真实 API 的第一次调用 —— **失败即报错,不 fail-open**。

    python3 -m paper_trading.jev_smoke            只打印请求体,不发送,不需要 key
    python3 -m paper_trading.jev_smoke --send     发送一次;需要 shell 里有 JEV_API_KEY

## 为什么要有这个文件

`TypesafeJevDecisionBackend` 的端点和请求格式是**按社区资料猜的**,至今没有一次真实调用。
而它是 fail-open 的:格式不对 ⇒ 每次都返回 `no_edge` + error 字段 ⇒
**一整段 Jev 回放会看起来像「Jev 一直选择观望」**。那是本仓库的主导缺陷:
「拿不到」被渲染成一个合理的答案。

所以在任何 Jev 回放或模拟盘之前,先用这个脚本打一枪:
直接调 backend 的 `_request` / `_parse_response`(和 S-397 走的是同一条代码路径),
任何异常原样抛出,退出码 1。

## 状态怎么给

4 个 HL 币的**匿名化**特征:没有币名、没有日期、没有价格水平,只有收益率、波动、回撤、资金费。
这是为了压低前视风险 —— Jev 是语言模型,在历史日期上回放时,训练数据可能已经见过那段行情。
匿名化能降低、不能消除这个风险;**干净的证据只能来自前向模拟盘。**

key 只从环境变量读,从不打印、不写文件。
"""
from __future__ import annotations

# S-402 bootstrap: `python3 paper_trading/jev_smoke.py` puts `paper_trading/`
# at sys.path[0], so `from paper_trading.X import` (inside _build_questions /
# _send) fails at module import — before argparse even sees `--send`. Pattern
# matches `spec_runner.py` / `replay_three_arms.py` / `run_paper_a17.py`
# (test_spec_runner_cli.py scans for it).
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent if _HERE.name == "paper_trading" else _HERE
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import argparse
import json
import math
import os
import sys
import time
import urllib.request

COINS = ["BTC", "ETH", "SOL", "HYPE"]


def _post(body: dict) -> list | dict:
    r = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=30))


def features() -> dict:
    """每个币一组归一化特征;键名匿名(asset_1..4),顺序固定但不暴露对应关系给 Jev。"""
    now = int(time.time() * 1000)
    out = {}
    for i, c in enumerate(COINS, 1):
        cs = _post({"type": "candleSnapshot", "req": {"coin": c, "interval": "1d",
                                                       "startTime": now - 260 * 86_400_000, "endTime": now}})
        closes = [float(x["c"]) for x in cs][:-1]          # 丢掉未收盘的今天
        fr = _post({"type": "fundingHistory", "coin": c, "startTime": now - 7 * 86_400_000})
        f7 = sum(float(x["fundingRate"]) for x in fr) / max(len(fr), 1) * 24 * 365
        rets = [closes[k] / closes[k - 1] - 1 for k in range(len(closes) - 30, len(closes))]
        mu = sum(rets) / len(rets)
        vol30 = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(365)
        ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
        p = closes[-1]
        out[f"asset_{i}"] = {
            "ret_20d": round(p / closes[-21] - 1, 4),
            "ret_60d": round(p / closes[-61] - 1, 4),
            "ret_120d": round(p / closes[-121] - 1, 4),
            "vol_30d_ann": round(vol30, 4),
            "dist_from_ma200": round(p / ma200 - 1, 4) if ma200 else None,
            "drawdown_from_200d_high": round(p / max(closes[-200:]) - 1, 4),
            "funding_7d_ann": round(f7, 4),
        }
    return out


def questions():
    from paper_trading.jev_decision import JevQuestion
    qs = [JevQuestion(
        name=f"asset_{i}_positioning", primitive="Choice",
        instructions=(f"For asset_{i}, relative to a trend-following baseline weight, "
                      "what weight is warranted over the next 14 days?"),
        criteria={"above_baseline": "trend and risk both support a larger weight",
                  "at_baseline": "no reason to deviate from the trend rule",
                  "below_baseline": "risk or crowding argues for a smaller weight",
                  "insufficient_evidence": "the state does not support a view"})
        for i in range(1, len(COINS) + 1)]
    qs.append(JevQuestion(name="market_risk", primitive="Score",
                          instructions="Overall downside risk for this group of liquid crypto assets, next 14 days.",
                          criteria=["low", "medium", "high"]))
    qs.append(JevQuestion(name="regime_tradeable", primitive="Noul",
                          instructions="Is this a regime in which a trend-following book should be exposed at all?"))
    return qs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()

    from paper_trading.jev_decision import TypesafeJevDecisionBackend
    be = TypesafeJevDecisionBackend()
    qs = questions()
    body = be._build_request_body({"assets": features()}, qs)
    print("── 请求体 ──")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    if not a.send:
        print("\n(未发送。加 --send 发送;需要 shell 里 export JEV_API_KEY=...)")
        return 0
    key = os.environ.get("JEV_API_KEY")
    if not key:
        print("\n✗ JEV_API_KEY 不在环境变量里", file=sys.stderr)
        return 1
    # 先在本地验 key 的形状 —— 否则一个本地编码错误会被误报成「API 格式不对」。
    # 2026-09-23 第一次 --send 就是这样:key 里有非 ASCII 字符,请求根本没发出去。
    if not key.isascii() or any(ch.isspace() for ch in key) or len(key) < 16:
        print(f"\n✗ JEV_API_KEY 形状不对(长度 {len(key)},"
              f"{'含非 ASCII 字符' if not key.isascii() else '含空白或过短'})。"
              "请求没有发出。检查 export 的是不是真实 key,不是占位文字。", file=sys.stderr)
        return 1

    print(f"\n── 发送到 {be._base_url}/v1/experimental_evaluate ──")
    t0 = time.monotonic()
    try:
        resp = be._request(key, body)
    except Exception as e:                                   # noqa: BLE001
        msg = str(e)
        print(f"✗ 请求失败:{type(e).__name__}: {msg[:300]}", file=sys.stderr)
        # 三种失败修法不同,分开说,别混成一句「格式不对」
        if msg.startswith("HTTP 4"):
            print("  ⇒ 服务器拒绝了请求:401/403 看 key 和权限,404 看端点路径,400/422 看请求体格式。",
                  file=sys.stderr)
        elif msg.startswith("HTTP 5"):
            print("  ⇒ 服务器端错误,稍后重试;连续出现再查。", file=sys.stderr)
        else:
            print("  ⇒ 请求没有得到 HTTP 响应(本地错误、DNS、超时或网络)。和 API 格式无关。",
                  file=sys.stderr)
        return 1
    ms = (time.monotonic() - t0) * 1000
    print(f"HTTP 200,{ms:.0f}ms")
    print("响应顶层键:", sorted(resp) if isinstance(resp, dict) else type(resp).__name__)
    try:
        answers, tokens = be._parse_response(resp, qs)
    except Exception as e:                                   # noqa: BLE001
        print(f"✗ 响应格式和解析器不一致:{type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        print("  原始响应(前 800 字):", json.dumps(resp, ensure_ascii=False)[:800], file=sys.stderr)
        return 1
    print(f"✓ 解析通过,input_tokens={tokens}")
    print(json.dumps(answers, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

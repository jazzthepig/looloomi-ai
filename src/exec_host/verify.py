"""主机复核(台账 S-666):主机不信上游 —— 每张要下真单的进场票,在东京主机上用公开数据或 Jazz 的签名重新成立一遍。

## 为什么

计划由 Railway + Supabase 产出,主机照单执行。2026-10-21 Railway 公告存放环境变量的系统被入侵,部分变量被解密
拿走 —— 能写库的人就能往 `r_tickets_paper` 塞一张 pending 票、往 `regime_calls` 塞一条「on、3 档、战场 = 他拉盘的币」,
主机第二天就会照着下单。本模块让「能写库」最多只能让主机做一张**本来就像我们信号**的交易:

- **R-v2 票**:用 HL 公开日线把信号重算一遍(规则 V,S-666 预注册,阈值一字不改):
  V1 HL 有信号日那根 · V2 信号日及之前 ≥ 41 根 · V3 收盘 ≥ 0.99 × 前 40 根最高价 · V4 ≥ 200 根时收盘 ≥ 0.99 × SMA200 ·
  V5 HL 收盘与计划 ref_close 一致(倍数 1 / 1000 / 1/1000,误差 ≤ 3%)· V6 止损宽度 = HL 的 2.5 × ATR14 ÷ 收盘的 0.67–1.5 倍 ·
  V7 最近 30 根成交额均值 ≥ $1M(成交量全为零的回填段不查)。
- **J 票(Jazz ⓪)**:价格形态不是 J 票的理由,Jazz 的判断才是 —— 判断要带 Jazz 在自己 Mac 上的签名
  (HMAC-SHA256,密钥只在 Jazz 的 Mac 与主机上,Railway 和库里都没有)。主机只认签名里的内容,不认 Railway 的转述。
- **信心档位**:R-v2 票的 risk_mult > 1 也要来自一条签名有效、state = on 的判断;否则按 1 倍。

**S-666 判定 ❌(真票通过率 78% < 90%,几乎全栽在 V7 —— 2023 年 HL 太薄;伪造票只过 6%)⇒ 规则 V 默认只
`report`**:每张票照样复核、判定进发件箱,不拦。S-667 用前向的票判 V′(V1–V6,不含 V7):过了才改
`EXECUTOR_VERIFY=enforce`(按 V′ 拦)。**签名不受这个开关管,始终强制**:J 票没有有效签名 ⇒ 不可执行;
R-v2 票的信心倍数没有签名支撑 ⇒ 压回 1 倍。伪造的 off / flat / 离场只会让我们少做或早走 —— 方向安全,本模块不管。

全部是纯函数(没有 I/O),runner 负责取 HL 日线。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import secrets
from typing import Any, Iterable, Optional

# 规则 V(S-666 预注册,改动必须新开预注册)
TOL_PX = 0.01
LOOKBACK = 40
MIN_BARS = LOOKBACK + 1
SMA_N = 200
STOP_ATR = 2.5
ATR_N = 14
PRICE_AGREE = 0.03
SCALES = (1.0, 1000.0, 0.001)
STOP_RATIO_LO, STOP_RATIO_HI = 0.67, 1.5
ADV_N = 30
ADV_MIN_USD = 1_000_000.0
BARS_NEEDED = 260                     # 取多少根日线(SMA200 + 余量)

# ⓪ 签名
RISK_MULT = {1: 1.0, 2: 1.5, 3: 2.0}  # 与 regime_call.RISK_MULT 同一张表(测试守着)
MAX_RISK_MULT = 2.0
SIGNED_FIELDS = ("state", "conviction", "battlefield", "close", "days", "note", "signed_at", "nonce")
MAX_SIGN_SKEW_S = 300
MODES = ("enforce", "report", "off")
DEFAULT_MODE = "report"               # S-666 ❌ ⇒ report;S-667 过了才改 enforce(主机环境变量 EXECUTOR_VERIFY)


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _d(x: Any) -> Optional[dt.date]:
    if x is None or x == "":
        return None
    if isinstance(x, dt.date) and not isinstance(x, dt.datetime):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def _ts(x: Any) -> Optional[dt.datetime]:
    try:
        v = x if isinstance(x, dt.datetime) else dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


# ── HL 日线 ─────────────────────────────────────────────────────────────────────────────────────────────
def hl_bars(candles: Iterable[dict]) -> list[dict]:
    """HL `candleSnapshot`(1d)→ [{d, o, h, l, c, v}],按日期升序,同一天取最后一条。t = 开盘毫秒(UTC 日)。"""
    by_d: dict[str, dict] = {}
    for k in candles or []:
        t = _f(k.get("t"))
        o, h, l, c = (_f(k.get(x)) for x in ("o", "h", "l", "c"))
        if t is None or None in (o, h, l, c):
            continue
        d = dt.datetime.fromtimestamp(t / 1000, tz=dt.timezone.utc).date().isoformat()
        by_d[d] = {"d": d, "o": o, "h": h, "l": l, "c": c, "v": _f(k.get("v")) or 0.0}
    return [by_d[d] for d in sorted(by_d)]


def _nearest_scale(r: float) -> float:
    return min(SCALES, key=lambda s: abs(math.log(r / s))) if r > 0 else 1.0


def rv2_check(bars: list[dict], signal_d: Any, ref_close: Any, stop_frac: Any) -> dict[str, Any]:
    """规则 V。bars = hl_bars() 的输出(可以含信号日之后的根,这里只看到信号日为止)。"""
    sd = _d(signal_d)
    fails: list[str] = []
    m: dict[str, Any] = {}
    if sd is None:
        return {"ok": False, "ok_v1_6": False, "fails": ["信号日缺失"], "metrics": m}
    upto = [b for b in bars if b["d"] <= sd.isoformat()]
    if not upto or upto[-1]["d"] != sd.isoformat():
        return {"ok": False, "ok_v1_6": False, "fails": ["V1 HL 没有信号日那根日线"], "metrics": m}
    if len(upto) < MIN_BARS:
        return {"ok": False, "ok_v1_6": False, "fails": [f"V2 HL 只有 {len(upto)} 根(要 ≥ {MIN_BARS})"], "metrics": m}
    sig = upto[-1]
    c = sig["c"]
    hh = max(b["h"] for b in upto[-LOOKBACK - 1:-1])
    m.update(hl_close=c, hh40=hh, n_bars=len(upto))
    if not c >= (1 - TOL_PX) * hh:
        fails.append(f"V3 收盘 {c:.6g} 没有突破前 {LOOKBACK} 根最高 {hh:.6g}")
    if len(upto) >= SMA_N:
        sma = sum(b["c"] for b in upto[-SMA_N:]) / SMA_N
        m["sma200"] = sma
        if not c >= (1 - TOL_PX) * sma:
            fails.append(f"V4 收盘 {c:.6g} 在 SMA200 {sma:.6g} 之下")
    rc = _f(ref_close)
    if rc and rc > 0 and c > 0:
        r = c / rc
        s = _nearest_scale(r)
        m.update(price_ratio=r, scale=s)
        if abs(r / s - 1) > PRICE_AGREE:
            fails.append(f"V5 HL 收盘 {c:.6g} 与计划 ref_close {rc:.6g} 对不上(比 {r:.4g})")
    else:
        fails.append("V5 计划没有 ref_close")
    trs = []
    for i in range(len(upto) - ATR_N, len(upto)):
        b, pc = upto[i], upto[i - 1]["c"] if i > 0 else upto[i]["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    atr = sum(trs) / ATR_N
    s_hl = STOP_ATR * atr / c if c > 0 else None
    sf = _f(stop_frac)
    m.update(atr14_hl=atr, stop_frac_hl=s_hl)
    if not (sf and s_hl and s_hl > 0 and STOP_RATIO_LO <= sf / s_hl <= STOP_RATIO_HI):
        fails.append(f"V6 止损宽度 {sf} 与 HL 的 {s_hl if s_hl is None else round(s_hl, 4)} 不符")
    last = upto[-ADV_N:]
    if len(last) == ADV_N and all(b["v"] > 0 for b in last):
        adv = sum(b["v"] * b["c"] for b in last) / ADV_N
        m["adv30_usd"] = adv
        if adv < ADV_MIN_USD:
            fails.append(f"V7 HL 30 日成交额均值 ${adv:,.0f} < ${ADV_MIN_USD:,.0f}")
    # V′(S-667)= V1–V6:流动性(V7)是执行闸,不是信号复核
    return {"ok": not fails, "ok_v1_6": not [f for f in fails if not f.startswith("V7")], "fails": fails, "metrics": m}


# ── ⓪ 签名 ─────────────────────────────────────────────────────────────────────────────────────────────
def new_key() -> str:
    return secrets.token_hex(32)


def key_fingerprint(key_hex: str) -> str:
    """密钥的指纹(前 8 位),Mac 与主机对一下是不是同一把;指纹不能反推出密钥。"""
    return hashlib.sha256(("cometcloud-regime-call:" + key_hex.strip()).encode()).hexdigest()[:8]


def canonical(payload: dict) -> str:
    return json.dumps({k: payload.get(k) for k in SIGNED_FIELDS}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sign(payload: dict, key_hex: str) -> tuple[str, str]:
    """→ (signed, sig)。signed 是要原样存进库、原样交给主机的字符串。"""
    s = canonical(payload)
    return s, hmac.new(bytes.fromhex(key_hex.strip()), s.encode(), hashlib.sha256).hexdigest()


def open_signed(signed: Any, sig: Any, key_hex: Optional[str]) -> tuple[Optional[dict], str]:
    """签名对 ⇒ (签名里的判断, "");否则 (None, 原因)。"""
    if not key_hex:
        return None, "主机没有 JAZZ_CALL_KEY"
    if not signed or not sig:
        return None, "这条判断没有签名"
    try:
        want = hmac.new(bytes.fromhex(key_hex.strip()), str(signed).encode(), hashlib.sha256).hexdigest()
    except ValueError:
        return None, "JAZZ_CALL_KEY 不是十六进制"
    if not hmac.compare_digest(want, str(sig)):
        return None, "签名不对"
    try:
        p = json.loads(signed)
    except ValueError:
        return None, "签名内容不是 JSON"
    if not isinstance(p, dict) or set(p) != set(SIGNED_FIELDS):
        return None, "签名内容字段不对"
    return p, ""


def call_window(p: dict) -> tuple[Optional[dt.date], Optional[dt.datetime]]:
    """签名里的判断从哪天起管、到什么时候 —— 与 regime_call.validate_call / governing_call 同一规则。"""
    at = _ts(p.get("signed_at"))
    try:
        days = int(p.get("days"))
    except (TypeError, ValueError):
        return None, None
    if at is None or not (1 <= days <= 60):
        return None, None
    at = at.astimezone(dt.timezone.utc)
    return at.date(), at + dt.timedelta(days=days)


def governs(p: dict, day: Any) -> bool:
    eff, exp = call_window(p)
    d = _d(day)
    if eff is None or d is None:
        return False
    return eff <= d and exp > dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tzinfo=dt.timezone.utc)


def _in_list(coin: str, names: Iterable[Any]) -> bool:
    c = coin.upper()
    for n in names or []:
        u = str(n or "").strip().upper()
        if u == c or "K" + u == c or u == "K" + c:
            return True
    return False


def j_check(entry: dict, p: Optional[dict], why_unsigned: str) -> dict[str, Any]:
    if p is None:
        return {"ok": False, "fails": [f"J 票的判断没有通过签名:{why_unsigned}"]}
    fails = []
    coin = str(entry.get("coin") or entry.get("symbol") or "")
    if str(p.get("state")) != "on":
        fails.append(f"签名里的判断是 {p.get('state')},不开 J 票")
    if not _in_list(coin, p.get("battlefield") or []):
        fails.append(f"{coin} 不在签名里的战场名单 {p.get('battlefield')}")
    if not governs(p, entry.get("signal_d")):
        fails.append(f"信号日 {entry.get('signal_d')} 不在签名判断的有效期内")
    try:
        want = RISK_MULT[int(p.get("conviction"))]
    except (TypeError, ValueError, KeyError):
        want = None
    got = _f(entry.get("risk_mult")) or 1.0
    if want is None or got > want + 1e-9:
        fails.append(f"风险倍数 {got} 超过签名信心档位给的 {want}")
    return {"ok": not fails, "fails": fails}


# ── 一轮的复核 ──────────────────────────────────────────────────────────────────────────────────────────
def is_j(entry: dict) -> bool:
    return str(entry.get("ticket_id") or "").startswith("J:") or entry.get("book") == "jazz"


def review(tplan: dict, bars_by_coin: dict[str, list[dict]], coin_of: dict[str, Optional[str]],
           key_hex: Optional[str], mode: str = DEFAULT_MODE) -> tuple[dict, dict[str, Any]]:
    """纯函数。计划 → (主机真正执行的计划, 判定)。coin_of = {ticket_id: HL 币名}(resolve_coin 的结果)。

    签名(始终强制,不受 mode 管):J 票没有有效签名、或签名内容不支持这张票 ⇒ 拿掉,进 `host_rejected`;
    R-v2 票的 risk_mult 高于签名支撑的倍数 ⇒ 压回(没有有效签名 ⇒ 1 倍)。
    规则 V′(V1–V6,mode 管):enforce = 没过的 R-v2 票拿掉;report = 只记判定(含 V7,供 S-667 对账);off = 不算。"""
    if mode not in MODES:
        mode = DEFAULT_MODE
    out = dict(tplan)
    call = tplan.get("regime_call") or {}
    p, why_p = open_signed(call.get("signed"), call.get("sig"), key_hex)
    call_mult = 1.0
    if p is not None and str(p.get("state")) == "on" and governs(p, tplan.get("asof")):
        try:
            call_mult = RISK_MULT[int(p.get("conviction"))]
        except (TypeError, ValueError, KeyError):
            call_mult = 1.0
    keep, rejected, verdicts = [], [], []
    for e in tplan.get("enter") or []:
        tid = e.get("ticket_id")
        coin = coin_of.get(tid)
        if is_j(e):
            v = j_check({**e, "coin": coin or e.get("symbol")}, p, why_p)
            blocks = not v["ok"]
            e2 = e
        else:
            if coin is None or mode == "off":
                v = {"ok": True, "ok_v1_6": True, "fails": [],
                     "note": "不查(mode = off)" if mode == "off" else "HL 上没有这个永续(不可执行另有记录)"}
            else:
                v = rv2_check(bars_by_coin.get(coin) or [], e.get("signal_d"), e.get("ref_close"), e.get("stop_frac"))
            blocks = mode == "enforce" and not v.get("ok_v1_6", v["ok"])
            mult = _f(e.get("risk_mult")) or 1.0
            e2 = e if mult <= call_mult + 1e-9 else {**e, "risk_mult": call_mult,
                                                      "risk_mult_note": f"计划给 {mult},签名支撑 {call_mult}"}
        verdicts.append({"ticket_id": tid, "coin": coin, "kind": "jazz" if is_j(e) else "r_v2", "ok": v["ok"],
                         "ok_v1_6": v.get("ok_v1_6"), "blocks": blocks, "fails": v["fails"],
                         "metrics": {k: (round(x, 6) if isinstance(x, float) else x)
                                     for k, x in (v.get("metrics") or {}).items()}})
        if blocks:
            rejected.append({**e, "coin": coin, "why": "主机复核没过:" + ";".join(v["fails"])})
        else:
            keep.append(e2)
    out["enter"] = keep
    out["host_rejected"] = rejected
    summary = {"mode": mode, "call_signed": p is not None, "call_why": why_p or None, "call_mult": call_mult,
               "n": len(verdicts), "passed": sum(1 for v in verdicts if v["ok"]), "blocked": len(rejected),
               "verdicts": verdicts}
    return out, summary

"""情景台账(Jazz 11-02「利用 AI 的能力做好情景分析和模拟」;「规则是零假设,打破是实验」)—— 事前写下、事后打分。

## 为什么

情景分析不需要预测准,但情景很容易变成事后的故事。台账让「事前」可以被第三方核对:
- 每一条写下来的那一刻由**数据库**记时间(`written_at`、`d` 由触发器写,客户端给的值不算);
- 结算日 `horizon_d` 必须晚于写下的那一天;
- **只追加**:写下之后不能改、不能删(触发器拒绝 UPDATE / DELETE);进 `forward_anchor_daily`(按 `d`,键 `id`)。
打分另存 `scenario_scores`(可重算,不进锚):Brier = (概率 − 结果)²。长期的校准分数就是「我们的概率是校准的」这句话的证据 ——
可以公开验证、又不承诺任何收益。

## 一条情景

`id`(唯一,如 `E53`、`R1-A`)· `author`(seth-weekly / jazz / ai:<模型> / lane-a …)· `scenario`(属于哪个情景 / 分支)·
`statement`(人读的一句话)· `variable` + `op` + `lo` / `hi`(机器能核的命题)· `prob`(这条命题为真的概率)· `horizon_d`(哪天的值)。

`variable` 能自动结算的三类(其余写 `manual`,人工结算):
- `close:<SYMBOL>` —— `ohlcv_daily` 当天收盘(加密 binance_hist,其余 eodhd);
- `state:<feature>` —— `state_daily`(entity = panel)当天的值;
- `macro:<series>` —— `macro_daily` 当天或之前 7 天内最近一个值;
- `high:<SYMBOL>[@HH]` / `low:<SYMBOL>[@HH]`(T-409,11-15)—— **走法**:从这条写下的那一刻(`written_at`,向上取整点)
  到结算日 HH:00 UTC(不写 @HH = 当天 24:00)之间 `ohlcv_hourly`(binance_hist)的最高价 / 最低价。
  「周一 13:00 前碰到 1,834」= `high:ETH@13`、`gt`、`lo = 1834`、`horizon_d` = 那个周一。小时线没覆盖到截止时刻 ⇒ 等值。
`op`:`between`(lo ≤ x ≤ hi)、`gt`(x > lo)、`lt`(x < hi)。结算日过了 7 天还没有值 ⇒ 记「读不到」,结果留空(不当成假)。

## lane 也是作者(11-02 第二批,S-705)

A / B / C 交研究卡时,把对结果的前向预期写成 `docs/research/scenarios/<lane>-T-NNN.json`(格式见那个目录的 README),
随分支一起进 PR;Seth 合并 = 闸门;Railway 部署后 `ingest_repo` 把还没入账的条目写进台账 —— `d` 由库记成入账那天,
所以 lane 给的结算日要留足余量(≥ 入账后 7 天)。作者取文件里的 `author`(只认 lane-a/b/c、seth*、jazz、ai:*),
之后 `calibration` 按作者分开算 Brier:**三个 lane 的「概率说得准不准」从此是量出来的,不是感觉。**

## 人工命题的结算(11-12)—— 之前没有这条路

`variable = manual` 的命题占台账 45%(11-12 实测 628 条里 285 条,首批 11-21 到期),而写入端只结自动的三类 ⇒
最具体的那一半研究命题永远不会被打分,「按作者的校准」只量得到价格命题。现在:结算记录写成
`docs/research/scenarios/settlements/*.json`(`{"settled_by": "lane-b", "settlements": [{"id", "observed", "evidence"}]}`),
随分支进 PR,Seth 合并 = 闸门,部署后入账。三条纪律(`settle_manual`):
- 结算人只交**观测值 + 证据**(脚本路径 / SQL + 数);成没成由**登记时**的 op / lo / hi 算,不由结算人说;
- **不结自己的**:结算人与作者不能是同一方(lane-b 不结 lane-b 的;seth 的由 lane 结);
- 到期之后才能结;结过的不重结(要改 = 另立更正,不覆盖)。

判活:`select count(*) from scenario_ledger` 只增不减;`loop_attempt` 里 `_scenario_ledger_loop` 每小时一条。

## 作废:「这条登记本身是错的」(11-23,T-427)—— 结算之外的第三类记录

台账只追加、不可改 —— 那是对的(事前写下的东西不能改),但对**登记错误**是错的:一条登记错了的命题进了池子就再也出不来,
它会被自动结算成一个看起来很正常的 `outcome`,并被算进作者的命中率与 Brier ⇒ 校准(这套装置里唯一的自我纠错信号)被污染。
所以加第三类记录:`docs/research/scenarios/voids/*.json`,形状 `{"voided_by": "<作者>", "voids": [{"id", "reason", "evidence", "superseded_by"}]}`,
由 **Seth / Jazz / ai:** 写 —— 作废是**登记错误的更正**,作者本人不能给自己的命题判死刑(同 `settle_manual` 的 `party()` 规则)。

**作废 ≠ 结算**:结算 = 命题为真/为假(记 `outcome` + `brier`);作废 = 这条登记**从来不是一条有效的前向命题**。
所以作废行 `observed=null, outcome=null, brier=null`,只留一行标记 ⇒ 不进校准、不会被结算、不再被算成「该结了」。
台账一行都不动(触发器本来就拒绝 UPDATE/DELETE);**不需要 DDL**(`scenario_scores` 那三列可空)⇒ 不改 `migrations/`。
- `reason` 是**闭集**(`VOID_REASONS`):闭集里没有「被证伪」—— 被证伪只能走结算。
- 三条纪律:① 不能自己作废自己(`party()`);② **已结的不能作废**(结算是不可改的历史事实,作废擦不掉它);
  ③ 台账行永不删改(只写 `scenario_scores` 的一行标记)。
- 机器怎么认出作废行:唯一通道是 `note` 的**稳定前缀** + 纯函数 `is_void(row)`;所有消费点一律调它(不做自由文本匹配)。
- 台账里没有的 id(`scenario_scores.id` 外键指向 `scenario_ledger.id`)**不写行,只点名** —— 补登记就是造一条事前的假记录。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

TABLE = "scenario_ledger"
SCORES = "scenario_scores"
WRITES_TABLES = (TABLE, SCORES)
WRITES_COLUMNS = {TABLE: ("id", "d", "author", "scenario", "statement", "variable", "op", "lo", "hi", "prob", "horizon_d",
                          "code_ref"),
                  SCORES: ("id", "scored_at", "observed", "outcome", "brier", "note", "code_ref")}
CODE_REF = "scenario_ledger v1.1 (11-15: + high / low 走法命题,T-409)"
OPS = ("between", "gt", "lt")
KINDS = ("close", "state", "macro", "high", "low", "manual")
PATH_KINDS = ("high", "low")
LATE_DAYS = 7
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_AUTHOR = re.compile(r"^(?:lane-[abc]|seth(?:[:-][\w.-]+)?|jazz|ai:[\w.-]+)$")
SCENARIO_DIR = "docs/research/scenarios"
SETTLE_DIR = SCENARIO_DIR + "/settlements"
VOID_DIR = SCENARIO_DIR + "/voids"
CODE_REF_MANUAL = "scenario_ledger v1 manual (11-12)"
CODE_REF_VOID = "scenario_ledger v1.2 void (11-23: 作废标记层,T-427)"
MIN_EVIDENCE = 12
VOID_NOTE_PREFIX = "作废 · "                     # 唯一通道:note 的稳定前缀 ⇒ is_void(row)
VOID_REASONS = ("defective_threshold",           # 阈值取错对象(如 BO20 触发价当现价)
                "defective_base_rate",           # 基率窗口与到期日不对齐
                "complement_pair",               # 与另一条互为补集 ⇒ 有一半注定错
                "not_machine_checkable",          # 量不出一个数
                "duplicate_id",                   # 与别的 id 重复
                "superseded")                     # 被新 id 接替(必须写 superseded_by)
_VOIDER = re.compile(r"^(?:seth(?:[:-][\w.-]+)?|jazz)$")   # 作废只能由 seth / jazz 写(ai:* 不认 —— lane 能自称 ai:,§Seth-1123x)


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def parse_variable(v: str) -> tuple[str, str]:
    """`close:BTC` → (close, BTC);`manual` → (manual, "")。认不出 ⇒ ValueError。"""
    v = str(v or "").strip()
    if v == "manual":
        return "manual", ""
    kind, _, key = v.partition(":")
    if kind not in KINDS or kind == "manual" or not key:
        raise ValueError(f"variable {v!r} 认不出(close:<SYMBOL> / state:<feature> / macro:<series> / high:<SYMBOL>[@HH] / low:<SYMBOL>[@HH] / manual)")
    if kind in PATH_KINDS:
        sym, _, hh = key.partition("@")
        if not sym or (hh and not (hh.isdigit() and 0 <= int(hh) <= 23)):
            raise ValueError(f"variable {v!r}:走法命题写成 {kind}:<SYMBOL> 或 {kind}:<SYMBOL>@HH(HH = 0–23,UTC)")
    return kind, key


def path_window(key: str, horizon_d: str, written_at: Any) -> tuple[str, dt.datetime, dt.datetime]:
    """纯函数。走法命题的窗口:(标的, 起点, 截止)。起点 = 写下那一刻向上取整点(写下之前的小时不算);截止 = 结算日 HH:00(缺省次日 00:00)。"""
    sym, _, hh = key.partition("@")
    w = written_at if isinstance(written_at, dt.datetime) else dt.datetime.fromisoformat(str(written_at).replace("Z", "+00:00"))
    w = w.astimezone(dt.timezone.utc)
    start = w.replace(minute=0, second=0, microsecond=0) + (dt.timedelta(hours=1) if (w.minute or w.second or w.microsecond) else dt.timedelta())
    day = dt.datetime.combine(dt.date.fromisoformat(str(horizon_d)[:10]), dt.time(), dt.timezone.utc)
    end = day + (dt.timedelta(hours=int(hh)) if hh else dt.timedelta(days=1))
    return sym, start, end


def holds(op: str, lo: Optional[float], hi: Optional[float], x: float) -> bool:
    """纯函数。命题在值 x 上成立吗。"""
    if op == "between":
        return lo <= x <= hi
    if op == "gt":
        return x > lo
    if op == "lt":
        return x < hi
    raise ValueError(op)


def brier(prob: float, outcome: bool) -> float:
    return round((float(prob) - (1.0 if outcome else 0.0)) ** 2, 6)


def validate(e: dict, today: dt.date) -> list[str]:
    """纯函数。一条情景的问题清单(空 = 能写)。触发器在库里再守一遍时间与 op 的约束。"""
    why = []
    if not _ID.match(str(e.get("id") or "")):
        why.append("id 要 1–64 位字母数字(可含 _ . : -)")
    for k in ("author", "scenario", "statement"):
        if not str(e.get(k) or "").strip():
            why.append(f"缺 {k}")
    try:
        parse_variable(e.get("variable"))
    except ValueError as ex:
        why.append(str(ex))
    op, lo, hi, p = e.get("op"), _f(e.get("lo")), _f(e.get("hi")), _f(e.get("prob"))
    if op not in OPS:
        why.append(f"op 要是 {OPS}")
    elif op == "between" and (lo is None or hi is None or lo > hi):
        why.append("between 要 lo ≤ hi")
    elif op == "gt" and lo is None:
        why.append("gt 要 lo")
    elif op == "lt" and hi is None:
        why.append("lt 要 hi")
    if p is None or not 0 <= p <= 1:
        why.append("prob 要在 [0, 1]")
    try:
        h = dt.date.fromisoformat(str(e.get("horizon_d"))[:10])
        if h <= today:
            why.append(f"horizon_d {h} 要晚于今天 {today}(事前写下)")
    except ValueError:
        why.append("horizon_d 要是日期")
    return why


def row_for(e: dict, author: str) -> dict:
    return {"id": str(e["id"]), "d": dt.datetime.now(dt.timezone.utc).date().isoformat(),   # 触发器会用库的时间覆盖
            "author": author, "scenario": str(e["scenario"])[:200], "statement": str(e["statement"])[:500],
            "variable": str(e["variable"]).strip(), "op": e["op"], "lo": _f(e.get("lo")), "hi": _f(e.get("hi")),
            "prob": _f(e["prob"]), "horizon_d": str(e["horizon_d"])[:10], "code_ref": CODE_REF}


def score(entry: dict, value: Optional[float], today: dt.date) -> Optional[dict]:
    """纯函数。到期的一条 + 当天的值 → 一行打分;还没到 / 还在等值 ⇒ None;过了宽限还没有值 ⇒ 写「读不到」、结果留空。"""
    h = dt.date.fromisoformat(str(entry["horizon_d"])[:10])
    if h >= today:
        return None
    base = {"id": entry["id"], "code_ref": CODE_REF}
    if value is None:
        if (today - h).days <= LATE_DAYS:
            return None
        return {**base, "observed": None, "outcome": None, "brier": None,
                "note": f"结算日 {h} 过了 {LATE_DAYS} 天仍读不到 {entry['variable']} —— 不当成假"}
    ok = holds(entry["op"], _f(entry.get("lo")), _f(entry.get("hi")), value)
    return {**base, "observed": value, "outcome": ok, "brier": brier(entry["prob"], ok), "note": None}


def party(author: Any) -> str:
    """纯函数。作者属于哪一方:`seth:cycle-space` → seth,`ai:MiniMax-M3` → ai,`lane-b` → lane-b。"""
    a = str(author or "").strip()
    return "seth" if a.startswith("seth") else a.split(":", 1)[0]


def is_void(row: Any) -> bool:
    """纯函数。这一行是不是「作废标记」行。

    唯一通道:`note` 的**稳定前缀**(`VOID_NOTE_PREFIX`)。不做自由文本 `in` 匹配 ——
    一句结算说明里恰好写了「作废」两个字,不该把那条结算行变成作废行。所有消费点一律调这个函数。"""
    if not isinstance(row, dict):
        return False
    return str(row.get("note") or "").startswith(VOID_NOTE_PREFIX)


def settle_manual(entry: Optional[dict], s: dict, settled_by: str, today: dt.date) -> tuple[Optional[dict], Optional[str]]:
    """纯函数。一条 manual 命题 + 一条结算记录 → (打分行, None) 或 (None, 拒绝理由)。
    结算人只给观测值与证据;结果由登记时的 op / lo / hi 算。不结自己的;没到期不结。"""
    sid = str(s.get("id") or "")
    if not entry:
        return None, f"{sid}: 台账里没有这条"
    if str(entry.get("variable")) != "manual":
        return None, f"{sid}: 不是 manual 命题(自动命题由系统结)"
    if not _AUTHOR.match(str(settled_by or "")):
        return None, f"{sid}: settled_by {settled_by!r} 不认"
    if party(settled_by) == party(entry.get("author")):
        return None, f"{sid}: {settled_by} 不能结 {entry.get('author')} 自己写的命题"
    h = dt.date.fromisoformat(str(entry["horizon_d"])[:10])
    if h >= today:
        return None, f"{sid}: 结算日 {h} 还没过"
    x = _f(s.get("observed"))
    if x is None:
        return None, f"{sid}: observed 要是一个数"
    ev = str(s.get("evidence") or "").strip()
    if len(ev) < MIN_EVIDENCE:
        return None, f"{sid}: evidence 要写出怎么量的(脚本路径 / SQL + 数)"
    ok = holds(entry["op"], _f(entry.get("lo")), _f(entry.get("hi")), x)
    return {"id": sid, "observed": x, "outcome": ok, "brier": brier(float(entry["prob"]), ok),
            "note": f"人工结算 · {settled_by} · {ev[:300]}", "code_ref": CODE_REF_MANUAL}, None


def void_marker(v: dict, entry: Optional[dict], settled: bool, voided_by: str) -> dict[str, Any]:
    """纯函数。一条作废记录 + 台账里那一条(没有 = `None`)+ 该 id 是否已结算 → {"status", "row", "why"}。

    作废 = 这条登记**本身是错的**(它从来不是一条有效的前向命题)⇒ `outcome` / `brier` 留空,只留一行标记。
    三条纪律:① 不能自己作废自己(`party()`);② 已结的不能作废(结算是不可改的历史事实);③ 台账行一行都不动。
    `status`:`ok` / `rejected`(带 why)/ `not_in_ledger`(台账里没这条 ⇒ 没有行可挂,只点名)。"""
    sid = str(v.get("id") or "")
    if not _ID.match(sid):
        return {"status": "rejected", "row": None, "why": "id 要 1–64 位字母数字(可含 _ . : -)"}
    reason = str(v.get("reason") or "")
    if reason not in VOID_REASONS:
        return {"status": "rejected", "row": None,
                "why": f"reason {reason!r} 不在闭集里(只能是 {', '.join(VOID_REASONS)})—— "
                       f"命题被证伪是**结算**,不是作废"}
    ev = str(v.get("evidence") or "").strip()
    if len(ev) < MIN_EVIDENCE:
        return {"status": "rejected", "row": None, "why": "evidence 要写出怎么核的(脚本路径 / SQL + 数)"}
    if not _VOIDER.match(str(voided_by or "")):
        return {"status": "rejected", "row": None,
                "why": f"voided_by {voided_by!r} 不认 —— 作废是登记错误的更正,只能由 seth / jazz 写"
                       f"(lane 不能作废任何人的条目,否则就能把自己的失败样本从校准里拿掉)"}
    sup = str(v.get("superseded_by") or "").strip()
    if reason == "superseded" and not sup:
        return {"status": "rejected", "row": None, "why": "reason=superseded ⇒ 要写 superseded_by(接替它的新 id)"}
    if sup and (not _ID.match(sup) or sup == sid):
        return {"status": "rejected", "row": None, "why": "superseded_by 要是另一个合法 id"}
    if entry is None:
        return {"status": "not_in_ledger", "row": None,
                "why": "台账里没有这条 id ⇒ 没有行可挂(scenario_scores.id 外键指向 scenario_ledger.id);只点名,不写行"}
    if party(voided_by) == party(entry.get("author")):
        return {"status": "rejected", "row": None,
                "why": f"{voided_by} 不能作废 {entry.get('author')} 自己写的条目"}
    if settled:
        return {"status": "rejected", "row": None,
                "why": "已结的不能作废 —— 结算是不可改的历史事实,作废擦不掉它"}
    note = f"{VOID_NOTE_PREFIX}{voided_by} · {reason} · {ev[:300]}"
    if sup:
        note += f" · 接替 {sup}"
    return {"status": "ok", "why": None,
            "row": {"id": sid, "observed": None, "outcome": None, "brier": None, "note": note, "code_ref": CODE_REF_VOID}}


def open_manual(entries: list[dict], scores: dict[str, dict], today: dt.date) -> dict[str, Any]:
    """纯函数。还没结的 manual 命题,按作者方:已到期几条(该结了)、30 天内到期几条。
    作废的条目(`is_void`)不算「该结了」—— 它从来不是一条有效的命题,结它只会把错误写进历史。"""
    out: dict[str, dict] = {}
    for e in entries:
        s = scores.get(e["id"]) or {}
        if str(e.get("variable")) != "manual" or s.get("outcome") is not None or is_void(s):
            continue
        h = dt.date.fromisoformat(str(e["horizon_d"])[:10])
        a = out.setdefault(party(e.get("author")), {"overdue": 0, "due_30d": 0, "later": 0})
        a["overdue" if h < today else "due_30d" if (h - today).days <= 30 else "later"] += 1
    return out


def calibration(entries: list[dict], scores: dict[str, dict]) -> dict[str, Any]:
    """纯函数。按作者:已结算条数、平均 Brier、命中率、五档可靠性(说 X% 的那些,实际成了几成)。"""
    out: dict[str, Any] = {}
    for e in entries:
        s = scores.get(e["id"])
        if not s or s.get("outcome") is None:
            continue
        a = out.setdefault(e["author"], {"n": 0, "brier_sum": 0.0, "hits": 0, "buckets": {}})
        a["n"] += 1
        a["brier_sum"] += float(s["brier"])
        a["hits"] += 1 if s["outcome"] else 0
        b = min(4, int(float(e["prob"]) * 5))
        bk = a["buckets"].setdefault(f"{b * 20}-{b * 20 + 20}%", {"n": 0, "true": 0})
        bk["n"] += 1
        bk["true"] += 1 if s["outcome"] else 0
    for a in out.values():
        a["mean_brier"] = round(a.pop("brier_sum") / a["n"], 4)
        a["hit_rate"] = round(a["hits"] / a["n"], 4)
    return out


async def submit(entries: list[dict], author: str, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """写入一批(只追加)。任何一条有问题 ⇒ 整批不写,返回每条的原因。"""
    from src.api.store import supabase_insert_table
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).date()
    if not entries or len(entries) > 50:
        return {"ok": False, "why": "一批 1–50 条"}
    entries = [{**e, "author": author} if isinstance(e, dict) else {} for e in entries]   # 作者由调用方(token)定,不由正文定
    bad = {str(e.get("id")): w for e in entries if (w := validate(e, today))}
    ids = [str(e.get("id")) for e in entries]
    if len(set(ids)) != len(ids):
        bad["_batch"] = ["同一批里 id 重复"]
    if bad:
        return {"ok": False, "why": "有问题的条目 —— 整批不写", "problems": bad}
    res = await supabase_insert_table(TABLE, [row_for(e, author) for e in entries])
    if not res.ok:
        return {"ok": False, "why": f"写入失败(id 已存在 / 结算日不晚于今天 都会被库拒):{(res.why or '')[:300]}"}
    return {"ok": True, "written": len(entries), "ids": ids}


async def _value(kind: str, key: str, d: str, written_at: Any = None) -> Optional[float]:
    from src.data.style.header import _read_all
    if kind in PATH_KINDS:
        if not written_at:
            return None
        sym, start, end = path_window(key, d, written_at)
        if end <= start:
            return None
        rows = await _read_all("ohlcv_hourly", {"select": "ts,high,low", "symbol": f"eq.{sym}", "source": "eq.binance_hist",
                                                "and": f"(ts.gte.{start.isoformat()},ts.lt.{end.isoformat()})", "order": "ts.asc"})
        rows = [r for r in rows if _f(r.get("high")) is not None and _f(r.get("low")) is not None]
        if not rows:
            return None
        last = dt.datetime.fromisoformat(str(rows[-1]["ts"]).replace("Z", "+00:00"))
        if last + dt.timedelta(hours=1) < end:                            # 小时线还没覆盖到截止时刻 ⇒ 等值
            return None
        return max(float(r["high"]) for r in rows) if kind == "high" else min(float(r["low"]) for r in rows)
    if kind == "close":
        for src in ("binance_hist", "eodhd"):
            rows = await _read_all("ohlcv_daily", {"select": "close", "symbol": f"eq.{key}", "source": f"eq.{src}",
                                                   "trade_date": f"eq.{d}", "limit": "1"})
            if rows and _f(rows[0].get("close")) is not None:
                return float(rows[0]["close"])
        return None
    if kind == "state":
        rows = await _read_all("state_daily", {"select": "value", "entity": "eq.panel", "feature": f"eq.{key}",
                                               "d": f"eq.{d}", "limit": "1"})
        return _f(rows[0].get("value")) if rows else None
    if kind == "macro":
        lo = (dt.date.fromisoformat(d) - dt.timedelta(days=LATE_DAYS)).isoformat()
        rows = await _read_all("macro_daily", {"select": "d,value", "series": f"eq.{key}", "d": f"lte.{d}",
                                               "order": "d.desc", "limit": "1"})
        return _f(rows[0].get("value")) if rows and str(rows[0].get("d"))[:10] >= lo else None
    return None


def repo_files(root: Optional[str] = None) -> list[dict]:
    """纯读。`docs/research/scenarios/*.json` → [{file, author, entries, problems}];坏文件只报不抛。"""
    import json
    from pathlib import Path
    base = Path(root) if root else Path(__file__).resolve().parents[3]
    out = []
    for f in sorted((base / SCENARIO_DIR).glob("*.json")):
        rec: dict[str, Any] = {"file": f.name, "author": None, "entries": [], "problems": []}
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            rec["problems"].append(f"读不了:{e}")
            out.append(rec)
            continue
        author = str((j or {}).get("author") or "")
        if not _AUTHOR.match(author):
            rec["problems"].append(f"author {author!r} 不认(lane-a/b/c、seth…、jazz、ai:…)")
        elif not isinstance(j.get("entries"), list):
            rec["problems"].append("entries 要是列表")
        else:
            rec["author"], rec["entries"] = author, [e for e in j["entries"] if isinstance(e, dict)]
        out.append(rec)
    return out


def settlement_files(root: Optional[str] = None) -> list[dict]:
    """纯读。`docs/research/scenarios/settlements/*.json` → [{file, settled_by, settlements, problems}];坏文件只报不抛。"""
    import json
    from pathlib import Path
    base = Path(root) if root else Path(__file__).resolve().parents[3]
    out = []
    for f in sorted((base / SETTLE_DIR).glob("*.json")):
        rec: dict[str, Any] = {"file": f.name, "settled_by": None, "settlements": [], "problems": []}
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            rec["settled_by"] = str((j or {}).get("settled_by") or "")
            rec["settlements"] = [x for x in (j.get("settlements") or []) if isinstance(x, dict)]
        except (OSError, ValueError, AttributeError) as e:
            rec["problems"].append(f"读不了:{e}")
        out.append(rec)
    return out


def void_files(root: Optional[str] = None) -> list[dict]:
    """纯读。`docs/research/scenarios/voids/*.json` → [{file, voided_by, voids, problems}];坏文件只报不抛。"""
    import json
    from pathlib import Path
    base = Path(root) if root else Path(__file__).resolve().parents[3]
    out = []
    for f in sorted((base / VOID_DIR).glob("*.json")):
        rec: dict[str, Any] = {"file": f.name, "voided_by": None, "voids": [], "problems": []}
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            rec["voided_by"] = str((j or {}).get("voided_by") or "")
            rec["voids"] = [x for x in (j.get("voids") or []) if isinstance(x, dict)]
        except (OSError, ValueError, AttributeError) as e:
            rec["problems"].append(f"读不了:{e}")
        out.append(rec)
    return out


async def _voided_ids() -> set[str]:
    """库里被作废的 id。唯一通道:`note` 的稳定前缀 ⇒ `is_void`(不做自由文本匹配)。
    只读 `note` 非空的行(结算行也带 note,再由 `is_void` 挑出作废行)。"""
    from src.data.style.header import _read_all
    rows = await _read_all(SCORES, {"select": "id,note", "note": "not.is.null", "order": "id.asc"})
    return {str(r["id"]) for r in rows if is_void(r)}


async def apply_settlements(today: dt.date, root: Optional[str] = None) -> dict[str, Any]:
    """仓库里的人工结算记录 → `scenario_scores`(只写还没结的;被拒的只报)。
    **作废的条目不结**(消费点之二):作废行的 `outcome` 是 null,不在 `done` 里 ⇒ 不显式跳过就会被这次结算整行覆盖掉。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    files = settlement_files(root)
    want = {str(x.get("id")) for rec in files for x in rec["settlements"] if x.get("id")}
    if not want:
        return {"files": len(files), "settled": 0, "skipped_void": []}
    entries = {r["id"]: r for r in await _read_all(TABLE, {"select": "id,author,variable,op,lo,hi,prob,horizon_d",
                                                         "variable": "eq.manual", "order": "id.asc"})}
    done = {r["id"] for r in await _read_all(SCORES, {"select": "id", "outcome": "not.is.null", "order": "id.asc"})}
    voided = await _voided_ids()
    rows, rejected, skipped = {}, [], []
    for rec in files:
        rejected += [f"{rec['file']}: {p}" for p in rec["problems"]]
        for x in rec["settlements"]:
            sid = str(x.get("id") or "")
            if sid in voided:
                skipped.append(sid)
                continue
            if sid in done or sid in rows:
                continue
            row, why = settle_manual(entries.get(sid), x, rec["settled_by"], today)
            if row:
                rows[sid] = row
            else:
                rejected.append(f"{rec['file']}/{why}")
    if rows and not await supabase_upsert_table(SCORES, list(rows.values()), on_conflict="id"):
        return {"files": len(files), "settled": 0, "rejected": rejected[:20], "skipped_void": sorted(set(skipped)),
                "why": f"写 {SCORES} 失败"}
    return {"files": len(files), "settled": len(rows), "rejected": rejected[:20], "skipped_void": sorted(set(skipped))}


async def apply_voids(today: dt.date, root: Optional[str] = None) -> dict[str, Any]:
    """仓库里的作废记录 → `scenario_scores` 的**标记行**(只写台账里有的、还没结的)。

    三类分开报:**已写标记行**(`written`)/ **被拒**(带理由,`rejected`)/ **不在台账**(只点名 + 为什么,`not_in_ledger`)。
    台账一行都不动(触发器拒绝 UPDATE/DELETE);作废行的 `observed/outcome/brier` 全空 ⇒ 不进校准、不会再被结算。
    幂等:同一条记录跑两次不报错、不重写(第二次进 `already`)。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    files = void_files(root)
    want = {str(x.get("id")) for rec in files for x in rec["voids"] if x.get("id")}
    if not want:
        return {"as_of": today.isoformat(), "files": len(files), "voided": 0, "written": [], "already": [],
                "rejected": [], "not_in_ledger": []}
    entries = {r["id"]: r for r in await _read_all(TABLE, {"select": "id,author", "order": "id.asc"})}
    scores = {r["id"]: r for r in await _read_all(SCORES, {"select": "id,outcome,note", "order": "id.asc"})}
    settled = {i for i, r in scores.items() if r.get("outcome") is not None}
    already = {i for i, r in scores.items() if is_void(r)}
    rows: dict[str, dict] = {}
    written, rejected, missing = [], [], []
    for rec in files:
        rejected += [f"{rec['file']}: {p}" for p in rec["problems"]]
        for v in rec["voids"]:
            sid = str(v.get("id") or "")
            if sid in rows or sid in already:
                continue                                    # 幂等:已经作废过,不重写
            res = void_marker(v, entries.get(sid), sid in settled, rec["voided_by"])
            if res["status"] == "ok":
                rows[sid] = res["row"]
                written.append(sid)
            elif res["status"] == "not_in_ledger":
                if sid not in {m["id"] for m in missing}:
                    missing.append({"id": sid, "why": res["why"]})
            else:
                rejected.append(f"{rec['file']}/{sid}: {res['why']}")
    if rows and not await supabase_upsert_table(SCORES, list(rows.values()), on_conflict="id"):
        return {"as_of": today.isoformat(), "files": len(files), "voided": 0, "written": [], "already": sorted(already & want),
                "rejected": rejected[:20], "not_in_ledger": missing, "why": f"写 {SCORES} 失败"}
    return {"as_of": today.isoformat(), "files": len(files), "voided": len(rows) + len(already & want),
            "written": written, "already": sorted(already & want), "rejected": rejected[:20], "not_in_ledger": missing}


async def ingest_repo(today: dt.date, root: Optional[str] = None) -> dict[str, Any]:
    """仓库里 lane 写的情景文件 → 台账(只写还没入账的 id;过期 / 不合格的只报)。"""
    from src.data.style.header import _read_all
    files = repo_files(root)
    if not files:
        return {"files": 0, "written": 0}
    have = {r["id"] for r in await _read_all(TABLE, {"select": "id"})}
    written, skipped = 0, []
    for rec in files:
        skipped += [f"{rec['file']}: {p}" for p in rec["problems"]]
        new = [e for e in rec["entries"] if str(e.get("id")) not in have]
        good = [e for e in new if not validate({**e, "author": rec["author"]}, today)]
        skipped += [f"{rec['file']}/{e.get('id')}: {'; '.join(validate({**e, 'author': rec['author']}, today))}"
                    for e in new if e not in good]
        if good:
            r = await submit(good, rec["author"], dt.datetime.combine(today, dt.time(), dt.timezone.utc))
            if r.get("ok"):
                written += r["written"]
            else:
                skipped.append(f"{rec['file']}: {r.get('why')}")
    return {"files": len(files), "written": written, "skipped": skipped[:20]}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """① 仓库里的情景文件入账 ② 应用作废记录 ③ 结算所有到期、还没结的自动命题。

    **作废排在结算前面**:同一轮里既有作废记录又有结算记录时,作废先落 ⇒ 那条 id 这一轮不会被结掉。
    **作废的行不会被自动结算覆盖**(消费点之一):作废行的 `outcome` 是 null,不在 `done` 里 ⇒ 必须显式跳过,
    否则到期那天 `upsert(on_conflict="id")` 会把作废标记整行盖掉,登记错误又回到池子里。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).date()
    ingested = await ingest_repo(today)
    voids = await apply_voids(today)
    manual = await apply_settlements(today)
    due = await _read_all(TABLE, {"select": "id,variable,op,lo,hi,prob,horizon_d,written_at", "horizon_d": f"lt.{today.isoformat()}",
                                  "variable": "neq.manual", "order": "horizon_d.asc"})
    if not due:
        return {"ok": True, "status": "skipped" if not manual.get("settled") else "ok", "ingested": ingested, "manual": manual,
                "voids": voids, "why": f"没有到期的自动命题;人工结算 {manual.get('settled', 0)} 条,作废 {voids.get('voided', 0)} 条"}
    done = {r["id"] for r in await _read_all(SCORES, {"select": "id", "outcome": "not.is.null"})}
    voided = await _voided_ids()
    rows, waiting = [], 0
    for e in due:
        if e["id"] in done or e["id"] in voided:
            continue
        kind, key = parse_variable(e["variable"])
        s = score(e, await _value(kind, key, str(e["horizon_d"])[:10], e.get("written_at")), today)
        if s is None:
            waiting += 1
        else:
            rows.append(s)
    if rows:
        w = await supabase_upsert_table(SCORES, rows, on_conflict="id")
        if not w:
            return {"ok": False, "why": f"写 {SCORES} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "scored": len(rows), "waiting": waiting, "ingested": ingested, "manual": manual, "voids": voids,
            "why": f"结算 {len(rows)} 条,等值 {waiting} 条,入账 {ingested.get('written', 0)} 条,"
                   f"人工结算 {manual.get('settled', 0)} 条,作废 {voids.get('voided', 0)} 条"}

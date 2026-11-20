"""按键翻页(T-379 下半张):读出来的行数、内容、顺序**不许变**,只有翻页方式变。

OFFSET 翻页读 N 行要走过的行数是 N²/(2×每页行数)量级 —— 第 k 页要把前 k×每页 行重走一遍。
按键翻页用上一页最后一行的排序键接着读,不用 OFFSET。**但键不唯一就会漏行** —— 同一键的两行,
一页只带走一行。这份测试把三件事钉住:

① 键唯一时按键读到的行**逐行相同、顺序相同**于 OFFSET 读;
② 键不唯一 / 调用点自带 `or=` 过滤 ⇒ 老老实实留在 OFFSET 版;
③ 键值不适合做谓词时中途退回 OFFSET ⇒ 一行不少、一行不重。

护栏:`tests/test_read_all_paging.py` 的「服务端上限低于我们以为的」那条不许删。
"""
import asyncio
import re

from src.data.style import header as hd


class _RD:
    def __init__(self, rows=None, reason=None):
        self.rows, self.reason, self.ok = rows, reason, rows is not None


# ── 一个像 PostgREST 的假服务端 ───────────────────────────────────────────

def _split_top(s: str) -> list[str]:
    """按顶层逗号切(括号里的逗号不算)。"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


#: 叶子的值里不许有逗号和括号 —— 否则 `(a.gt.X,and(...))` 会被整条当成一个叶子。
_LEAF = re.compile(r"^([A-Za-z_]\w*)\.(eq|gt|lt|gte|lte)\.([^(),]+)$")


def _parse_node(text: str):
    """'(a.gt.X,and(a.eq.X,b.gt.Y))' ⇒ 树;叶子是 (col, op, value)。

    PostgREST 的 `or=(a,b,c)` 是**顶层 OR 列表** —— 逗号分隔的每一项是「或」的一支。
    `and(...)` / `or(...)` 是函数节点。
    """
    s = text.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    m = _LEAF.match(s)
    if m:
        return (m.group(1), m.group(2), m.group(3))
    if re.match(r"^[a-z_]+\(", s):
        name = s[:s.index("(")].strip()
        raw = s[s.index("(") + 1:s.rindex(")")]
        return (name, [_parse_node(a) for a in _split_top(raw)])
    parts = _split_top(s)
    if len(parts) == 1:
        return _parse_node(parts[0])
    return ("or", [_parse_node(p) for p in parts])


def _cmp(left, op, right) -> bool:
    if op == "eq":
        return str(left) == right
    if op == "gte":
        return str(left) >= right
    if op == "lte":
        return str(left) <= right
    if op == "gt":
        return str(left) > right
    if op == "lt":
        return str(left) < right
    raise AssertionError(op)


def _eval(node, row) -> bool:
    if len(node) == 3:
        return _cmp(row.get(node[0]), node[1], node[2])
    name, kids = node
    if name == "and":
        return all(_eval(k, row) for k in kids)
    if name == "or":
        return any(_eval(k, row) for k in kids)
    raise AssertionError(name)


def _sort_key(order: str):
    cols = []
    for piece in (order or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        col, _, direction = piece.rpartition(".")
        cols.append((col, direction or "asc"))

    def key(row):
        out = []
        for col, direction in cols:
            v = row.get(col)
            out.append((v is None, str(v) if direction == "asc" else _invert(str(v))))
        return tuple(out)
    return key


def _invert(text: str) -> str:
    """desc 排序:用一个取反的键。数字与日期字符串都能比 —— 这里只造测试数据。"""
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in text)


class _Fake:
    """按 offset/limit/or=/等值过滤给行 —— 够用的 PostgREST 替身。"""

    def __init__(self, rows, cap=10_000):
        self.rows, self.cap, self.calls = rows, cap, []

    async def __call__(self, table, params):
        self.calls.append(dict(params))
        rows = list(self.rows)
        for key, value in params.items():
            if key in ("select", "order", "limit", "offset", "or"):
                continue
            op, _, val = value.partition(".")
            if op == "in":
                wanted = {v.strip() for v in val.strip("()").split(",")}
                rows = [r for r in rows if str(r.get(key)) in wanted]
            else:
                rows = [r for r in rows if _cmp(r.get(key), op, val)]
        if params.get("or"):
            node = _parse_node(params["or"])
            rows = [r for r in rows if _eval(node, r)]
        rows.sort(key=_sort_key(params.get("order")))
        limit = min(int(params.get("limit") or 10), self.cap)
        offset = int(params.get("offset") or 0)
        return _RD(rows[offset:offset + limit])


def _setup(monkeypatch, sb_get, cap=10_000):
    import src.data.vector.market_state_writer as msw
    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(hd, "_PAGE", {"cap": cap, "tried_at": 0.0})
    monkeypatch.setenv("SUPABASE_URL", "http://x")


def _panel_rows(n_days=40, symbols=("BTC", "ETH", "SOL")):
    rows = []
    for d in range(n_days):
        day = f"2025-01-{d + 1:02d}"
        for i, sym in enumerate(symbols):
            rows.append({"symbol": sym, "trade_date": day, "close": 100 + d + i,
                         "volume": 10 + i, "source": "binance_hist"})
    return rows


# ── ① 键唯一时:按键读与 OFFSET 读逐行相同 ─────────────────────────────────

def test_keyset_reads_the_same_rows_in_the_same_order_as_offset(monkeypatch):
    """同一张表、同一份数据,两种翻页方式读出来的行**逐行相同、顺序相同**。"""
    rows = _panel_rows(n_days=40)
    params = {"select": "*", "source": "eq.binance_hist",
              "order": "trade_date.asc,symbol.asc"}

    off = _Fake(rows)
    _setup(monkeypatch, off, cap=30)
    monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily", ())      # 临时不在册 ⇒ 走 OFFSET
    rows_off = asyncio.run(hd._read_all("ohlcv_daily", dict(params)))

    key = _Fake(rows)
    _setup(monkeypatch, key, cap=30)
    monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily",
                         ((("trade_date", "symbol"), frozenset({"source"})),))
    rows_key = asyncio.run(hd._read_all("ohlcv_daily", dict(params)))

    assert rows_off == rows_key, "按键翻页读出来的内容/顺序与 OFFSET 版不同"
    assert len(rows_key) == 120
    assert len(key.calls) == len(off.calls), "请求页数应相同(每页行数一样)"
    assert "offset" not in key.calls[1], "第二页起应带续读谓词,不带 offset"
    assert key.calls[1].get("or"), "第二页应带 or= 续读谓词"


def test_the_resume_predicate_is_built_from_the_last_row_of_the_previous_page(monkeypatch):
    """续读谓词用的是**上一页最后一行**的键 —— 用错行就漏行。"""
    rows = _panel_rows(n_days=3, symbols=("BTC", "ETH"))
    fake = _Fake(rows, cap=2)
    _setup(monkeypatch, fake, cap=2)
    monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily",
                         ((("trade_date", "symbol"), frozenset({"source"})),))
    got = asyncio.run(hd._read_all("ohlcv_daily", {
        "select": "*", "source": "eq.binance_hist", "order": "trade_date.asc,symbol.asc"}))
    assert got == rows
    assert fake.calls[1]["or"] == "(trade_date.gt.2025-01-01,and(trade_date.eq.2025-01-01,symbol.gt.ETH))"


# ── ② 不许上按键翻页的三种情况 ──────────────────────────────────────────────

def test_a_table_that_is_not_in_the_registry_stays_on_offset(monkeypatch):
    """不在册的表一律留 OFFSET 版 —— 键不唯一会漏行,宁可慢,不可少。"""
    rows = _panel_rows(n_days=3)
    fake = _Fake(rows, cap=2)
    _setup(monkeypatch, fake, cap=2)
    got = asyncio.run(hd._read_all("some_unregistered_table", {
        "select": "*", "source": "eq.binance_hist", "order": "trade_date.asc,symbol.asc"}))
    assert got == rows
    assert all("or" not in c for c in fake.calls), "不在册的表不该带续读谓词"
    assert fake.calls[1].get("offset") == "2", "应留在 OFFSET 版"


def test_the_key_must_be_pinned_by_an_eq_filter(monkeypatch):
    """`ohlcv_daily` 的唯一约束是 (symbol, trade_date, **source**) —— source 没钉死时 (trade_date, symbol) 不唯一。"""
    rows = _panel_rows(n_days=3)
    fake = _Fake(rows, cap=2)
    _setup(monkeypatch, fake, cap=2)
    monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily",
                         ((("trade_date", "symbol"), frozenset({"source"})),))
    got = asyncio.run(hd._read_all("ohlcv_daily", {
        "select": "*", "order": "trade_date.asc,symbol.asc"}))      # 没有 source=eq.
    assert got == rows
    assert all("or" not in c for c in fake.calls), "source 没钉死 ⇒ 不许上按键翻页"


def test_a_call_with_its_own_or_filter_stays_on_offset(monkeypatch):
    """调用点自己带 `or=` 过滤时,续读谓词会把它覆盖掉 ⇒ 不许上按键翻页。"""
    rows = _panel_rows(n_days=3)
    fake = _Fake(rows, cap=2)
    _setup(monkeypatch, fake, cap=2)
    monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily",
                         ((("trade_date", "symbol"), frozenset({"source"})),))
    got = asyncio.run(hd._read_all("ohlcv_daily", {
        "select": "*", "source": "eq.binance_hist", "order": "trade_date.asc,symbol.asc",
        "or": "(close.gt.0)"}))
    assert got == rows
    assert all(c.get("or") == "(close.gt.0)" for c in fake.calls), "调用点的 or= 过滤不许被覆盖"


# ── ③ 中途退回:一行不少、一行不重 ─────────────────────────────────────────

def test_an_unusable_key_value_falls_back_to_offset_without_losing_rows(monkeypatch):
    """键值带保留字符(建不出谓词)⇒ 中途退回 OFFSET 版,读出来的行仍是一行不少一行不重。"""
    rows = _panel_rows(n_days=4)
    rows[1]["symbol"] = "BTC/USDT"                                  # '/' 不在安全字符集里
    fake = _Fake(rows, cap=2)
    _setup(monkeypatch, fake, cap=2)
    monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily",
                         ((("trade_date", "symbol"), frozenset({"source"})),))
    got = asyncio.run(hd._read_all("ohlcv_daily", {
        "select": "*", "source": "eq.binance_hist", "order": "trade_date.asc,symbol.asc"}))
    expected = sorted(rows, key=lambda r: (r["trade_date"], r["symbol"]))
    assert len(got) == len(expected) == 12
    assert got == expected, "退回 OFFSET 后读出来的行必须一行不少、一行不重、顺序不变"
    assert any("or" not in c for c in fake.calls[1:]), "谓词建不出来时应退回 OFFSET 版"
    assert any(c.get("offset") for c in fake.calls[1:]), "退回后应按已读行数继续"


# ── ④ 谓词的形状 ───────────────────────────────────────────────────────────

def test_resume_predicate_shapes_for_one_two_and_three_columns():
    assert hd.resume_predicate([("a", "asc")], {"a": "X"}) == "(a.gt.X)"
    assert hd.resume_predicate([("a", "asc")], {"a": "X"}) != hd.resume_predicate(
        [("a", "desc")], {"a": "X"})
    assert hd.resume_predicate([("a", "desc")], {"a": "X"}) == "(a.lt.X)"
    assert hd.resume_predicate([("a", "asc"), ("b", "asc")], {"a": "X", "b": "Y"}) == \
        "(a.gt.X,and(a.eq.X,b.gt.Y))"
    assert hd.resume_predicate([("a", "asc"), ("b", "desc")], {"a": "X", "b": "Y"}) == \
        "(a.gt.X,and(a.eq.X,b.lt.Y))"
    assert hd.resume_predicate([("a", "asc"), ("b", "asc"), ("c", "asc")],
                               {"a": "X", "b": "Y", "c": "Z"}) == \
        "(a.gt.X,and(a.eq.X,or(b.gt.Y,and(b.eq.Y,c.gt.Z))))"
    assert hd.resume_predicate([("a", "asc")], {"a": None}) is None, "空值 ⇒ 建不出谓词"
    assert hd.resume_predicate([("a", "asc")], {"a": "a,b"}) is None, "带保留字符 ⇒ 建不出谓词"


# ── ⑤ fetch_panel(生产路径的大头)───────────────────────────────────────────

def test_fetch_panel_uses_keyset_paging_and_returns_the_same_panel(monkeypatch):
    """`fetch_panel` 自带一套翻页循环 —— 改成按键翻页后,面板内容必须一模一样。"""
    import src.data.vector.market_state_writer as msw
    rows = _panel_rows(n_days=6)

    off = _Fake(rows, cap=3)
    monkeypatch.setattr(msw, "_sb_get", off)
    monkeypatch.setattr(msw, "PANEL_PAGE", 3)
    panel_off, _ = asyncio.run(msw.fetch_panel("2025-01-01"))

    key = _Fake(rows, cap=3)
    monkeypatch.setattr(msw, "_sb_get", key)
    monkeypatch.setattr(msw, "PANEL_PAGE", 3)
    panel_key, _ = asyncio.run(msw.fetch_panel("2025-01-01"))

    assert panel_key == panel_off, "按键翻页拿到的面板与 OFFSET 版不同"
    assert len(panel_key) == 3 and sum(len(v) for v in panel_key.values()) == 18
    assert "offset" not in key.calls[1], "第二页起应带续读谓词,不带 offset"
    assert key.calls[1].get("or"), "第二页应带 or= 续读谓词"


# ── ③ 核对请求的游标(T-419)───────────────────────────────────────────────
#
# 缺陷形状:末页不满(但 ≥1,000 行)时那次「还有没有行」的核对,用的是**进入这一轮时**
# 就已算好的旧游标(上一页的键)⇒ 问的是「上一页之后还有没有行」⇒ 答案永远是「有」
# ⇒ 白发一次请求、把每页行数误设成末页行数(线上量到 8,296)、
# 「服务端上限被调低」的检测在按键路径上失效。
#
# 修法:核对请求的谓词用**本页最后一行**(`out.extend` 之后的 `out[-1]`)的键重建;
# 谓词建不出来(键值带保留字符)⇒ 退回 `offset=len(out)`。
#
# 三条断言:谓词用本页末行 / 还有行时 cap 设成真实行数且不多发请求 /
# 末页就是最后一批时直接收、cap 不被改小。


def _keyed_rows(n: int) -> list[dict]:
    """n 行,键 (trade_date, symbol) 唯一(一天 10 个 symbol),顺序与 (trade_date, symbol) 一致。"""
    rows: list[dict] = []
    for i in range(n):
        d = i // 10
        rows.append({"trade_date": f"2025-{1 + d // 30:02d}-{1 + d % 30:02d}",
                     "symbol": f"S{i % 10:02d}", "close": 100 + i,
                     "volume": 10, "source": "binance_hist"})
    return rows


def _read(monkeypatch, rows, *, server_cap, believed_cap, keyset: bool):
    """整读一张表,返回(读到的行, 请求记录, 读完后的每页行数)。"""
    fake = _Fake(rows, cap=server_cap)
    _setup(monkeypatch, fake, cap=believed_cap)
    if keyset:
        monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily",
                             ((("trade_date", "symbol"), frozenset({"source"})),))
    else:
        monkeypatch.setitem(hd.KEYSET_SPECS, "ohlcv_daily", ())   # 临时不在册 ⇒ 走 OFFSET
    got = asyncio.run(hd._read_all("ohlcv_daily", {
        "select": "*", "source": "eq.binance_hist", "order": "trade_date.asc,symbol.asc"}))
    return got, fake.calls, hd._PAGE["cap"]


def test_the_probe_predicate_is_built_from_the_last_row_of_the_page_just_read(monkeypatch):
    """核对请求的 `or=` 谓词必须用**本页最后一行**的键重建(不是上一页的旧游标)。"""
    rows = _keyed_rows(3_500)
    got, calls, cap = _read(monkeypatch, rows, server_cap=2_000, believed_cap=2_000, keyset=True)

    assert got == rows, "读出来的行不许变"
    probe = calls[-1]
    assert probe["limit"] == "1", "核对请求只问一行"
    assert probe["or"] == "(trade_date.gt.2025-12-20,and(trade_date.eq.2025-12-20,symbol.gt.S09))", \
        "核对谓词必须用本页最后一行(2025-12-20/S09)重建"
    assert probe["or"] != calls[1]["or"], "核对请求不能复用上一页的旧游标"
    assert cap == 2_000


def test_a_real_cap_that_is_lower_sets_the_cap_to_the_true_row_count(monkeypatch):
    """真的还有行 ⇒ 服务端上限被调低 ⇒ `_PAGE["cap"]` 设成本页真实行数,且不多发一次请求。"""
    rows = _keyed_rows(2_500)
    got, calls, cap = _read(monkeypatch, rows, server_cap=1_000, believed_cap=1_500, keyset=True)
    off_got, off_calls, off_cap = _read(monkeypatch, rows, server_cap=1_000, believed_cap=1_500,
                                        keyset=False)

    assert got == rows == off_got and len(got) == 2_500, "两种读法读到的行必须一样"
    assert cap == 1_000 == off_cap, "上限被调低时按真实行数接着读,并记住"
    assert len(calls) == len(off_calls) == 4, "3 次取数 + 1 次核对;按键版不比 OFFSET 版多发请求"


def test_the_last_short_page_ends_the_read_without_shrinking_the_cap(monkeypatch):
    """末页就是最后一批时:核对请求返回空 ⇒ 直接收,`_PAGE["cap"]` 不被改小、不多发请求。"""
    rows = _keyed_rows(3_500)
    got, calls, cap = _read(monkeypatch, rows, server_cap=2_000, believed_cap=2_000, keyset=True)
    off_got, off_calls, _ = _read(monkeypatch, rows, server_cap=2_000, believed_cap=2_000,
                                  keyset=False)

    assert got == rows == off_got and len(got) == 3_500
    assert cap == 2_000, "上限没变 ⇒ 不许把每页行数改小"
    assert len(calls) == len(off_calls) == 3, "2 次取数 + 1 次核对;末页不该再发一次空的取数请求"

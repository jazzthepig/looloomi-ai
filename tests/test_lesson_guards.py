"""教训 → 关卡:把只被写下来的那些,变成会在复发时变红的 (S-224).

S-223 量出来:102 条写下的教训,76 条有关卡,26 条只是散文。这个文件补 A 类
—— 那些有明显可执行形式的工程教训。

每条守卫的写法遵守 `tests/_source.py` 的规则:**匹配构造,不匹配附近的字符串**。
本 session 我的守卫被这条打回过六次,而失败模式是反直觉的 —— 解释 bug 的注释里
一定含有那个 bug 的名字,所以注释写得越好,测试被废得越彻底。
"""
from __future__ import annotations

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tests._source import code_only                                  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
_fails: list[str] = []


def fail(label: str) -> None:
    _fails.append(label)


def py_files(*rel: str):
    for r in rel:
        base = ROOT / r
        if base.is_file():
            yield base
        else:
            for p in base.rglob("*.py"):
                if "__pycache__" in p.parts or ".venv" in p.parts:
                    continue
                yield p


# ── S-214 · 一个 `*_TABLE = "..."` 常量是一个承诺 ────────────────────────────
# pod_aggregator_paper 和 factor_tilt_paper 各声明了 NAV_TABLE 并且从未写入。
# 两张表 0 行数周,两本账每天照报 status ok。空表读起来像"这个策略没产出" ——
# 那是一个结果,而它从来不是结果,是一行没写的代码。
#
# 构造匹配:模块级赋值给以 _TABLE 结尾的名字 → 该常量必须在同文件中被【使用】
# (Name 节点出现在赋值以外的位置)。只查"提到过"是不够的,所以查 ast.Name 的
# 读取上下文,注释里的同名字符串不构成 ast.Name。
def _table_constants(tree: ast.AST) -> dict[str, int]:
    out: dict[str, int] = {}
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.endswith("_TABLE"):
                    out[t.id] = node.lineno
    return out


# ⚠️ 第一版守卫查的是"这个常量在文件里被读过没有",mutation 存活:把
# `write_nav_row(NAV_TABLE, ...)` 换成 `write_nav_row("pod_aggregator_nav", ...)`
# 照样通过,因为 `get_curve()` 也读这个常量。**"被读过"不是承诺的内容,"被写"才是。**
_WRITE_CALLS = {"write_nav_row", "supabase_insert_table", "supabase_upsert_table",
                "supabase_rpc_write"}


def _table_names_passed_to_writes(tree: ast.AST) -> set[str]:
    """常量名出现在某个写调用的实参位置 —— 构造匹配,不是名字出现匹配。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name not in _WRITE_CALLS:
            continue
        for a in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(a, ast.Name):
                out.add(a.id)
    return out


for p in py_files("src/data/signals"):
    try:
        tree = ast.parse(p.read_text())
    except SyntaxError:
        continue
    consts = _table_constants(tree)
    if not consts:
        continue
    written = _table_names_passed_to_writes(tree)
    for name, line in consts.items():
        # STATE_TABLE 走的是各账本自己的 httpx POST,不经共享写函数 —— 只查 NAV。
        if not name.startswith("NAV"):
            continue
        if name not in written:
            fail(f"S-214: {p.relative_to(ROOT)}:{line} declares {name} but no write "
                 f"call receives it — a constant naming a table is a promise, and "
                 f"{name} went unwritten for weeks while the book reported ok")


# ── S-195 · CoinGecko 的 market_chart 给不出收盘价 ───────────────────────────
# 它返回采样点,短窗口下是【小时点】,塌缩到日期后留下的是最后落进来的那个小时。
# 我们付了四个月 Pro,ohlc/range 调用 0 次。禁止它出现在任何收益/mark 路径。
#
# ⚠️ 这条守卫写完第一次跑就抓到两处【活的】违规。S-195 写在台账里,而调用还在,
# 其中一处喂的是 A 支柱 —— 这正是"只被写下来的教训"的样子:文档齐全,缺陷仍在。
# 冻结已知的两处并写明后果,新增的直接 fail。名单只能减。
_S195_KNOWN = {
    # 文件 : 后果(不是借口 —— 让后来的人知道自己在读什么数)
    "src/data/market/data_layer.py":
        "get_cg_price_history 喂 A 支柱(90d alpha)与波动率 regime。market_chart "
        "返回采样点不是 K 线,即使 interval=daily 也不是收盘 —— A 支柱与 vol regime "
        "建立在一个不是收盘价的序列上。归 Minimax-B/C,换 /ohlc/range。",
    "src/data/market/exchange_data.py":
        "未带 interval,短窗口下返回小时点。此路径是否仍被读取需先确认。",
}
_RETURN_PATHS = ("src/data/signals", "src/data/market")
_s195_seen: set[str] = set()
for p in py_files(*_RETURN_PATHS):
    body = code_only(p.read_text())
    if "market_chart" not in body:
        continue
    rel = str(p.relative_to(ROOT))
    if rel in _S195_KNOWN:
        _s195_seen.add(rel)
        continue
    fail(f"S-195: {rel} reaches market_chart on a return/mark path — it yields "
         f"sample points, not closes; use ohlc/range")
# 名单只能减:某文件已经修好了却还留在名单上 → fail,否则冻结名单会变成永久豁免。
for rel in _S195_KNOWN.keys() - _s195_seen:
    fail(f"S-195: {rel} no longer uses market_chart — remove it from _S195_KNOWN")


# ── S-216 · 每个 store 都要在 loop_health 的视野里 ───────────────────────────
# 建了每一段却没让它流动:asset_embeddings 停 31 天、market_state_vectors 停 19 天
# 且 regime_label 全 NULL、strategy_records 0 行 —— 全部靠手工发现,因为那个
# 为了"让掉队的环节无处可藏"而造的探针,视野里没有这四张表。
#
# ⚠️ 第一版守卫 mutation 存活,而且是 `_source.py` 记录的同一个失败:它扫全文件的
# ast.Constant,**而 docstring 本身就是 Constant 节点** —— 我在模块 docstring 里
# 列出那四张表的行为,满足了这条守卫。删掉 specs 里的一项照样通过。
# 「注释写得越好,测试被废得越彻底」在同一个 session 里第七次出现。
#
# 改成只看 `vdb_health()` 内部 `specs` 那个列表字面量的第一个元素。
_vdb_tree = ast.parse((SRC / "data/vector/vdb_health.py").read_text())
_declared_stores: set[str] = set()
for _fn in ast.walk(_vdb_tree):
    if not (isinstance(_fn, ast.AsyncFunctionDef) and _fn.name == "vdb_health"):
        continue
    for _st in ast.walk(_fn):
        if isinstance(_st, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "specs" for t in _st.targets):
            for _el in getattr(_st.value, "elts", []):
                first = getattr(_el, "elts", [None])[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    _declared_stores.add(first.value)
_EXPECTED_STORES = {"asset_embeddings", "market_state_vectors",
                    "strategy_records", "experiment_runs"}
if _declared_stores != _EXPECTED_STORES:
    fail(f"S-216: vdb_health's specs cover {sorted(_declared_stores)}, expected "
         f"{sorted(_EXPECTED_STORES)} — a store outside the probe's view is a "
         f"store nobody will notice going dark")

# ── S-225 · 探针必须按消费者的查询方式查 ─────────────────────────────────────
# asset_embeddings 存着 72 行,探针高高兴兴报 "72 rows, 31d old"。而读路径过滤
# `schema_version=eq.3 & superseded_reason is null`,所有存量行都是 v2 —— 可读
# 行数【零】。向量层已经全黑两周,而探针报的是"有点旧"。
#
# 并且:被测的新鲜度列必须由写者【显式写入】。computed_at 的 DEFAULT now() 只在
# INSERT 触发,而 upsert 走的是 UPDATE —— 再完美的日循环也不会让那个数字动。
_pgv_src = (SRC / "data/vector/pgvector_store.py").read_text()
_ups = next((n for n in ast.walk(ast.parse(_pgv_src))
             if isinstance(n, ast.FunctionDef) and n.name == "upsert_embeddings"), None)
if _ups is None:
    fail("S-225: upsert_embeddings not found")
else:
    _keys: set[str] = set()
    for _d in ast.walk(_ups):
        if isinstance(_d, ast.Dict):
            _keys |= {k.value for k in _d.keys if isinstance(k, ast.Constant)}
    if "computed_at" not in _keys:
        fail("S-225: upsert_embeddings does not write computed_at — a DEFAULT now() "
             "fires on INSERT only, and this is an on_conflict merge, so the "
             "freshness column vdb_health measures would never advance")

# ⚠️ 第一版:`"READ_FILTERS" not in source`。把【定义】改名成 READ_FILTERZ 后
# mutation 存活 —— 因为 `READ_FILTERS.get(table)` 那个【用法】还在,子串照样命中。
# 子串分不出定义和使用,这是今天第四次。改成 AST:模块级必须有这个赋值,且
# vdb_health() 内必须真的读它并写出 readable_rows。
_vdb_mod = ast.parse((SRC / "data/vector/vdb_health.py").read_text())
_has_def = any(isinstance(n, (ast.Assign, ast.AnnAssign))
               and any(isinstance(t, ast.Name) and t.id == "READ_FILTERS"
                       for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))
               for n in _vdb_mod.body)
if not _has_def:
    fail("S-225: vdb_health has no module-level READ_FILTERS — the probe would "
         "count rows the consumer cannot see")

_vh_fn = next((n for n in ast.walk(_vdb_mod)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "vdb_health"), None)
if _vh_fn is None:
    fail("S-225: vdb_health() not found")
else:
    _reads_filter = any(isinstance(n, ast.Name) and n.id == "READ_FILTERS"
                        and isinstance(n.ctx, ast.Load) for n in ast.walk(_vh_fn))
    _emits = any(isinstance(n, ast.Constant) and n.value == "readable_rows"
                 for n in ast.walk(_vh_fn))
    if not (_reads_filter and _emits):
        fail("S-225: vdb_health() does not apply READ_FILTERS / emit readable_rows — "
             "a count over a superset of what consumers can see is not a health "
             "metric (72 stored, 0 readable, reported as merely stale)")

# ── S-227 · 「太早」是一个独立结论,不是「坏了」 ──────────────────────────────
# 2026-08-24 一个问题来回三次,全部内容是在区分四个状态:没推送 / 推了没部署 /
# 部署了没跑到 / 跑了但写失败。把它们合并成"红或绿",就是那三次来回。
_pdv = (ROOT / "scripts/postdeploy_verify.sh")
if not _pdv.exists():
    fail("S-227: scripts/postdeploy_verify.sh 不存在 —— preflight 拦 push,"
         "没有任何东西拦「它在生产里到底跑了没有」")
else:
    _pdv_src = _pdv.read_text()
    for _needle, _why in [
        ("origin/main..HEAD", "没有查未推送 commit —— 那是三次来回里的第三次"),
        ("uptime_seconds", "没有读 uptime —— 分不出「太早」和「坏了」"),
        ("FIRST_RUN", "没有每个 loop 的首次延迟表 —— uptime 无从比较"),
        ("TOO_EARLY", "没有独立的「太早」判决 —— 它会被并进失败"),
        ("${LOCAL_SHA:0:7}", "SHA 比较没有取共同前缀 —— 会把相同判成不同"),
    ]:
        if _needle not in _pdv_src:
            fail(f"S-227: postdeploy_verify {_why}")

# ── S-228 · 角色与拒绝计数必须能从外面看见 ───────────────────────────────────
# APP_ROLE 未设 ⇒ fail-closed 成 replica ⇒ 每个经过 role gate 的写入被静默拒绝,
# 而拒绝只 log-once。于是两个世界从外面一模一样:primary 但没人调那个端点 /
# replica 但每次写入都被拒。修法毫不相干,而我在 S-221 里直接断言了前者。
_rr = ast.parse((SRC / "api/runtime_role.py").read_text())
if not any(isinstance(n, ast.FunctionDef) and n.name == "refusal_counts"
           for n in ast.walk(_rr)):
    fail("S-228: runtime_role 没有 refusal_counts() —— 一次拒绝和一万次拒绝"
         "在外面看起来一样")
else:
    _nr = next(n for n in ast.walk(_rr)
               if isinstance(n, ast.FunctionDef) and n.name == "note_refusal")
    # 计数必须在 log-once 的早返回【之前】,否则第二次起就不计了。
    _body = _nr.body
    _first_return = next((i for i, x in enumerate(_body)
                          if any(isinstance(y, ast.Return) for y in ast.walk(x))), len(_body))
    _counts_early = any("_REFUSALS" in ast.dump(x) for x in _body[:_first_return])
    if not _counts_early:
        fail("S-228: note_refusal 在 log-once 的早返回之后才计数 —— 第二次起就丢了,"
             "而「发生过」和「发生了多少次」是两个问题")

_ms = ast.parse((SRC / "api/main.py").read_text())
if not any(isinstance(n, ast.FunctionDef) and n.name == "_role_echo" for n in ast.walk(_ms)):
    fail("S-228: /internal/build-state 不回显 runtime_role —— 决定整个进程能否写"
         "系统记录的那个开关,在生产里不可见")

_lh = code_only((SRC / "api/loop_health.py").read_text())
if "vdb-health" not in _lh:
    fail("S-216: loop_health does not probe the vector substrate — the instrument "
         "built to make an orphaned stage impossible to hide had four of them "
         "outside its field of view")


# ── S-215 · 中性默认值必须带一个"这是不是测出来的"伴随字段 ───────────────────
# ic_multiplier = 1.0 同时表示"没有可用因子"和"IC 算出来是平的"。四个月里每根
# 支柱都读 1.0,因为 realized_return_7d 全 NULL —— 加权机制从未通电,而 payload
# 和一个测出了中性的健康引擎完全无法区分。
_trading = code_only((SRC / "api/routers/trading.py").read_text())
for companion in ("ic_pillars_measured", "ic_multiplier_source", "ic_layer_active"):
    if companion not in _trading:
        fail(f"S-215: /trading ships ic_multipliers without {companion} — a neutral "
             f"default and a measured neutral must not be the same payload")


# ── S-207 · BLOCKED 与 FLAT 不能合并 ─────────────────────────────────────────
# 规则跑了并拒绝 = 机器是好的;规则跑不起来 = 工程坏了。两值报告会把 T2 写出
# score/grade 满覆盖而 pillar 全 NULL 的那 9 天,和被 regime 闸门挡住的 55 天
# 算成同一件事。
_pit = ast.parse((ROOT / "src/research/validation/pit_replay.py").read_text())
_verdicts = set()
for node in ast.walk(_pit):
    if isinstance(node, ast.ClassDef) and node.name == "Verdict":
        for item in node.body:
            if isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        _verdicts.add(t.id)
if not {"FIRED", "FLAT", "BLOCKED"} <= _verdicts:
    fail(f"S-207: Verdict collapsed to {sorted(_verdicts)} — 'no position' must "
         f"carry whether the rule declined or could not run")


# ── S-194 · 覆盖率按持仓权重算,不按名字个数 ─────────────────────────────────
# 丢掉一个 0.4% 权重的名字是噪音;丢掉 30% 的 BTC 腿不是,而名字计数的地板
# 分不出这两件事。
_mc = ast.parse((SRC / "data/signals/mark_coverage.py").read_text())
_mc_code = code_only((SRC / "data/signals/mark_coverage.py").read_text())
if "min_coverage" not in _mc_code:
    fail("S-194: mark_coverage lost its coverage floor parameter")
# 权重求和的构造:必须对 weights 取值求和,而不是对名字计数
if "len(" in _mc_code and "sum(" not in _mc_code:
    fail("S-194: mark_coverage counts names instead of summing weights")


# ── S-119 · 写入门槛在写入函数里,不在调用方 ─────────────────────────────────
# 门槛必须在写入路径上,不能只在 CI 里 —— 问「谁能绕过这个检查」。二十几个
# 后台 loop 会不断新增,一个需要记得的门槛就是会被忘记的门槛。
_store = code_only((SRC / "api/store.py").read_text())
_ins = _store.split("async def supabase_insert_table", 1)
if len(_ins) < 2:
    fail("S-119: supabase_insert_table not found — the single write gate moved")
elif "refuse_write" not in _ins[1][:900]:
    fail("S-119: supabase_insert_table no longer calls refuse_write at its head — "
         "the role gate moved out of the write function and into its callers")


if _fails:
    print("✗ lesson guards FAILED:")
    for f in _fails:
        print("   ·", f)
    sys.exit(1)
print(f"  ✓ lesson guards: S-119/194/195/207/214/215/216/225/227/228 enforced "
      f"({len(_declared_stores)} vdb stores watched)")

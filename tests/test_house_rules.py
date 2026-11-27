"""S-930:现行规则只有一份,研究脚本必须声明它用了哪些、改了哪一条。

起因(2026-11-27):S-926 → S-929 连续四轮模拟都由 Jazz 指出不合标准 —— 空单定稿只在卡的备注里,
教义里留着被取代的写法,每个研究脚本自己重写一遍口径,预注册只核对自己的预测、从不核对现行规则。
这里钉住三件:
  1. `docs/RULEBOOK.md` 的机器可读块 == `src/data/evaluation/house_rules.py`(文档与代码说同一件事)。
  2. 生产里形态 #1 的口径从 `house_rules` 来(`setup_watch` 不再自己写常量)。
  3. 新研究脚本(`docs/research/s929_*.py` 起)在模块顶层声明 `HOUSE_RULES`:
     `{"layer": …, "ruler": …, "uses": [现行规则集名…], "varies": {改了哪条: "S-编号 + 为什么"}}`;
     `uses` 里的名字必须是 `house_rules.RULE_SETS` 里有的,`varies` 的每一条都要带 S-编号。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.evaluation import house_rules as H  # noqa: E402

RULEBOOK = ROOT / "docs" / "RULEBOOK.md"
FIRST_DECLARED = 929          # 这个编号起的研究脚本必须声明


def _parse(v: str):
    v = v.strip()
    if v == "None":
        return None
    if v in ("True", "False"):
        return v == "True"
    if "," in v:
        return tuple(float(x) for x in v.split(","))
    return float(v) if "." in v or v.startswith("-") else int(v)


def _rulebook_block() -> dict:
    text = RULEBOOK.read_text(encoding="utf-8")
    m = re.search(r"```house_rules\n(.*?)```", text, flags=re.S)
    assert m, "RULEBOOK.md 里找不到 ```house_rules 机器可读块"
    out = {}
    for line in m.group(1).strip().splitlines():
        k, v = line.split("=", 1)
        out[k.strip()] = _parse(v)
    return out


def _flat() -> dict:
    out = {}
    for name, rs in H.RULE_SETS.items():
        for k, v in rs.items():
            out[f"{name}.{k}"] = tuple(float(x) for x in v) if isinstance(v, tuple) else v
    return out


def test_rulebook_and_code_say_the_same_thing():
    doc, code = _rulebook_block(), _flat()
    assert set(doc) == set(code), f"只在文档里:{sorted(set(doc) - set(code))};只在代码里:{sorted(set(code) - set(doc))}"
    bad = {k: (doc[k], code[k]) for k in code if doc[k] != code[k]}
    assert not bad, f"RULEBOOK 与 house_rules 不一致(文档, 代码):{bad}"


def test_setup_watch_reads_the_house_rules():
    from src.data.evaluation import setup_watch as S
    assert (S.LOOKBACK, S.STOP_ABOVE, S.STOP_CAP, S.HORIZON_D) == (H.T370["lookback"], H.T370["stop_above"], H.T370["stop_cap"], H.T370["horizon_d"])
    src = (ROOT / "src/data/evaluation/setup_watch.py").read_text(encoding="utf-8")
    assert "from src.data.evaluation.house_rules import" in src, "setup_watch 要从 house_rules 取口径,不要自己写常量"


def _declaration(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HOUSE_RULES" for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def _new_scripts() -> list[Path]:
    out = []
    for p in sorted((ROOT / "docs" / "research").glob("s*.py")):
        m = re.match(r"s(\d+)_", p.name)
        if m and int(m.group(1)) >= FIRST_DECLARED:
            out.append(p)
    return out


def test_new_research_scripts_declare_which_rules_they_use_and_vary():
    problems = []
    for p in _new_scripts():
        d = _declaration(p)
        if not isinstance(d, dict):
            problems.append(f"{p.name}:模块顶层没有 HOUSE_RULES 声明")
            continue
        missing = [k for k in ("layer", "ruler", "uses", "varies") if k not in d]
        if missing:
            problems.append(f"{p.name}:HOUSE_RULES 缺 {missing}")
            continue
        unknown = [u for u in d["uses"] if u not in H.RULE_SETS and u != "none"]
        if unknown:
            problems.append(f"{p.name}:uses 里有不认识的规则集 {unknown}(现有 {sorted(H.RULE_SETS)})")
        no_ref = [k for k, why in d["varies"].items() if not re.search(r"S-\d+", str(why))]
        if no_ref:
            problems.append(f"{p.name}:varies 里这几条没写 S-编号:{no_ref}")
    assert not problems, "\n".join(problems)


def test_the_declaration_check_bites():
    """守卫自己要会咬人:一份没有声明的脚本必须被挑出来(S-294 的教训:只看调用方、不看被调方的守卫)。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s999_x.py"
        p.write_text('"""x"""\nX = 1\n', encoding="utf-8")
        assert _declaration(p) is None
        p.write_text('HOUSE_RULES = {"layer": "③", "ruler": "账户回本时间", "uses": ["T370"], "varies": {"管法": "无编号"}}\n', encoding="utf-8")
        d = _declaration(p)
        assert d and not re.search(r"S-\d+", d["varies"]["管法"])

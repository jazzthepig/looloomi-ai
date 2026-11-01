#!/usr/bin/env python3
"""T-217 辅助:把 t217_* 脚本的 scratch 路径从 /tmp 搬回 lane 根(doc/research/)。

规则 3a:产物落在 lane 的根上,不落 /tmp。
做法(纯机械、可重复):
  1) 正则把 "/tmp/t217_scratch/<file>" 改写为 Path(__file__).parent / "t217_<file>"
  2) 目录常量 "/tmp/t217_scratch" 改写为 Path(__file__).resolve().parent
  3) 补 `from pathlib import Path` 导入
  4) 把已有 scratch 产物复制成新名字(若新名字还不存在)

注意:本脚本不修改自己(glob 时排除 t217_relocate.py)—— 上一版改坏过自己的正则。

用法: python3 t217_relocate.py [--copy]
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELF = "t217_relocate.py"
# 形如 "/tmp/t217_scratch/foo.json" 的完整文件路径常量
PAT_FILE = re.compile(r'"/tmp/t217_scratch/([^"]+)"')
# 形如 "/tmp/t217_scratch" 的目录常量
PAT_DIR = re.compile(r'"/tmp/t217_scratch"')


def rewrite(src: Path) -> bool:
    text = src.read_text(encoding="utf-8")
    if "/tmp/t217_scratch" not in text:
        return False
    new = PAT_FILE.sub(lambda m: f'str(Path(__file__).resolve().parent / "t217_{m.group(1)}")', text)
    new = PAT_DIR.sub('str(Path(__file__).resolve().parent)', new)
    if "from pathlib import Path" not in new:
        for anchor in ("import json", "import os", "import re"):
            if anchor in new:
                new = new.replace(anchor, anchor + "\nfrom pathlib import Path", 1)
                break
    src.write_text(new, encoding="utf-8")
    return True


def main() -> None:
    copy = "--copy" in sys.argv
    scratch = Path("/tmp/t217_scratch")
    changed = []
    for p in sorted(HERE.glob("t217_*.py")):
        if p.name == SELF:
            continue
        if rewrite(p):
            changed.append(p.name)
    print("rewritten:", ", ".join(changed) or "(none)")
    if copy and scratch.is_dir():
        n = 0
        for f in sorted(scratch.iterdir()):
            if not f.is_file():
                continue
            dst = HERE / f"t217_{f.name}"
            if not dst.exists():
                shutil.copy2(f, dst)
                n += 1
        print("copied:", n)
    left = [p.name for p in sorted(HERE.glob("t217_*.py"))
            if p.name != SELF and "/tmp/t217_scratch" in p.read_text(encoding="utf-8")]
    print("still_referencing_tmp:", left or "(none)")


if __name__ == "__main__":
    main()

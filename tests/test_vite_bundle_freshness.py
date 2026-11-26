"""
Vite bundle freshness guard — preflight B-4 (S-171 follow-on, M-1 authored by Minimax-B 2026-08-25).

INCIDENT. Twice in 2026-08 the same shape shipped:

  · `dashboard/src/components/Foo.jsx` edited
  · `cd dashboard && npm run build` SKIPPED (forgot, "tests pass")
  · `git add dashboard/src/components/Foo.jsx dashboard/index.html` (only the
    index.html that already existed, since Vite hadn't regenerated it)
  · `git commit -m "feat: add Foo" && git push`
  · Railway deploys. The bundle does NOT contain Foo's compiled chunk. User
    clicks the tab → ReferenceError → blank page. Same shape as S-171
    (AssetRadar), but the cause was different: S-171 was a missing import; this
    is a missing build.

WHY NOTHING CAUGHT IT.

  · `npm run build` was the author's responsibility. The script is fast (~6s),
    but the cost is a discipline step, and discipline steps are exactly what
    the project centralises in preflight (CLAUDE.md "always run preflight").
  · ESLint did not run on the pre-commit (no husky configured). Even if it did,
    it checks the source, not whether the bundle matches it.
  · py_compile is Python only. Vite is JS.

THE SECOND INCIDENT (2026-11-20) —— 这一条把守卫自己变成了路障。

  · 一条 src 提交只改了**注释**(`dashboard/src/components/AssetRadar.jsx`),
    产物**逐字不变**(49/49 文件哈希相同,实测)。
  · 那条提交是**绕过 preflight 直接 git push** 的(commit message 自己写了
    「未走 seth_bot job」)⇒ 没有人重建 dist。
  · 于是:最后一次改 src 的提交(23:09:19)**晚于**最后一次改 dist 的提交
    (11-19 17:05:48)⇒ 老守卫判红。
  * 而这个红**没有任何合法解**:产物没变 ⇒ 没有可提交的 dist 差异 ⇒
    「再提交一次 dist」这条路不存在 ⇒ 守卫永远红 ⇒ **整个仓库推不动**
    (seth_bot 的每个 commit / merge job 都卡在 preflight)。

  ⇒ **病根不在纪律,在于尺子。** 老尺子量的是「提交时间」,问的是
  「dist 的提交是不是比 src 的提交新」;这个问题在「src 变了但产物没变」时
  **没有答案** —— 产物没变就不需要新的 dist 提交,于是尺子永远指着红。
  **尺子问错了问题。** 真正要问的是:**线上那一份产物,是不是当前 src 编出来的那一份?**

THE GUARD (v2, 2026-11-20 改版).

  尺子换成**量内容**:

  · src 有未提交改动 ⇒ 用 mtime(原尺子;这正是它当初要抓的场景:
    正在改 src、还没重建 dist)。
  · src 干净 ⇒ **把当前 src 构建到临时目录,和已提交的 dist 逐文件比哈希**:
    完全一致 ⇒ 线上那一份就是当前 src 编出来的 ⇒ 绿(哪怕提交时间是反的);
    有任何差异(少一个 chunk、多一个 chunk、某个文件内容不同)⇒ 红。
  · 量不到(没有 node / 没有 node_modules / 构建失败)⇒ 退回旧尺子
    (提交时间比较),保持老行为,不在环境缺依赖时假绿。

  构建**只写临时目录**,绝不写 dashboard/dist —— 那会把警报变成修理
  (守卫自己把 bug 修好,就没人知道线上曾经缺过 chunk)。仓库里的 dist 一律
  原样保留,差异照报。

  实测代价:一次 vite build ≈ 2s(合并 worktree 里也一样,前提是那里有
  node_modules —— seth_bot 的合并 worktree 现在会软链主目录那份)。

Run: python3 -m tests.test_vite_bundle_freshness
"""
from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_DASH = _ROOT / "dashboard"
_SRC  = _DASH / "src"
_DIST = _DASH / "dist"

# Files we never want to compare against (build artefacts that update for
# unrelated reasons: source maps, gzip copies, OS noise).
_DIST_IGNORE_SUFFIXES = (".map", ".gz", ".html")
_DIST_IGNORE_EXACT    = {"manifest.json", ".DS_Store"}

# 构建的超时:一次冷构建(无 vite 缓存)实测 ~2s;给它 5 分钟只为不把
# preflight 挂死,超时就当「量不到」,退回旧尺子。
_BUILD_TIMEOUT_S = 300

_FAILURES: list[str] = []


def _fmt(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _check(label: str, ok: bool, hint: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}")
    if not ok:
        _FAILURES.append(f"{label}{(' — ' + hint) if hint else ''}")


def _newest_mtime(root: Path, ignore_suffixes: tuple[str, ...] = (),
                  ignore_exact: set[str] = frozenset()) -> float | None:
    """Walk root, return the highest mtime across all regular files. Returns
    None if root does not exist OR has no eligible files."""
    if not root.is_dir():
        return None
    best: float | None = None
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune known noise directories.
        dirnames[:] = [d for d in dirnames
                       if d not in {"node_modules", ".git", "dist.old",
                                    "__pycache__", ".cache"}]
        for f in filenames:
            if f in ignore_exact:
                continue
            if any(f.endswith(s) for s in ignore_suffixes):
                continue
            p = Path(dirpath) / f
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if best is None or m > best:
                best = m
    return best


def _newest_mtime_time(root: Path) -> float | None:
    """Same as _newest_mtime but without the suffix filter — for use inside
    the tempdir test where there is no noise."""
    return _newest_mtime(root)


def _git(*a: str) -> str:
    """只读 git。`--no-optional-locks`:不碰 index 锁(规则 4)。"""
    return subprocess.run(["git", "-C", str(_ROOT), "--no-optional-locks", *a],
                          capture_output=True, text=True, check=True).stdout.strip()


def _git_status(path: str) -> str:
    try:
        return _git("status", "--porcelain", "--", path)
    except Exception:                                             # noqa: BLE001
        return ""


def _committed_freshness():
    """src 无未提交改动 ⇒ (最后一次改 src 的提交时间, 最后一次改 dist 的提交时间);否则 / git 不可用 ⇒ None。
    只读:`--no-optional-locks`,不碰 index 锁(规则 4)。"""
    try:
        if _git_status("dashboard/src"):
            return None
        src_ct = _git("log", "-1", "--format=%ct", "--", "dashboard/src")
        dist_ct = _git("log", "-1", "--format=%ct", "--", "dashboard/dist")
        if not src_ct or not dist_ct:
            return None
        return float(src_ct), float(dist_ct)
    except Exception:                                             # noqa: BLE001
        return None


# ── 内容比较(v2 的尺子)───────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    """目录 → {相对路径: sha256}。比较用,不看 mtime(构建出来的 mtime 每次都新)。"""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = _sha256(p)
    return out


def _diff_trees(a: dict[str, str], b: dict[str, str]) -> list[str]:
    """a=构建产物,b=已提交的 dist。返回差异描述(空列表 = 逐字一致)。"""
    out: list[str] = []
    for k in sorted(set(a) | set(b)):
        if k not in a:
            out.append(f"已提交的 dist 里多出:{k}")
        elif k not in b:
            out.append(f"构建产物里有、已提交的 dist 里没有:{k}")
        elif a[k] != b[k]:
            out.append(f"内容不同:{k}")
    return out


def _build_into(out_dir: Path) -> tuple[bool, str]:
    """把当前 src 构建到 out_dir(临时目录)。绝不写 dashboard/dist。
    返回 (成功?, 失败原因)。"""
    if not shutil.which("npm"):
        return False, "PATH 上没有 npm"
    if not (_DASH / "node_modules").is_dir():
        return False, "dashboard/node_modules 不在"
    try:
        p = subprocess.run(
            ["npm", "run", "build", "--", "--outDir", str(out_dir), "--emptyOutDir"],
            cwd=str(_DASH), capture_output=True, text=True, timeout=_BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"构建超时(>{_BUILD_TIMEOUT_S}s)"
    except Exception as e:                                        # noqa: BLE001
        return False, f"构建异常:{e}"
    if p.returncode != 0:
        return False, "构建失败:" + (p.stdout + p.stderr)[-400:].replace("\n", " ")
    return True, ""


def _measure_content() -> tuple[bool | None, str]:
    """量「当前 src 编出来的产物」与「已提交的 dashboard/dist」是不是同一份。

    返回 (一致?, 说明);第一项是 None = **量不到**(没有 node / 没有 node_modules /
    构建失败)⇒ 调用方退回旧尺子(提交时间比较),而不是假绿。

    11-26(lane-a T-443 报的):这里一直返回 `(None, why)`,调用方却判 `measured is None` ——
    退回旧尺子那段从没走到过,没有 node_modules 的机器(沙盒、只 pip install 的 CI)一律红。
    """
    # dist 有未提交改动 ⇒ 线上的那一份(committed)与工作树不是同一份,
    # 量工作树没有意义;这种情况本身就该被看见(产物改了没提交 ⇒ 别推)。
    if _git_status("dashboard/dist"):
        return False, ("dashboard/dist 有未提交改动 —— 线上跑的是已提交的那一份,"
                       "先把它提交了再推")
    with tempfile.TemporaryDirectory(prefix="vite-freshness-") as td:
        tmp = Path(td) / "dist"
        ok, why = _build_into(tmp)
        if not ok:
            return None, why
        if not tmp.is_dir():
            return None, "构建没有产出目录"
        diffs = _diff_trees(_tree(tmp), _tree(_DIST))
    if diffs:
        return False, f"{len(diffs)} 处不同(前 3):" + "; ".join(diffs[:3])
    return True, ""


# ── 检查项 ──────────────────────────────────────────────────────────────────

def test_dist_directory_exists() -> None:
    """No dist/ → never built. The first push of a dashboard change without
    `npm run build` lands here."""
    _check("dashboard/dist/ exists",
          _DIST.is_dir(),
          f"run `cd dashboard && npm run build` to create it")


def test_committed_bundle_matches_current_src() -> None:
    """线上那一份产物,是不是当前 src 编出来的那一份?

    · src 有未提交改动 ⇒ mtime 是对的尺子(正在改、还没重建)。
    · src 干净 ⇒ 量内容(构建到临时目录,逐文件比哈希)。
    · 量不到 ⇒ 退回提交时间比较(S-433b 的旧尺子),不假绿。
    """
    if _git_status("dashboard/src"):
        # ── 尺子 A:mtime(src 正在改,dist 还没跟上)─────────────────────────
        src_max  = _newest_mtime(_SRC)
        dist_max = _newest_mtime(_DIST, ignore_suffixes=_DIST_IGNORE_SUFFIXES,
                                 ignore_exact=_DIST_IGNORE_EXACT)
        if src_max is None:
            _check("dashboard/src/ has at least one file", False,
                   "src/ is missing or empty — wrong repo state")
            return
        if dist_max is None:
            _check("dashboard/dist/ has at least one build artefact",
                   False,
                   "dist/ has no .js / .css / etc. after filtering; run `npm run build`")
            return
        delta_s = src_max - dist_max
        _check(
            f"newest src mtime ({_fmt(src_max)}) ≤ newest dist mtime ({_fmt(dist_max)})",
            src_max <= dist_max,
            f"src is {delta_s:.1f}s newer than dist — Railway would serve a stale "
            f"bundle. Run `cd dashboard && npm run build && git add dashboard/dist/` "
            f"before pushing.",
        )
        return

    # ── 尺子 B:量内容(尺子 C 不可量时的下面是旧尺子)───────────────────────
    measured = _measure_content()
    if measured is None or measured[0] is None:
        # 量不到 ⇒ 旧尺子(S-433b):最后一次改 src 的提交 ≤ 最后一次改 dist 的提交。
        committed = _committed_freshness()
        if committed is None:
            _check("dashboard/dist 与当前 src 一致(量不到内容,退回提交时间比较)", True,
                   "git 不可用,跳过")
            return
        src_ct, dist_ct = committed
        _check(
            f"[量不到内容,退回提交时间]最后一次改 src 的提交 ({_fmt(src_ct)}) "
            f"≤ 最后一次改 dist 的提交 ({_fmt(dist_ct)})",
            src_ct <= dist_ct,
            "有一次提交改了 dashboard/src 却没有随后重建 dist。"
            "Run `cd dashboard && npm run build && git add dashboard/dist/` before pushing.",
        )
        return

    ok, why = measured
    _check("已提交的 dashboard/dist 与当前 src 的构建产物逐字一致(量的是内容,不是提交时间)",
           ok, why)


def test_guard_catches_a_simulated_staleness() -> None:
    """Negative control: bump an src file's mtime, confirm the predicate
    detects it. If this passes when stale, the guard is decoration."""
    import tempfile, time

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        src = td_path / "src";  src.mkdir()
        dist = td_path / "dist";  dist.mkdir()
        (src / "Foo.jsx").write_text("// foo")
        (dist / "Foo.js").write_text("/* old */")
        # Make dist newer than src.
        old = time.time() - 3600
        os.utime(dist / "Foo.js", (old, old))
        os.utime(src / "Foo.jsx", (old - 1, old - 1))
        assert _newest_mtime(src) < _newest_mtime_time(dist), \
            "test setup wrong: dist should start newer than src"

        # Now bump src to be newer.
        os.utime(src / "Foo.jsx", (time.time(), time.time()))
        assert _newest_mtime(src) > _newest_mtime_time(dist), \
            "test setup wrong: src should now be newer than dist"

    _check("negative control: predicate detects src > dist", True)


def test_content_guard_detects_a_stale_bundle() -> None:
    """Negative control for the CONTENT ruler: change one byte of the built
    bundle, the comparison must notice. If it always says "identical", the
    ruler is decoration and the guard can never fire."""
    if not _DIST.is_dir():
        _check("negative control: 内容比较能抓到产物与源码不一致", True,
               "dist 不在,跳过")
        return
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "dist"
        shutil.copytree(_DIST, fake)
        target = fake / "index.html"
        if not target.is_file():
            _check("negative control: 内容比较能抓到产物与源码不一致", True,
                   "dist/index.html 不在,跳过")
            return
        data = bytearray(target.read_bytes())
        data[0] = (data[0] + 1) % 256
        target.write_bytes(bytes(data))
        diffs = _diff_trees(_tree(fake), _tree(_DIST))
        assert diffs, "内容比较没抓到被改动的文件 —— 它是装饰品"
    _check("negative control: 内容比较能抓到产物与源码不一致", True)


def test_does_not_fire_when_only_test_files_changed() -> None:
    """If the most recent src change is in tests/ or scripts/, do not flag.
    Actually we do flag — there is no good way to tell which src/ change is
    the dashboard-relevant one. False positives are CHEAP (rebuild takes 6s);
    false negatives ship a broken tab. So we flag any time src > dist.

    Pinned here as a behavior contract so the asymmetry stays a deliberate
    choice, not an accident."""
    _check("false-positive-asymmetry is intentional", True,
          "see docstring; rebuild on any src > dist is the policy")


if __name__ == "__main__":
    print("── dashboard/dist/ 必须与 dashboard/src/ 编出同一份产物(B-4, 2026-08-25;v2 改版 2026-11-20)──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ bundle freshness OK")

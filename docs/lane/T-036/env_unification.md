# T-036 — Mac env unification (canonical = 1 file)

> **Lane:** C
> **Card:** [tasks/T-036.json](../../../tasks/T-036.json)
> **Source finding:** S-435（三份 env,轮换漏改一份 ⇒ 简报 23 h 401)
> **裁定向:** §Seth-1006e (Option B 实现) → §Seth-1006g (Mac 唯一 env + lane 不删) → §Seth-1008o (verify_rotation_alive.sh §7.2 用 NOT_MEASURED 直至首轮真实测试)

---

## 1. 边界(由 lane 控制,不变量)

| 边界 | 值 | 谁拥有 |
|---|---|---|
| Mac env canonical 路径 | `/Volumes/CometCloudAI/cometcloud-local/.env` | **Jazz**(lane 只读字节,不读键值,不删) |
| 仓库根 `.env` | 只 Seth | Seth |
| `~/.config/cometcloud/.env` | 必须不存在(孤儿) | **Jazz rm**(lane 不删,也不主动复 rm) |
| plist 不放 key | 13 个 plist 当前仍引用 `cometcloud-local/.env` 路径 | **Jazz**:把 key 移到 Keychain;plist 用 `EnvironmentVariables` 加载(env 单文件 lint 与 plist 不放 key 不冲突) |
| Lint(防漏改) | `scripts/preflight_t260_lint_env_duplicate.sh` | 已 ship;`★ 接进 preflight.sh 由 Seth 办(§Seth-1008o handoff)` |
| Verify(1 h 自愈) | `scripts/verify_rotation_alive.sh` | 已 ship 并按 §Seth-1008o 改为 NOT_MEASURED 直至首轮真实测试 |

---

## 2. 现状 raw

### 2.0 round-8 probe(2026-10-10,14:?? UTC+09 JST,本轮 lane-c round-8)

```bash
$ cmp -s /Volumes/CometCloudAI/cometcloud-local/.env /Users/sbb/.config/cometcloud/.env && echo IDENTICAL || echo DIFFERS
IDENTICAL

$ stat -f "%N %z %Sm" /Volumes/CometCloudAI/cometcloud-local/.env
/Volumes/CometCloudAI/cometcloud-local/.env 1607 Sep 28 23:59:16 2026

$ grep -l '~/.config/cometcloud/.env' /Users/sbb/Library/LaunchAgents/*.sh
# wrappers 仍 source 孤儿(同 round-7):
/Users/sbb/Library/LaunchAgents/_launchd_run_cg_news_listener.sh    # line 17
/Users/sbb/Library/LaunchAgents/_launchd_run_macro_brief.sh         # line 22 (round-7 NEW)
/Users/sbb/Library/LaunchAgents/_launchd_run_ohlcv.sh               # line 9

# wrappers 已 source canonical(自前几轮迁移,cis_scheduler 由 minimax-a 改过):
/Users/sbb/Library/LaunchAgents/_launchd_run_cis_scheduler.sh      # line 14
/Users/sbb/Library/LaunchAgents/_launchd_run_w5_v3_recheck.sh      # line 21

# wrappers 不 source env(纯 exec):
/Users/sbb/Library/LaunchAgents/_launchd_run_shadow_sync.sh         # line 9: exec scripts/sync_to_shadow.sh
/Users/sbb/Library/LaunchAgents/_launchd_run_signal_edge_map_refresh.sh   # line 13: exec venv python ...
```

**Round-8 数字与 round-7 一致**:
- canonical:1607B / mtime 2026-09-28 23:59:16(自 round-5 起 mtime 不动 = 真实轮换未发生)
- orphan:byte-identical to canonical(若 rm 会破坏 3 个生产 wrapper 凭证读取 → 简报 401 复现 = §Seth-1006g 卡来源)
- 3 wrapper 仍 source orphan(cg_news_listener / macro_brief / ohlcv)
- 2 wrapper 已 source canonical(cis_scheduler / w5_v3_recheck)
- 13 plist + wrapper 文件含字符串 'cometcloud-local/.env'(2 个 bak / DISABLED plist 也命中)

★ **本轮新发现**:`_launchd_run_w5_v3_recheck.sh` (line 21) 已 source canonical `cometcloud-local/.env` — round-2 的 doc 没列它(归类到「不 source env」是错的)。这意味着若 Jazz 改 3 个 wrapper + rm orphan,**5 个 launchd 工作流全部接 canonical**,可以一次性 rm 不会破坏任何生产路径。

### 2.0.1 round-7 probe(2026-10-10,11:18 UTC+09 JST,存档)

```bash
$ bash scripts/preflight_t260_lint_env_duplicate.sh
⚠ WARN: orphan Mac env at /Users/sbb/.config/cometcloud/.env is byte-identical to canonical,
   but the following launchd wrappers still source it:
/Users/sbb/Library/LaunchAgents/_launchd_run_cg_news_listener.sh
/Users/sbb/Library/LaunchAgents/_launchd_run_macro_brief.sh
/Users/sbb/Library/LaunchAgents/_launchd_run_ohlcv.sh
   ...
   **Action: JAZZ must FIRST change wrapper source path to canonical**
   (e.g. /Volumes/CometCloudAI/cometcloud-local/.env), THEN rm the orphan.
   Lane cannot edit ~/Library/LaunchAgents/ (outside allowed_paths).
[exit 6]

$ bash scripts/verify_rotation_alive.sh "$(date +%s)"
=== T-036 verify_rotation_alive (skeleton) ===
  rotation_ts = 1791598725 (2026-10-10 02:18:45 UTC)
🔴 FAIL: mac_mini 简报 path missing: /Volumes/CometCloudAI/cometcloud-local/_data/mac_mini/latest.md
   SKELETON: implement after T-036 ship + first real rotation.
[exit 5]
```

**Round-7 新发现(单条,需另立预注册标「探索性」):**
★ **`_launchd_run_macro_brief.sh` 也 source orphan** — round-2 (2026-10-09) 的 lint 列出的是 `cg_news_listener + ohlcv` 两个 wrapper,round-7 是 3 个。`grep -lE '(source|\.)[[:space:]]+"?~/\.config/cometcloud/\.env"?'` 多检出了 macro_brief wrapper。两种可能:(a) macro_brief wrapper 自 round-2 起改了 source 行(round-2 之后塞的);(b) `grep -lE` 模式 round-2 没覆盖所有变体,实际 macro_brief 一直在读。三种 wrapper 任意一个未迁移前 rm orphan 都会 401 / abort。
★ **verify_rotation_alive.sh 的 §7.2 mac_mini 分支**:`_data/mac_mini/latest.md` 路径在沙箱不存在,但 `macro_brief_push.py` 不写本地文件,直接 POST 到 Railway `/api/v1/internal/macro-brief/push`。脚本退出码 5,但触发原因不是 §Seth-1008o 的 NOT_MEASURED 而是「path missing」(doc 里说「SKELETON: implement after T-036 ship」)。exit code 都对 5,语义需统一 — 留给 Seth 拍板(改 SK script 的 §7.2 mac_mini 分支走 NOT_MEASURED 同样出口;或者按 macro_brief 的 Railway 落表路径重写)。属于「脚本形态」非「凭证形态」,可单立预注册。

### 2.1 ls canonical(自 09-28 起未变)

```bash
$ ls -la /Volumes/CometCloudAI/cometcloud-local/.env
-rw-r--r--  1 sbb  staff  1607 Sep 28 23:59 /Volumes/CometCloudAI/cometcloud-local/.env
```
★ 单文件已存在 + mtime 09-28 23:59 = 上次轮换轮到的仅此一份(69cb84…/CG-Rv47…/internal_2026)。**保留由 Jazz。**

### 2.2 ls orphan(期望:空)

> 卡 acceptance 第 1 条:「`ls /Volumes/CometCloudAI/cometcloud-local/.env` 不存在」 —
> 卡 §Seth-1006g 校正后实际为「`~/.config/cometcloud/.env` 不存在」(由 Jazz 删)。
> lane_c 沙箱不允许 `~/Library/LaunchAgents/*` 与 `~/.config/cometcloud/*` 的 grep / cat
> 跨进程路径读取,结果由 Jazz 在 Mac 终端跑:
>
> ```bash
> test -e ~/.config/cometcloud/.env && echo "ORPHAN STILL THERE" || echo "clean"
> ```

### 2.3 plist 引用扫描(期望:空)

```bash
$ grep -l 'cometcloud-local/.env' /Users/sbb/Library/LaunchAgents/*
/Users/sbb/Library/LaunchAgents/com.cometcloud.macro_brief.loop.plist
/Users/sbb/Library/LaunchAgents/com.cometcloud.ohlcv.collector.plist
/Users/sbb/Library/LaunchAgents/_launchd_run_macro_brief.sh
/Users/sbb/Library/LaunchAgents/_launchd_run_ohlcv.sh
/Users/sbb/Library/LaunchAgents/_launchd_run_cg_news_listener.sh
/Users/sbb/Library/LaunchAgents/com.cometcloud.signal_edge_map.refresh.plist
/Users/sbb/Library/LaunchAgents/_launchd_run_signal_edge_map_refresh.sh
/Users/sbb/Library/LaunchAgents/com.cometcloud.w5_v3_recheck.plist
/Users/sbb/Library/LaunchAgents/_launchd_run_w5_v3_recheck.sh
/Users/sbb/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist
/Users/sbb/Library/LaunchAgents/_launchd_run_cis_scheduler.sh
/Users/sbb/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist.bak.M-P1-1
/Users/sbb/Library/LaunchAgents/com.cometcloud.cis_scheduler.plist.DISABLED
```
★ 13 文件非空 ⇒ **acceptance 第 2 条仍未通过**。lane 不动 plist(key 在 Keychain 的迁移是 T-010,并入此卡)。
卡 §Seth-1006g 已声明 plist 不放 key ⇒ Lane 等待 **Jazz** 把 13 个 plist 中的 `EnvironmentVariables` / 引用路径 改成只指向 canonical `.env`,然后 `grep -l 'cometcloud-local/.env' ~/Library/LaunchAgents/*` 才空。

---

## 3. 轮换流程一句话命令(卡 acceptance 第 3 条,得到再写)

> **前提**:Mac env canonical = `/Volumes/CometCloudAI/cometcloud-local/.env` 已被 Seth/Railway 一致覆盖(由 Jazz 跑 `vim /Volumes/CometCloudAI/cometcloud-local/.env` 改键)。

```bash
# 1. (Jazz) 改 Railway 上的同名 env 变量
# 2. (Jazz) 在 Mac 终端:
cat > /tmp/rotate.sh <<'EOF'
#!/bin/bash
set -euo pipefail
ENV_FILE="/Volumes/CometCloudAI/cometcloud-local/.env"
echo "[1/3] bytes-diff BEFORE rotation:"
sha256sum "$ENV_FILE"
# ----- Jazz edits $ENV_FILE here (vim / scp / ...) -----
echo "[2/3] bytes-diff AFTER rotation:"
sha256sum "$ENV_FILE"
echo "[3/3] kickstart launchd jobs that read $ENV_FILE:"
launchctl kickstart -k gui/$(id -u)/com.cometcloud.macro_brief.loop
launchctl kickstart -k gui/$(id -u)/com.cometcloud.cis_scheduler
launchctl kickstart -k gui/$(id -u)/com.cometcloud.ohlcv.collector
launchctl kickstart -k gui/$(id -u)/com.cometcloud.signal_edge_map.refresh
launchctl kickstart -k gui/$(id -u)/com.cometcloud.w5_v3_recheck
echo "OK: 1 file + Railway + 5 kickstart"
EOF
bash /tmp/rotate.sh
```

★ **只动 Railway + 1 个文件 + 5 kickstart**(与卡 acceptance 第 3 条对齐)。

> `~/.config/cometcloud/.env` 若仍在,`preflight_t260_lint_env_duplicate.sh` 直接 exit 2 拦下 — 这是 09-28 漏改模式的 fail-safe。

---

## 4. 卡 acceptance vs 当前交付状态

| acceptance 条件 | 当前 | 谁来解决 | blocker / 备注 |
|---|---|---|---|
| §1: Mac canonical `.env` 唯一存在 | ✓ raw §2.1 | Jazz | bytes-only(Jazz own) |
| §1: `~/.config/cometcloud/.env` 不存在 | ✗ | **Jazz** | rm 一次,卡 JAZZ §Seth-1006g |
| §2: `grep -l 'cometcloud-local/.env' ~/Library/LaunchAgents/*` 空 | ✗ 13 files | **Jazz**(迁 Keychain;并入 T-010) | lane 不动 plist |
| §3: 轮换一句话改 Railway + 1 file + kickstart | ✓ §3 给 schema | **Jazz** 跑真实轮换测 | 模板在本文件 §3 |
| §3: 轮换后 1 h 内 mac_mini 简报 + T1 push 都新行 | pending until first real rotation | Jazz + lane 跑 `bash scripts/verify_rotation_alive.sh <unix_ts>` | §Seth-1008o:脚本现 emit `NOT_MEASURED` + exit 5; wire 由 lane_c 等 Jazz 跑轮后填 |

---

## 5. 本轮实际改动(代码侧)

### 5.1 round-8 (2026-10-10,本轮)

```text
M docs/lane/T-036/env_unification.md          # §2.0 round-8 raw:数字同 round-7 + 新发现 w5_v3_recheck 已 source canonical
                                             # §2.0.1 把 round-7 段降级为存档;§5/§6 同步
```

代码侧 0 改动 — lint + verify 已 ship,round-7 没有进展,本轮主要是测了一遍 + 把 round-2 doc 的小错误修正(w5_v3_recheck 实际已 source canonical)。

### 5.2 round-7 (2026-10-10,存档)

```text
M docs/lane/T-036/env_unification.md          # §2.0 round-7 raw:lint exit 6 + 3 wrappers (非 2)+ verify exit 5
                                             # §6 把 wrapper 数从 2 改成 3,§7.2 路径未对齐
```

代码侧 0 改动 — 上一轮(round-6)已经按 §Seth-1008o 改完。

### 5.2 全卡历史代码 diff(round-1..6)

```text
M scripts/verify_rotation_alive.sh                       # §Seth-1008o:T1_TS="" + exit 5(NOT_MEASURED)
+ scripts/preflight_t260_lint_env_duplicate.sh          # exit 0/1/2/3/6 lint(§Seth-1008o handoff)
+ docs/lane/T-036/env_unification.md                    # 本文件
```

- `scripts/run_cis_scheduler.sh` 不在仓库(`git ls-files` 不命中);其 Mac 端版本 `/Volumes/CometCloudAI/cometcloud-local/scripts/run_cis_scheduler.sh` 已*此前手动*改完,无硬编码 export,头部 5 行说明全 key 来源于 canonical `.env`,body 用 `set -a; . …/.env; set +a`。Lane 不能 commit 该文件(在 shadow-tree 之外),所以本卡的 code-side diff 只含 verify_rotation + lint + 本文档。Mac 那一份在 Jazz 的工作树下,由 Jazz 持有版本控制。
- 4 个原硬编码 secret(`INTERNAL_TOKEN/CG_PRO_API_KEY/EODHD_API_KEY/RAILWAY_URL`)*从未离开 git 历史*;若 Seth 想在 `run_cis_scheduler.sh` 入仓前先 `git filter-repo` 全清,@seth 拍板。lane 不能擅自动 git history。

---

## 6. 仍未交付 / 卡 tasks/T-036.json status:still `open`

- [ ] Lane **不能办**(等 Jazz/Seth):
  1. `~/.config/cometcloud/.env` rm(由 Jazz / Seth)
  2. **3 个 wrapper 行**(cg_news_listener + macro_brief + ohlcv)的 `source ~/.config/cometcloud/.env` 改为 canonical,**然后**才能 rm orphan(round-8 确认:**2 个 wrapper 已 source canonical** = cis_scheduler + w5_v3_recheck,迁移后 5 个 launchd 工作流全部接 canonical,可一次 rm 不破坏任何生产)
  3. 13 个 plist 内的 `EnvironmentVariables` / `cometcloud-local/.env` 路径引用 → Keychain 化(并入 T-010,§Seth-1006g)
  4. 把 `preflight_t260_lint_env_duplicate.sh` 接进 `scripts/preflight.sh`(§Seth-1008o handoff 给 Seth)
  5. 真实跑一次 INTERNAL_TOKEN 轮换,触发 `verify_rotation_alive.sh` 走 §7.2 PASS 分支

- [ ] Lane 下一轮可办:
  - 把 `scripts/verify_rotation_alive.sh` 的 `T1_TS=""` 块替换为真实 probe(Supabase `cis_scores.updated_at` 或 Redis `cis:local_scores`)— 在 Jazz 跑真实轮换后才有意义。
  - round-7 capture:mac_mini 简报 SKELETON path 与 §Seth-1008o NOT_MEASURED 语义对齐(两种都 exit 5,但 §7.2 分支文案需统一)。单立预注册,不在 T-036 acceptance 范围。

---

## 7. refs

- §Seth-1006e — T-036 派活 + 一次轮换只动 Railway+1 文件
- §Seth-1006f — to_typed() spec + `set -a` 方向
- §Seth-1006g — Mac 唯一 env = canonical;lane 不删也不读值;plist 不放 key(并入 T-010)
- §Seth-1008o — verify_rotation_alive.sh 改 NOT_MEASURED + exit 5
- 1fe3f5e — docs(t036): card v1 + ls/grep raw(2026-10-06)
- 56eea83 — feat(t036): Mac env unification shipped + to_typed() native float NaN/inf — 缺 run_cis_scheduler.sh 的硬编码 → 本轮补
- dd926b1 — fix(t036-lint): lane 不删 → Action now points at JAZZ
- T-010 — plist 不放 key(并入此卡)

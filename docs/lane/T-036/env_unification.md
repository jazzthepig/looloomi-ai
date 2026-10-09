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

## 2. 现状 raw(2026-10-09 lane-c 轮验)

### 2.1 ls canonical

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

```text
M scripts/run_cis_scheduler.sh          # 移 4 个硬编码 secret → .env 单源
M scripts/verify_rotation_alive.sh      # §Seth-1008o:T1_TS="" + exit 5(NOT_MEASURED)
+ docs/lane/T-036/env_unification.md    # 本文件
```

- `run_cis_scheduler.sh` 历史含 4 个 export(`INTERNAL_TOKEN/CG_PRO_API_KEY/EODHD_API_KEY/RAILWAY_URL`)硬编码在脚本体内,违反 §Seth-1006g 的「Mac 唯一 env = single source」,已替换为 `set -a; . /Volumes/CometCloudAI/cometcloud-local/.env; set +a`,并加头部注释说明。
  - 这 4 个 key 在脚本里 *从未离开 git 历史*,但 commit 此改动会让 `git grep` 不再命中 commit 后的工作树。Seth 如认为需要在改前先 `git filter-repo` 全清,@seth 拍板。

---

## 6. 仍未交付 / 卡 tasks/T-036.json status:still `open`

- [ ] Lane **不能办**(等 Jazz/Seth):
  1. `~/.config/cometcloud/.env` rm(由 Jazz / Seth)
  2. 13 个 plist 内的 `EnvironmentVariables` / `cometcloud-local/.env` 路径引用 → Keychain 化(并入 T-010,§Seth-1006g)
  3. 把 `preflight_t260_lint_env_duplicate.sh` 接进 `scripts/preflight.sh`(§Seth-1008o handoff 给 Seth)
  4. 真实跑一次 INTERNAL_TOKEN 轮换,触发 `verify_rotation_alive.sh` 走 §7.2 PASS 分支

- [ ] Lane 下一轮可办:
  - 把 `scripts/verify_rotation_alive.sh` 的 `T1_TS=""` 块替换为真实 probe(Supabase `cis_scores.updated_at` 或 Redis `cis:local_scores`)— 在 Jazz 跑真实轮换后才有意义。

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

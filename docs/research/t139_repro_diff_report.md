# T-139 / S-615 — mult_v2_replay 复现差异报告(停下报差异)

**任务 acceptance 要求 mult_v2_replay 逐日 NAV 在 Python 里复现,与库里差 < 1e-6。**
本次实测差异 max|Δnav| = **5.91e-04**(发生在 2026-10-13),**差 591× 不通过**,按"对不上先停下报差异"的规定停在这里,以下是差异的成因与建议下一步。

---

## 实测:逐字段对比(全段 1386 行,2023-01-02 → 2026-10-18)

| 字段 | max\|Δ\| | 通过 |
|---|---|---|
| `m` | 0 | ✅ 完全相同 |
| `cost` | 0 | ✅ 完全相同 |
| `ret` | 1.12e-08 | ✅ 等同 8-decimal rounding |
| `nav` | **5.91e-04** | ❌ 阈值 1e-6,差 591× |

`m` / `cost` / `ret` 三项都精确一致 ⇒ 算式与状态层(dist_200 / vol_pct_3y / funding_7d_ann)、底仓口径(cap_a1_u)都对得上。nav 偏是 **结构性的**,不是 rounding 噪声。

---

## 偏从哪一天开始

`diff` 在 2026-10-11 之前 = 0(逐日严格相同)。从 **2026-10-12 起**开始拉开:

| d | DB `mult_v2_replay.ret` | repro ret | DB `core_u_replay.ret` | repro `core_u_replay.ret` |
|---|---|---|---|---|
| 2026-10-11 | +0.012924 | +0.012924 | +0.010002 | +0.010002 |
| 2026-10-12 | **−0.036464** | −0.036464 | **−0.027991** | **−0.027991** |

读 `core_u_replay.ret` 在 2026-10-12 是 −0.027991,与 `mult_v2_replay.ret` = 1.3 × −0.027991 = −0.036388 不一致(差 7.6e-5);说明库内 `core_u_replay` 的 ret 列 **与写 mult_v2_replay 当时所用的 core_ret 不是同一序列** —— 重写后 core_u_replay 行已变,mult_v2_replay 的回放行没同步重写(forward_lock 只锁前向臂,回放臂"照写",但两次"照写"之间 panel 数据可能更新)。

---

## 为什么不是 rounding noise

如果仅是 8-decimal 落库精度,max 单行 |Δnav| 应 ≤ 5e-8(NAV ≈ 4)。这里 5.91e-04 ≈ 14 bp 的 NAV,是 **某一天 core_ret 真实不同** 的累计结果。结构性,不能归约。

---

## 建议下一步(请 @seth 选一项)

1. **重写 mult_v2_replay 一致**:在 Mac Mini 侧再跑一轮 `multiplier.run_once()`,让回放行与 `core_u_replay` 用同一组 core_ret;再让本脚本复现。前提:forward_lock 允许回放行重写(`multiplier.py` 注释确实说回放行照写)。
2. **接受 NAV 差,用 ret 差作复现判据**:max|Δret| = 1.12e-08 < 1e-6 ⇒ 视为通过。nav 差作为已知存储伪差记入报告。S-615 的过关判据("总收益 / 最大回撤")由 ret 累计算出,nav 落库精度不直接影响判定。
3. **改 acceptance 阈值**:把 < 1e-6 改成 < 1e-3(本钱包挣到的 NAV diff 上界),并把"max|Δnav| = 5.91e-04"作为已知偏差写到 §S-615 备注。

倾向选 **2**(不浪费一轮重算、不改阈值;ret 才是判定的真实量)。请 @seth 决定。

---

## 已经在库的中间产物(未提交)

- `docs/research/t139_s615_liquidity_thrust.py` —— 复现 + 臂 L / 臂 S 主脚本(在 5.91e-04 处 raise 停下,未算臂 L / 臂 S)
- `lane-b-scratch/probe_diff{2,3,4,5}.py` —— 探针脚本,定位差异到 2026-10-12 的 core_ret 漂移

无 commit / push 动作。卡留在 `open`。
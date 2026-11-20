# 部署核对：两个问题，一份判据（Seth, 2026-11-20）

**为什么有这份文件.** 11-19 到 11-20，`seth_bot` 有三次合并在**部署核对**这一步报失败，
而合并**其实已经落地**了（push 成功、线上 `/health` 正常）。查下来根因不是部署坏了，
是**两个不同的问题被当成一个问**。写下这份是为了下一个改 `scripts/deploy_paths.py`
的人不会把它"修"成一个说谎的门。

---

## 一、现在这个门在问什么

`scripts/deploy_paths.py`（唯一的清单源头，`railway.json` 由它生成，测试核对两边相同）：

> **线上是不是最新？** —— 线上那一版与目标那一版之间**没有任何运行时路径的差别** ⇒ 就是最新。

实现是两点 diff（`live..want`，两棵树直接比）。**这个判据是对的**，理由在下面第三节。

调用链：

```
seth_bot.do_commit / do_merge
  └─ verify_after_deploy()                        scripts/seth_bot/seth_bot.py
       └─ bash scripts/wait_for_deploy.sh          WANT_SHA=<刚推的 sha>
            ├─ 读线上 /internal/build-state 的 git_sha  ⇒ LIVE
            ├─ LIVE == WANT              ⇒ "✅ live = WANT"
            ├─ LIVE 非空 且 deploy_paths.py --is-current LIVE WANT 退出码 0
            │                            ⇒ "✅ live = … · 与 … 之间没有运行时路径的改动"
            └─ 否则:最多等 900 秒 ⇒ "✗ … 内没有等到 … 上线"
```

---

## 二、被混在一起的两个问题

| | 问题 | 判据 | 归谁 |
|---|---|---|---|
| **Q1** | **这次推送要不要部署？** | Railway 的 `build.watchPatterns` 看**这次推送改了什么** | Railway（`railway.json`） |
| **Q2** | **线上是不是最新？** | 线上那棵树与目标那棵树**有没有运行时路径的差别** | `scripts/deploy_paths.py` |

**Q1 是一次推送的属性，Q2 是两棵树的关系。** 11-19 实测的坑：两条血统分叉时
（两个 agent 各推 `main`），Q1 说"这次推送只改了 preflight / 卡片 / 测试 ⇒ 不触发部署"，
Q2 说"线上那棵树带运行时改动、目标树没有 ⇒ 不是最新" —— 两个都成立，
但**当前代码只问了 Q2**，于是 `wait_for_deploy.sh` 白等满 900 秒，报一个假失败。

**这不是"部署坏了"，是门问错了问题。**

### 现象（11-19 ~ 11-20 实测）

- `20261119-13-merge-t228`：push 成功（`f9adf3bc`），`deploy_ok: false` —— 报部署失败。
- `20261119-20-merge-t062`：同样，`deploy_ok: false`，而 `971edfa5` 后来确实在 main 上。
- `20261119-2345-merge-t005-retry`：**同样血缘、同样门**，`deploy_ok: true` ✅。

三者的区别只在"推之前线上那一版是不是已经是目标树的祖先"。**分叉时必假失败。**

---

## 三、为什么判据必须是两点 diff，**不许改成三点**

试过、验过、回退了。把 `changed_between` 改成三点（`merge-base..b`）会让门**说谎**：

- 三点只问"目标从分叉点起改了什么"，会把**线上那一版多出来的运行时内容**从比较里抹掉。
- 抹掉之后 `--is-current` 退出码 0 ⇒ 门报"✅ 不用部署" ⇒ **线上跑的根本不是目标树的代码**。
- 那不是省事，那是**报一个假的绿**。

现在的两点语义把两棵树的运行时内容差异都列出来，线上带的运行时改动**看得见**。
这个语义被 `tests/test_deploy_paths.py::test_divergent_lineages_are_judged_on_the_two_trees_not_the_merge_base`
钉住 —— 改判据的人会先撞到那条测试红。

**"当前是不是最新"是一个关于两棵树的问题，不是关于推送的问题。** 两者混起来才出事。

---

## 四、待 Jazz 拍板：把 Q1 拆出来

现状是 `deploy_ok` 一个布尔同时承担了两件事（"线上是最新的" 与 "这次部署跑完了"），
分叉时必然出现"合并落地但门报红"。**建议的拆法**（未实施 —— 改了 `deploy_ok` 的含义，
属于口径变更，不该由 agent 单方面定）：

1. `seth_bot` 在 push **之前**记下 `origin/main` 的旧 tip（= 这次推送的父）。
2. `wait_for_deploy.sh` 用它分三档：
   - `LIVE == WANT` ⇒ ✅ 最新且已部署；
   - Q1 为假（本次推送没碰运行时路径）**且** Q2 为假（线上带运行时内容不在目标树里）
     ⇒ ⚠️ **"本次推送不触发部署，线上仍落后于目标树"** —— 这是**要看的**，不是失败；
   - Q1 为真（本次推送碰了运行时路径）⇒ 照旧等上线，超时报失败。
3. `deploy_ok` 拆成 `deploy_current`（Q2）与 `deploy_triggered`（Q1），两边都记。

**在 Jazz 定这个之前，运维层的读法是：**
`deploy_ok: false` **先当作"部署核对没通过"读，不要当作"合并没落地"** ——
以 `git log origin/main` 和线上 `/internal/build-state` 为准。

---

## 五、相关文件

| 文件 | 角色 |
|---|---|
| `scripts/deploy_paths.py` | 清单源头 + Q2 判据（**不要改 diff 的点数**） |
| `railway.json` | Q1 的判据（`build.watchPatterns`，由上面那个生成） |
| `scripts/wait_for_deploy.sh` | 门（当前只问 Q2） |
| `scripts/seth_bot/seth_bot.py` | `verify_after_deploy()` → 门 |
| `scripts/deploy_health_gate.py` | 另一处用同一判据（`_runtime_current`） |
| `tests/test_deploy_paths.py` | 钉住语义：清单一致、运行时路径清单、两棵树语义 |

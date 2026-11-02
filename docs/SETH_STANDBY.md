# Seth 待命模式:Claude 用不了的时候,MiniMax lane 顶 Seth 的活(Jazz 11-02 裁定,DECISIONS)

**前提已经在了:** 三个 lane 由 lane_bot 自动醒(每 15 分钟、额度预算内),交付推 `lane-x/T-NNN` 分支;seth_bot 每 5 分钟
跑 preflight 后合并、推 main、Railway 自动部署。**Seth 平时做的三件事里,只有「派卡 / 叫醒」和「排合并」需要一个人** ——
下面是 Jazz 在 terminal 里替 Seth 做这两件事的最短路径。lane 碰不到 `.seth_bot/`(禁区),所以排合并一定是人。

## 1. 派活(两种)

**一句话的事** —— 直接叫醒,不开卡(lane 只能改它名下卡允许的路径;没卡时它只能做只读 / 报告类):

```bash
cd ~/Projects/looloomi-ai && python3 scripts/seth_bot/queue.py wake lane-a "看一下 loop_attempt 里 _news_feed_loop 最近 6 轮为什么 failed_sources 一直有 SEC,报原因,不改代码"
```

**要改代码的事** —— 复制模板开一张卡(卡号用 BOARD 上最大的 +1),填 `title` / `acceptance` / `allowed_paths`,然后叫醒:

```bash
cd ~/Projects/looloomi-ai && cp tasks/_TEMPLATE_standby.json tasks/T-231.json && open -e tasks/T-231.json
python3 scripts/task_board.py && python3 scripts/seth_bot/queue.py commit -m "tasks: T-231 (standby card)" tasks/T-231.json tasks/BOARD.md
python3 scripts/seth_bot/queue.py wake lane-a "T-231:按卡上的 acceptance 做到能交付"
```

模板的 `allowed_paths` 含 `src/`、`tests/`、`docs/`、`migrations/`(迁移只写 SQL 文件,**应用**仍是 Jazz 在 Supabase 控制台);
禁区不变(Shadow/、scripts/lane_bot、scripts/seth_bot、.seth_bot/、PROJECT_STATE)。

## 2. 收活

lane 的最终回复会贴进 `MINIMAX_SYNC.md`(也在 `python3 scripts/lane_bot/lane_bot.py --status`)。它推了分支、卡改成 `in_review` 之后:

```bash
cd ~/Projects/looloomi-ai && python3 scripts/seth_bot/queue.py merge lane-a/T-231
python3 scripts/seth_bot/queue.py status
```

seth_bot 会:范围检查(改动 ⊆ 卡的 allowed_paths)→ preflight(红就拒,结果在 `.seth_bot/done/<id>.json`)→ 合并推 main →
Railway 部署 → 部署核对。**红了就把 done 里的 detail 原文叫醒 lane 去修**,不要自己改。

## 3. 不要做的

- 不要在主目录 `git switch` / `stash`(seth_bot 会整轮拒绝;钩子也会拦)。
- 不要把 `.env` / key 给 lane;lane 只有 publishable key(只读)。
- 迁移、Railway env、真钱开关:还是 Jazz 的手。
- 额度:`python3 scripts/lane_bot/lane_bot.py --status` 第二行看 5 小时窗口;停了就是在等窗口,不用动。

## 4. Seth 回来之后

读 `MINIMAX_SYNC.md` 里待命期间的 §段、`.seth_bot/log.txt`、`git log --since`;把 lane 交付里的数字进台账(lane 写不了台账);
PROJECT_STATE 头部补上这段。

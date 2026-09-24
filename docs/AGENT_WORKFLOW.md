# AGENT_WORKFLOW.md — 多 agent 协作机制(Jazz 2026-09-24 批准,生效)

*Seth。依据:本仓库过去一周的协作事故 + 2026 年社区主流做法(来源见文末)。*

## 保留什么,改什么

Jazz 采用半自动、全程留档的开发方式,是为了看清全局,也为了让他的决策和策略被每个 agent 共享、一起成长。
**这部分不改:** Jazz 是唯一决策者;台账(集体记忆和坟场)照写;MINIMAX_SYNC 里的讨论和结论照写。

**只改造成事故的机制:**

| 以前 | 现在 |
|---|---|
| 四个 agent 共用一个工作目录 | 每个 lane 一个 worktree |
| 谁都能推 main | lane 推自己的分支,Seth 合并;钩子在推送时拦截 |
| 待办写在 SYNC 的散文里 | 待办是 `tasks/T-*.json` 任务卡,看板 `tasks/BOARD.md` 自动生成 |
| agent 自己宣布「✅ 完成」 | 完成 = 合并者跑了验收查询、写下测得的值 |
| 决定散在 CLAUDE.md、台账、SYNC 里 | `docs/DECISIONS.md` 一条一行,开工先读 |
| 结论只写 🔴/✅ | 结论段落必须写「基准:」「regime:」「判据:」(守卫检查) |

## 开工顺序(每次开工、每次压缩上下文之后)

1. `docs/DECISIONS.md` —— Jazz 的决定和理由
2. `tasks/BOARD.md` —— 自己名下的卡
3. 卡上写的 `source`(台账条目、SYNC 段落)
4. **从文件继承来的结论只当假设**:动手前用原始数据核一遍

## 工作目录

```
~/Projects/looloomi-ai            main。只有 Seth 在这里合并
~/Projects/looloomi-ai-lane-a    Minimax-A
~/Projects/looloomi-ai-lane-b    Minimax-B
~/Projects/looloomi-ai-lane-c    Minimax-C
```

一次性建立(Mac 侧):`bash scripts/setup_lane_worktrees.sh`。
它会建三个 worktree、把 `.env` 链接进去,并启用 `scripts/githooks/pre-push`:**lane worktree 推 main 会被拒绝。**
Mac 数据根 `/Volumes/CometCloudAI/cometcloud-local/` 不在仓库里,照旧由各 lane 维护。

## 一个任务的完整流程

**lane(以 A 做 T-001 为例):**

```bash
cd ~/Projects/looloomi-ai-lane-a &&
git fetch origin &&
git switch -c lane-a/T-001 origin/main
```

改卡上 `allowed_paths` 里的文件,不碰 `forbidden_paths`。做完:

```bash
python3 scripts/task_board.py &&
bash scripts/preflight.sh &&
git add <卡上允许的路径> tasks/T-001.json tasks/BOARD.md &&
git commit -m "<type>(<scope>): T-001 <subject>" &&
git push -u origin lane-a/T-001
```

提交前把卡片 `status` 改成 `in_review`,在 `notes` 写上自己测得的值(**和之前的值并列**)。SYNC 里只需一行:「T-001 待审」。

**Seth(合并者):**

1. 在主工作目录拉分支,在合并后的代码上跑 preflight
2. **自己跑卡上的验收查询**,把测得的值写进 `verified: {by: seth, value: ..., at: ...}`,状态改 `done`
3. 需要建表或改列的,在合并前执行(规则 5b 不变)
4. 台账编号(S- / M-)在合并时分配,两个窗口撞号的问题就不存在了
5. `python3 scripts/task_board.py` 重新生成看板,合并推送

## 新任务怎么产生

Jazz 拍板或讨论出结论 → Seth 开卡(或 lane 起草卡、Seth 审)。
卡必须有:负责人、允许改的文件、**禁止碰的文件**、验收查询、之前的值。缺一项,`tests/test_task_cards.py` 不让过。

## 来源

- [Git worktrees for parallel AI coding agents — Upsun](https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents)
- [How to Run a Multi-Agent Coding Workspace (2026) — Augment Code](https://www.augmentcode.com/guides/how-to-run-a-multi-agent-coding-workspace)
- [Parallel Agentic Development With Git Worktrees — MindStudio](https://www.mindstudio.ai/blog/parallel-agentic-development-git-worktrees)
- [Use a Merge Queue for Coding Agent Pull Requests — Coding Agent Guide](https://codingagentguide.com/posts/merge-queues-for-coding-agent-pull-requests/)
- [Agent pull requests are everywhere — GitHub Blog](https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/)
- [Claude Code Multi-Agent Orchestration: 2026 Guide — Tembo](https://www.tembo.io/blog/claude-code-multi-agent-orchestration)

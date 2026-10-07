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

## 第一次复盘后的四条补充(Seth,2026-09-26,S-426)

两天实测:origin 上**一个 lane 分支都没有**;main 上 11 张 lane 卡全是 `open`,而数据显示其中几张其实已经做完;
另有一个**第二个 T1 写入端**每小时抢在常规引擎之后推一次。机制本身没错,漏在四处:

**1. Mac 侧的活不在 worktree 里,就不能靠分支和合并来把关。**
`cometcloud-local/` 不在仓库里,改完即生效,没有「合并前」这一步。所以 Mac 侧的规矩是:
- **不许手动往生产推 T1 / 任何生产表。** 试跑一律 `--dry-run` 或不带 token;要推生产,先在 SYNC 写一行「几点、哪个脚本、为什么」。
  实测:09-24 起 19 次非整点 T1 推送,DQS 全空、confidence 与常规引擎不同 —— 网站在两个版本之间来回切。
- Mac 侧卡片的验收**只看数据**,合并者跑卡上的 SQL 就能判;不必等 PR。

**2. 谁拍板:Jazz 只拍 `DECISIONS.md` 级别的事**(产品边界、钱、风险、key、策略取舍)。
合并顺序、测试常量、卡片范围、谁先提交 —— **问 Seth**(SYNC 里写 `@seth`),不要问 Jazz。
实测:B 把「棘轮常量从 111 改成 107」做成三选一请 Jazz 拍;C 把「A 和 C 谁先提交」请 Jazz 拍。两件都不是 Jazz 的事。

**3. 棘轮常量随 PR 一起改,不算越界。** 某个棘轮的数降了,就在本 PR 里把基线改成新数(只改那一行常量)。
降是好事,不应该让任何人等。棘轮现在一律数 `git ls-files`(`tests/_source.py::tracked_py`),
不再数磁盘 —— 以前主目录的两个未跟踪文件让同一份代码在主目录算 111、在 lane 算 107。

**4. 提交身份按 lane 区分。** 现在所有提交都署名同一个人,事后分不清谁改了什么。
`setup_lane_worktrees.sh` 已给每个 worktree 设 `user.name`(`Minimax-A` / `-B` / `-C`);已建好的 worktree 手动跑一次:
`git config extensions.worktreeConfig true && git -C ~/Projects/looloomi-ai-lane-a config --worktree user.name "Minimax-A"`(B、C 同理)。
**必须 `--worktree`**:不带它会写进共享配置,把 main 的署名也一起改了。

**5. 审阅结论写在卡上,不只写在 SYNC(S-433e)。** 09-27:C 的 spec 审阅写在 SYNC §S-433b(就在 C 的 spec 段下面 33 行),
C 按「下一个 S- 编号」去搜,没找到,于是把「等审阅」当成现状又问了一轮。**找回复一律搜卡号(`grep T-005`)**;
合并者给出的裁决同时写进卡的 `notes` —— 开工先读卡,就不会漏。

## 来源

- [Git worktrees for parallel AI coding agents — Upsun](https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents)
- [How to Run a Multi-Agent Coding Workspace (2026) — Augment Code](https://www.augmentcode.com/guides/how-to-run-a-multi-agent-coding-workspace)
- [Parallel Agentic Development With Git Worktrees — MindStudio](https://www.mindstudio.ai/blog/parallel-agentic-development-git-worktrees)
- [Use a Merge Queue for Coding Agent Pull Requests — Coding Agent Guide](https://codingagentguide.com/posts/merge-queues-for-coding-agent-pull-requests/)
- [Agent pull requests are everywhere — GitHub Blog](https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/)
- [Claude Code Multi-Agent Orchestration: 2026 Guide — Tembo](https://www.tembo.io/blog/claude-code-multi-agent-orchestration)

## 自动化(S-500,2026-10-07 起)—— Jazz 不再当传话的人

Jazz:「一个一个等你复核这样效率很低,因为不是实时和全自动化的。」实测瓶颈不是审阅本身,是**每个改动要过 Jazz 的手三次**:
转述 lane 的报告 → 粘贴 Seth 的提交块 → 把核对输出粘回来。而 origin 上**一个 lane 分支都没有**(10-07 实测),交付全走 SYNC 散文 + 补丁。

**现在的路:**

```
lane 推 lane-x/T-NNN ──► GitHub Actions「Lane gate」自动跑:
                          scope(改动 ⊆ 卡的 allowed_paths)· preflight(干净机器、无凭证)· 开 PR · Claude 初审(有密钥时)
                     ──► Seth(定时任务,每 2 小时)读 SYNC 新段落、origin/lane-*、PR 结果、in_review 的卡
                     ──► 合并 = Seth 往 .seth_bot/queue/ 放一个任务 ──► Mac 上的 seth_bot 执行:
                          范围检查 → 临时 worktree 里合并 → preflight(合并后的树)→ push → 快进主目录 → 等部署 → GET 核对
                     ──► 结果写 .seth_bot/done/<id>.json,Seth 下一轮读;卡的 verified 由 Seth 跑验收查询后写
```

**lane 要改的只有一件事:交付 = 推分支。** 不再在 SYNC 里贴补丁、不再请 Jazz 转达。

```bash
cd ~/Projects/looloomi-ai-lane-a &&
git fetch origin &&
git switch -c lane-a/T-003 origin/main
```

做完:卡的 `status` 改 `in_review`、`notes` 写测得的值 → `python3 scripts/task_board.py` → preflight → `git add <卡允许的路径> tasks/T-003.json tasks/BOARD.md` → commit → `git push -u origin lane-a/T-003`。
SYNC 里一行「T-003 已推」即可。CI 红了自己看 Actions 页修,再推同一分支。

**卡就是合同。** `scripts/check_pr_scope.py` 把「改了卡上没允许的文件」变成机械事实:改动必须在 `allowed_paths` 内
(加卡自己和 BOARD.md),不许碰 `forbidden_paths` 和全局禁区(Shadow/、.github/、githooks、seth_bot、DECISIONS.md、.env)。
卡的范围不够 → 在 SYNC `@seth` 要 Seth 改卡,不要越界改。只交报告(Mac 数据根)的卡不用推分支,照旧写最终路径。

**seth_bot 只做三件事**(`scripts/seth_bot/seth_bot.py`,测试 `tests/test_seth_bot.py`):
`commit`(显式路径,绝不 -A,永不提交清单拒收)· `merge`(只收 `lane-{a,b,c}/T-NNN`)· `fetch`。
只执行 `by=seth` 的任务;不执行任意命令;核对只做本站相对路径的 GET。**lane 不许往 `.seth_bot/` 写任何东西。**
安装 / 卸载 / 暂停只由 Jazz:`bash scripts/seth_bot/install.sh` / `--uninstall` / `touch .seth_bot/PAUSE`。

**Jazz 仍然拍的:** `DECISIONS.md` 级别的事(产品边界、钱、风险、key、策略取舍)。其余合并顺序、范围、测试常量都问 Seth。

## 私有文档不入库(S-501,2026-10-07 起)

仓库是 public。`REFUTATION_LEDGER.md`、`STRATEGY_PLAYBOOK.md`、`DECISIONS.md`、`docs/DECISIONS.md` **不再被 git 跟踪**,
和 MINIMAX_SYNC 一样:**Mac 主目录一份,是唯一一份**;lane worktree 里是软链(seth_bot 每轮补,`setup_lane_worktrees.sh` 也会建)。

- lane 照旧读、照旧往台账末尾追加 M- 条目 —— 写的是主目录那份。**先切到新 main**(`git fetch origin && git switch -c lane-x/T-NNN origin/main`):
  旧分支上那份还是被跟踪的旧副本,写进去的东西会跟着分支走、合并时冲突。
- **永远不要 `git add -f` 这四份。** CI 的范围检查、seth_bot、`tests/test_private_docs_untracked.py` 三处都会拒;但拒在推送之后就晚了。
- 不要在主目录 `git checkout` 旧提交:被忽略的文件会被旧内容覆盖、回来时被删。真发生了,从 `~/Projects/looloomi-private`(seth_bot 每 5 分钟的快照,带历史)拷回来。
- 读这四份的检查在 CI 上明说跳过(GitHub 没有这些文件),在 Mac / lane / 合并前的 preflight 上照常跑。

## 历史已改写(S-502,2026-10-07)

私有文件(台账、策略手册、两份 DECISIONS、MINIMAX_SYNC、WEEKLY_REVIEW、Shadow/)从公开历史里整个删掉了,**所有提交号从那之后都变了**。

- **旧分支一律作废。** 本机旧分支(lane-*/base、lane-b/T-011 …)和 reflog 里还有旧历史;`scripts/githooks/pre-push` 会拒绝任何「不在 origin 上、却碰过私有路径」的提交。
  要继续旧分支上的工作:`git fetch origin && git switch -c lane-x/T-NNN origin/main`,再把改动搬过去(cherry-pick 也会被拒,如果那个提交碰过私有路径)。
- 文档里引用的旧提交号(PROJECT_STATE、台账、卡片)在 GitHub 上已不存在:旧号 → 新号查 `~/Projects/looloomi-private/history-rewrite-s502/commit-map`。
- 被跟踪的文件里不许有 key:`tests/test_no_secrets_in_tracked_files.py`(只报路径与类型)。key 只经 Jazz 的手进 `.env` / Railway。

## lane 自己醒(S-503,2026-10-07 起)—— 不用 Jazz 开 terminal

`scripts/lane_bot/`:launchd 每 10 分钟检查一次(`.lane_bot/wake/` 里出现文件立即检查)。某个 lane **醒**的条件:
Seth 写了 `.lane_bot/wake/lane-x`(派卡、回复、要求返工时),或者距上一轮 ≥ 2 小时且名下有 open / claimed 的卡。
**不醒**:09:00–23:00(本机时间)之外;当天已跑满 8 轮;那个目录里已经开着一个 claude(Jazz 在用);上一轮没完。

醒了就在 lane 平时的目录里用无界面模式跑一轮(`claude -p`,经 `zsh -lic` 启动,读的是和 Jazz 开 terminal 时同一份配置,
即同一个 MiniMax 连接;key 不经过脚本)。每轮最多 60 步、40 分钟。提示词 `scripts/lane_bot/prompt.md`,目录 `scripts/lane_bot/lanes.json`。

- **lane 在自动轮次里不编辑 MINIMAX_SYNC** —— 它的最终回复由 lane_bot 加锁贴成 `§A-auto-MMDD-HHMM` 一段(三个 lane 同时整文件改写会互相覆盖)。
- 工具白名单:读写文件、`python3`、`git` 的读与分支操作、只推 `lane-` 开头的分支;没有 `rm`、没有推 main(另有 pre-push 钩子)。
- lane 改不了自己的缰绳:`scripts/lane_bot/` 在全局禁区(`check_pr_scope.py`)。
- Jazz 手动开 terminal 照旧可用;开着的那个 lane 自动轮次会让开。暂停全部:`touch .lane_bot/PAUSE`;单个:`lanes.json` 里 `enabled: false`。
- 记录:`.lane_bot/log.txt`(一行一轮)、`.lane_bot/runs/`(每轮的原始输出、步数、耗时)。

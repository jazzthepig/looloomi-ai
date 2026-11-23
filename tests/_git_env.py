"""S-903:`GIT_DIR` / `GIT_WORK_TREE` 是环境变量,测试里起的 git 子进程会继承。

2026-11-23 08:05 UTC:一条 shell 里导出了 `GIT_DIR=<主仓库>/.git GIT_WORK_TREE=<草稿目录>`,接着跑了
`tests/test_deploy_paths.py` —— 它在临时目录里 `git init / config / add -A / commit`,`cwd=tmp_path` 不起作用,
四条命令全打在真仓库上:`.git/config` 被写了 `core.worktree` 和 `user = t <t@t>`,本地 main 上多了一个 99 个文件的
提交。没推送,是另一个会话发现后暂停了提交机器人才挡住的。`test_seth_bot.py` 里早就有一行「钩子里跑时 GIT_DIR 会把
临时仓库指回真仓库」的清理 —— **那条教训只守了写下它的那一个文件。**

所以:会把 git 的靶子换掉的变量,在测试进程一开始就删掉(`conftest.py` 管 pytest 那条路;起临时仓库的测试文件自己再调
一次,管 `python3 -m tests.x` 那条路)。`GIT_OPTIONAL_LOCKS` 之类只减少写入的变量不动。
"""
from __future__ import annotations

import os

#: 会改变「git 命令打在哪个仓库 / 哪个工作区 / 哪个索引上」的变量。
REDIRECTING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
               "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")


def scrub_git_env(environ=None) -> list[str]:
    """删掉会改靶子的 GIT_* 变量(就地改,子进程不再继承)。返回删掉的名字。"""
    env = os.environ if environ is None else environ
    gone = [k for k in REDIRECTING if k in env]
    for k in gone:
        env.pop(k, None)
    return gone

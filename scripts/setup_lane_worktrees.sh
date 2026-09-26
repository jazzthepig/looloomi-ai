#!/usr/bin/env bash
# S-421:为 Minimax 三个 lane 各建一个 worktree,并启用仓库内的 git 钩子。Mac 侧运行一次即可,可重复运行。
#   bash scripts/setup_lane_worktrees.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
main_wt="$(pwd)"
git fetch origin
git worktree prune
for lane in a b c; do
  dir="$(dirname "$main_wt")/looloomi-ai-lane-$lane"
  if [ -d "$dir" ]; then
    echo "· lane-$lane 已存在:$dir"
  else
    git worktree add -B "lane-$lane/base" "$dir" origin/main
    echo "✓ lane-$lane:$dir"
  fi
  [ -e "$dir/.env" ] || ln -s "$main_wt/.env" "$dir/.env"
  # S-426:提交按 lane 署名。必须 --worktree(且开 worktreeConfig),否则写进共享配置,连 main 一起改名。
  git config extensions.worktreeConfig true
  git -C "$dir" config --worktree user.name "Minimax-$(echo $lane | tr a-z A-Z)"
done
# 绝对路径:钩子用主工作目录那份,lane 改不到自己的副本来绕过
git config core.hooksPath "$main_wt/scripts/githooks"
echo "✓ 钩子已启用:lane worktree 不能推 main"
git worktree list

#!/usr/bin/env bash
# 被强制执行的教训数量,只能升不能降 (S-223).
#
# Jazz, 2026-08-24:「这几个月的试错价值不要丢失了。」
#
# MEMORY.md 已经写着判据:**if a test already enforces it, the test is the memory**。
# 所以「价值有没有丢」不是态度问题,是一个能量出来的比例。今天量的:
#
#     台账里写下的教训 (S-* 标题)        102
#     其中有测试/preflight 关卡强制的      76      ← 真正不会丢
#     只以散文形式存在的                   26      ← 会被重新学一遍
#
# 而其中三条 —— S-214 / S-215 / S-216 —— 是我今天刚写的。**今天写下的教训,今天就
# 已经在"会丢"的那一栏里。** 缺的不是纪律:「要记得补测试」这条约定我们一直有,
# 它今天产出了三条未强制的教训。缺的是一个让"写下"和"强制"不能脱节的机制。
#
# 这就是那个机制,和 check_ledger_citations.sh 同一个形状:一个只能朝好的方向
# 移动的数字。它不要求任何人记得什么。
#
# 它检查的性质很窄,而这正是它能成立的原因:**一条教训的编号出现在某个测试或
# preflight 关卡里**。它无法判断那个测试是否守住了教训的真意 —— 那要靠 mutation
# 测试(本 session 我的守卫被 mutation 打回过六次)。但它能判断**有没有人试过**,
# 而 26 条的答案是没有。
set -uo pipefail
cd "$(dirname "$0")/.."

LEDGER="REFUTATION_LEDGER.md"
BASELINE="scripts/lesson_enforcement_baseline.txt"

[[ -f "$LEDGER" ]] || { echo "  ✗ $LEDGER 不存在"; exit 1; }

# 写下的:台账里带 S-号的标题行。一个标题可以认领多个号 (## S-186 / S-187 — ...)。
WRITTEN=$(grep -E '^#{2,3} .*S-[0-9]+' "$LEDGER" | grep -oE 'S-[0-9]+' | sort -u)

# 强制的:出现在测试或 preflight 关卡里的号。src 里的 docstring 不算 —— 一段解释
# bug 的注释不会在 bug 复发时失败,而那正是本 session 反复踩到的区别。
ENFORCED=$(grep -rohE '\bS-[0-9]+\b' \
             tests/ scripts/preflight.sh \
             src/research/validation/tests/ src/data/cis/tests/ 2>/dev/null \
           | sort -u)

BOTH=$(comm -12 <(echo "$WRITTEN") <(echo "$ENFORCED"))
N_WRITTEN=$(echo "$WRITTEN" | grep -c . || true)
N_BOTH=$(echo "$BOTH" | grep -c . || true)
PCT=$(( N_WRITTEN ? 100 * N_BOTH / N_WRITTEN : 0 ))

FLOOR=76
[[ -f "$BASELINE" ]] && FLOOR=$(grep -oE '^[0-9]+' "$BASELINE" | head -1)

if (( N_BOTH < FLOOR )); then
  echo "  ✗ 被强制执行的教训从 $FLOOR 降到 $N_BOTH —— 有守卫被删除或改名了"
  echo "    掉出来的:"
  comm -13 <(echo "$ENFORCED") <(echo "$BOTH") | sed 's/^/      /'
  echo "    这个数字只能升。若某条守卫是有意撤除的,连同理由一起改 $BASELINE。"
  exit 1
fi

if (( N_BOTH > FLOOR )); then
  # 棘轮:涨上去就锁住,否则基线会永远停在第一天。
  echo "$N_BOTH  # 被强制执行的教训下限。只能升。上次更新 $(date -u +%F)" > "$BASELINE"
  echo "  ✓ 强制执行率 $N_BOTH/$N_WRITTEN (${PCT}%) — 基线由 $FLOOR 抬到 $N_BOTH"
  exit 0
fi

echo "  ✓ 强制执行率 $N_BOTH/$N_WRITTEN (${PCT}%) — 基线 $FLOOR 未跌"

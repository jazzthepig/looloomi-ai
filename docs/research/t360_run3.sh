#!/usr/bin/env bash
# T-360 返工第三轮:只跑规则 A、持有期 H ∈ {20,30,45}、零分布 N_NULL = 50。
# 用法(在仓库根):bash docs/research/t360_run3.sh
# 口径修复见 T-360_reversal_engines.py 的 srs_on_acct(账户日重取比 + 链式自检)。
set -euo pipefail
cd "$(dirname "$0")/../.."

export T360_H_A="20,30,45"
export T360_RULE_B=0
export T360_N_NULL=50
export T360_OUT="docs/research/T-360_results_run3.json"
export T360_VERIFY_OUT="docs/research/T-360_verify_run3.json"

nohup python3 docs/research/T-360_reversal_engines.py > docs/research/t360_run3.log 2>&1 &
echo "launched pid=$! at $(date -u +%FT%TZ) -> docs/research/t360_run3.log"

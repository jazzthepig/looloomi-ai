#!/usr/bin/env bash
# CG Pro 深盘回填的落地脚本 (S-258)。**在 Mac 上跑,不在沙箱。**
#
# 为什么需要一个脚本而不是一条 curl:这个操作会往生产库写几万行,
# 而 dry_run 与正式跑之间**必须有一个人看过覆盖窗口**。一条 curl 的
# `dry_run=true` 改成 `false` 只差五个字符,而那五个字符没有任何东西拦。
#
# 用法:
#     bash scripts/land_cg_pro_backfill.sh            # 只 dry-run,永远安全
#     bash scripts/land_cg_pro_backfill.sh --write    # dry-run → 人工确认 → 正式写
set -uo pipefail

BASE="${LOOLOOMI_BASE:-https://looloomi.ai}"
DAYS="${DAYS:-1825}"
WRITE=0
[[ "${1:-}" == "--write" ]] && WRITE=1

if [[ -z "${INTERNAL_TOKEN:-}" ]]; then
  echo "✗ INTERNAL_TOKEN 未设置。"
  echo "  这个仓库【没有任何代码加载 .env】(S-246)—— Railway 上是真的环境变量,"
  echo "  本地裸跑读到的是空。先:  set -a; source .env; set +a"
  exit 2
fi

echo "── ① dry-run(不写库)─────────────────────────────────────────────"
echo "   base=$BASE  days=$DAYS"
DRY=$(curl -s -X POST "$BASE/internal/backfill-cg-pro?dry_run=true&days=$DAYS" \
        -H "X-Internal-Token: $INTERNAL_TOKEN")

if [[ -z "$DRY" ]]; then
  echo "✗ 端点没有返回任何内容 —— 读不到 ≠ 都健康 (S-180)。检查 base/token/部署。"
  exit 1
fi

echo "$DRY" | jq -r '
  "状态: \(.status)  ·  可写标的: \(.symbols_written)  ·  跳过: \(.symbols_skipped)",
  "",
  "逐标的:",
  (.detail[] | "  \(.symbol|.[0:5])  \(.candles // 0 | tostring | .[0:5]) 根  \(.coverage // "—")  \(.skipped_because // "")")
' 2>/dev/null || { echo "✗ 返回不是预期的 JSON:"; echo "$DRY" | head -5; exit 1; }

OK=$(echo "$DRY" | jq -r '.symbols_written // 0')
SKIP=$(echo "$DRY" | jq -r '.symbols_skipped // 0')

echo
echo "── ② 判据 ────────────────────────────────────────────────────────"
echo "   期望:每个标的的 coverage 接近 $DAYS 天(M-92 实测 CG Pro 有 1811 天),"
echo "         且 skipped 里【没有】'映射未通过校验' —— 那意味着 coin_id 指错了币。"
echo
if [[ "$OK" -eq 0 ]]; then
  echo "✗ 0 个标的可写。不要继续。逐条看上面的 skipped_because。"
  exit 1
fi
if echo "$DRY" | jq -e '.detail[] | select(.skipped_because // "" | test("映射未通过校验"))' >/dev/null 2>&1; then
  echo "🔴 有标的的 coin_id 映射【未通过实证校验】——"
  echo "   一个错的映射会把另一个币的整段历史写进这个标的,而曲线看起来完全正常。"
  echo "   先修 src/api/routers/ohlcv.py 里的 pairs 表,再跑。"
  exit 1
fi
echo "   ✓ $OK 个标的可写,$SKIP 个跳过,无映射错误"

if [[ "$WRITE" -eq 0 ]]; then
  echo
  echo "── 只做了 dry-run。确认上面的覆盖窗口无误后:"
  echo "     bash scripts/land_cg_pro_backfill.sh --write"
  exit 0
fi

echo
echo "── ③ 正式写入 ────────────────────────────────────────────────────"
read -r -p "   要往生产库写 ~$OK 个标的 × 最多 $DAYS 天。输入 WRITE 确认: " CONFIRM
[[ "$CONFIRM" == "WRITE" ]] || { echo "   已取消。"; exit 0; }

curl -s -X POST "$BASE/internal/backfill-cg-pro?dry_run=false&days=$DAYS" \
     -H "X-Internal-Token: $INTERNAL_TOKEN" \
  | jq -r '"写入 \(.rows_written) 行 · \(.symbols_written) 个标的 · 状态 \(.status)"'

echo
echo "── ④ 复验(在 Supabase 上跑)──────────────────────────────────────"
cat <<'SQL'
-- 新源落了多少,覆盖到哪
select source, count(*) n, count(distinct symbol) syms,
       min(trade_date)::text lo, max(trade_date)::text hi
from ohlcv_daily where source in ('coingecko_pro_ohlc','coingecko','binance_hist')
group by 1 order by 2 desc;

-- 旧的 48,853 行必须【原封不动】—— on_conflict 少写 source 会覆盖它们
select count(*) as coingecko_rows_must_still_be_48853
from ohlcv_daily where source='coingecko';

-- 判活层是否认它
select * from ohlcv_source_coverage();
SQL

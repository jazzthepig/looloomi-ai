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
DEST="${DEST:-local}"          # local=本地研究面(默认) · supabase=系统记录
WRITE=0
[[ "${1:-}" == "--write" ]] && WRITE=1

if [[ -z "${INTERNAL_TOKEN:-}" ]]; then
  echo "✗ INTERNAL_TOKEN 未设置。"
  echo "  这个仓库【没有任何代码加载 .env】(S-246)—— Railway 上是真的环境变量,"
  echo "  本地裸跑读到的是空。先:  set -a; source .env; set +a"
  exit 2
fi

echo "── ① dry-run(不写库)─────────────────────────────────────────────"
echo "   base=$BASE  days=$DAYS  dest=$DEST"
# ⚠️ 必须看 HTTP 状态码,不能只看 body 是否为空。
# 实测 2026-08-30:端点未部署时返回 404 + 一个 JSON body,而只检查空 body 的
# 版本会当它是正常响应继续往下走,然后 jq 解析失败 —— 排查时看到的是 jq 报错,
# 而真正的原因是「这个端点还没推上去」。**状态码是那条信息,body 不是。**
HTTP=$(curl -s -o /tmp/cgpro_dry.json -w '%{http_code}' \
        -X POST "$BASE/internal/backfill-cg-pro?dry_run=true&dest=$DEST&days=$DAYS" \
        -H "X-Internal-Token: $INTERNAL_TOKEN")
DRY=$(cat /tmp/cgpro_dry.json 2>/dev/null)

case "$HTTP" in
  200) : ;;
  404) echo "✗ HTTP 404 —— 端点不存在。**代码还没推上去。**"
       echo "   先在 Mac 上 commit + push,等 Railway 部署完(~90s)再跑。"
       exit 1 ;;
  401) echo "✗ HTTP 401 —— token 不对。检查 INTERNAL_TOKEN 与 Railway 上的是否一致。"
       exit 1 ;;
  000) echo "✗ 连不上 $BASE —— 网络或域名问题。"; exit 1 ;;
  *)   echo "✗ HTTP $HTTP:"; echo "$DRY" | head -3; exit 1 ;;
esac

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
if [[ "$DEST" == "supabase" ]]; then
  echo "   🔴 dest=supabase —— 这会写【生产库】。Supabase 是免费版(实测 50.7% 已用)。"
  echo "      研究用途请改回 DEST=local。"
fi
read -r -p "   要往 $DEST 写 ~$OK 个标的 × 最多 $DAYS 天。输入 WRITE 确认: " CONFIRM
[[ "$CONFIRM" == "WRITE" ]] || { echo "   已取消。"; exit 0; }

curl -s -X POST "$BASE/internal/backfill-cg-pro?dry_run=false&dest=$DEST&days=$DAYS" \
     -H "X-Internal-Token: $INTERNAL_TOKEN" \
  | jq -r '"写入 \(.rows_written) 行 · \(.symbols_written) 个标的 · dest=\(.dest) · 状态 \(.status)"'

echo
echo "── ④ 复验 ────────────────────────────────────────────────────────"
if [[ "$DEST" == "local" ]]; then
cat <<'LOCALSQL'
# 本地研究面(sqlite):
sqlite3 /tmp/cometcloud_data/ohlcv.db "
  select source, count(*) n, count(distinct symbol) syms,
         min(trade_date), max(trade_date)
  from ohlcv_daily group by 1 order by 2 desc;"

# 成交量必须全 NULL(/ohlc/range 不给量,拼别处的量就是跨源 S-230):
sqlite3 /tmp/cometcloud_data/ohlcv.db "
  select count(*) as should_be_zero from ohlcv_daily
  where source='coingecko_pro_ohlc' and volume is not null;"
LOCALSQL
else
cat <<'SQL'
-- 生产库(Supabase):新源落了多少,覆盖到哪
select source, count(*) n, count(distinct symbol) syms,
       min(trade_date)::text lo, max(trade_date)::text hi
from ohlcv_daily where source in ('coingecko_pro_ohlc','coingecko','binance_hist')
group by 1 order by 2 desc;

-- 旧的 48,853 行必须【原封不动】—— on_conflict 少写 source 会覆盖它们
select count(*) as coingecko_rows_must_still_be_48853
from ohlcv_daily where source='coingecko';

-- 库容:免费版 500MB,写之前 253MB(50.7%)
select pg_size_pretty(pg_database_size(current_database())) as db_total;

-- 判活层是否认它
select * from ohlcv_source_coverage();
SQL
fi

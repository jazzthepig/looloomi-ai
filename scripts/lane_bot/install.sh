#!/usr/bin/env bash
# 安装 / 卸载 lane_bot(S-503)。只由 Jazz 在 Mac 终端里跑。
#   bash scripts/lane_bot/install.sh              安装(或更新)并启动:每 10 分钟检查一次,.lane_bot/wake/ 出现文件立即检查
#   bash scripts/lane_bot/install.sh --uninstall  停止并移除
# 先试一个 lane:python3 scripts/lane_bot/lane_bot.py --dry-run,再 python3 scripts/lane_bot/lane_bot.py --once lane-b
# 暂停全部:touch .lane_bot/PAUSE;单个 lane:scripts/lane_bot/lanes.json 里 enabled=false。
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$(pwd)"
LABEL="com.cometcloud.lanebot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ lane_bot 已停止并移除"
  exit 0
fi
PY="$(command -v python3)"
command -v claude >/dev/null || { echo "✗ 找不到 claude —— 在你平时打开 lane 的 terminal 里跑这个安装脚本"; exit 1; }
mkdir -p "$REPO/.lane_bot/wake" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$REPO/scripts/lane_bot/lane_bot.py</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>WatchPaths</key><array><string>$REPO/.lane_bot/wake</string></array>
  <key>StartInterval</key><integer>600</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$PATH</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>StandardOutPath</key><string>$REPO/.lane_bot/launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/.lane_bot/launchd.log</string>
</dict>
</plist>
PL
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "✓ lane_bot 已启动:python=$PY claude=$(command -v claude)"
echo "  配置 scripts/lane_bot/lanes.json · 日志 .lane_bot/log.txt · 每轮记录 .lane_bot/runs/ · 暂停 touch .lane_bot/PAUSE"

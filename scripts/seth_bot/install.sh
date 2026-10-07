#!/usr/bin/env bash
# 安装 / 卸载 Seth 的 Mac 侧执行器(S-500)。只由 Jazz 在 Mac 终端里跑。
#   bash scripts/seth_bot/install.sh              安装(或更新)并启动
#   bash scripts/seth_bot/install.sh --uninstall  停止并移除
# 暂停而不卸载:touch .seth_bot/PAUSE(删掉这个文件即恢复)。
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$(pwd)"
LABEL="com.cometcloud.sethbot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ seth_bot 已停止并移除(队列与结果留在 .seth_bot/)"
  exit 0
fi
PY="$(command -v python3)"
mkdir -p "$REPO/.seth_bot/queue" "$REPO/.seth_bot/done" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$REPO/scripts/seth_bot/seth_bot.py</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>WatchPaths</key><array><string>$REPO/.seth_bot/queue</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$PATH</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>StandardOutPath</key><string>$REPO/.seth_bot/launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/.seth_bot/launchd.log</string>
</dict>
</plist>
EOF
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "✓ seth_bot 已启动:python=$PY repo=$REPO"
echo "  队列 .seth_bot/queue/ · 结果 .seth_bot/done/ · 日志 .seth_bot/log.txt · 暂停 touch .seth_bot/PAUSE"

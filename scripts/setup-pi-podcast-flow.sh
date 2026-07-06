#!/bin/bash
# 注册基于 pi CLI 的播客流（podcast）。
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SPOOL="$HOME/.info-collector"
FLOW_TARGET="$HOME/.pi/scripts/podcast-bookmarks.py"
SKILL_TARGET="$HOME/.claude/skills/podcast-digest"
PLIST_LABEL="com.pi.podcast-bookmarks"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

mkdir -p "$SPOOL/outbox" "$SPOOL/inbox/processed" "$SPOOL/state" "$HOME/.pi/logs"

echo "== 1/4 安装 pi 播客流脚本"
chmod +x "$REPO/flows/podcast-bookmarks.py"
if [[ -f "$FLOW_TARGET" ]]; then
  cp "$FLOW_TARGET" "$FLOW_TARGET.bak-$(date +%Y%m%d%H%M%S)"
fi
mkdir -p "$(dirname "$FLOW_TARGET")"
cp "$REPO/flows/podcast-bookmarks.py" "$FLOW_TARGET"
chmod +x "$FLOW_TARGET"

echo "== 2/4 安装 podcast-digest skill"
rm -rf "$SKILL_TARGET"
mkdir -p "$(dirname "$SKILL_TARGET")"
cp -R "$REPO/skills/podcast-digest" "$SKILL_TARGET"

echo "== 3/4 注册 flows.json"
SPOOL="$SPOOL" FLOW_TARGET="$FLOW_TARGET" PLIST_LABEL="$PLIST_LABEL" python3 <<'PY'
import json, os

spool = os.environ["SPOOL"]
path = os.path.join(spool, "flows.json")
flows = {}
if os.path.exists(path):
    try:
        flows = json.load(open(path))
    except Exception:
        flows = {}
home = os.path.expanduser("~")
flows["podcast"] = {
    "command": ["/usr/bin/python3", os.environ["FLOW_TARGET"], "--manual"],
    "lockFile": f"{home}/.pi/logs/podcast-bookmarks.lock",
    "intervalSeconds": 3600,
    "label": os.environ["PLIST_LABEL"],
}
with open(path, "w") as f:
    json.dump(flows, f, ensure_ascii=False, indent=1)
print("   podcast → pi 流已注册")
PY

echo "== 4/4 安装 launchd 定时任务"
mkdir -p "$(dirname "$PLIST_DST")"
LAUNCHD_PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin"
for exe in pi npx uvx; do
  if command -v "$exe" >/dev/null 2>&1; then
    dir="$(dirname "$(command -v "$exe")")"
    case ":$LAUNCHD_PATH:" in
      *":$dir:"*) ;;
      *) LAUNCHD_PATH="$dir:$LAUNCHD_PATH" ;;
    esac
  fi
done
HOME="$HOME" LAUNCHD_PATH="$LAUNCHD_PATH" \
  python3 - "$REPO/templates/$PLIST_LABEL.plist" "$PLIST_DST" <<'PY'
import os, pathlib, sys

src, dst = map(pathlib.Path, sys.argv[1:])
text = src.read_text(encoding="utf-8")
text = text.replace("__HOME__", os.environ["HOME"])
text = text.replace("__PATH__", os.environ["LAUNCHD_PATH"])
dst.write_text(text, encoding="utf-8")
PY
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

cat <<EOF
完成。

还需要在 Dashboard 设置区手动添加 Processing Type：
  id: podcast
  名称: 播客
  自动排队: 不勾选
EOF

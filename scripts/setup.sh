#!/bin/bash
# Info Collector 一键安装（可重复运行，不覆盖已有配置）。
# 交互提问可用环境变量跳过（供 AI/脚本非交互运行）：
#   INFO_COLLECTOR_API_KEY=sk-...       DeepSeek 或 Anthropic API Key
#   INFO_COLLECTOR_MODEL=deepseek-v4-flash
#   INFO_COLLECTOR_OUTPUT_DIR=~/Documents/InfoCollector   译文输出目录
#   INFO_COLLECTOR_ENGINE=deepseek|claude|skip   翻译引擎选择
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SPOOL="$HOME/.info-collector"
EXT_ID="fmdbamjmoabmcggjfgeopaijnbjkjbhm"
NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
FLOW_BIN="$SPOOL/bin/translate-flow.py"
PLIST_LABEL="com.info-collector.translate"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

echo "== 1/5 创建 spool 目录 $SPOOL"
mkdir -p "$SPOOL/outbox" "$SPOOL/inbox/processed" "$SPOOL/state" "$SPOOL/bin"

echo "== 2/5 安装 Chrome native host"
chmod +x "$REPO/host/info_collector_host.py"
mkdir -p "$NM_DIR"
cat > "$NM_DIR/com.pi.info_collector.json" <<EOF
{
  "name": "com.pi.info_collector",
  "description": "Info Collector file bridge",
  "path": "$REPO/host/info_collector_host.py",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXT_ID/"]
}
EOF

echo "== 3/5 配置翻译引擎"
HAS_TRANSLATE=$(python3 -c "
import json, os
p = os.path.expanduser('$SPOOL/flows.json')
flows = {}
if os.path.exists(p):
    try:
        flows = json.load(open(p))
    except Exception:
        pass
print('yes' if 'translate' in flows else 'no')
")

ENGINE="${INFO_COLLECTOR_ENGINE:-}"
if [[ "$HAS_TRANSLATE" == "yes" && -z "$ENGINE" ]]; then
  echo "   已有 translate 流程注册，保留现有配置（想换成内置 Claude 翻译流，"
  echo "   请用 INFO_COLLECTOR_ENGINE=claude 重跑本脚本；想换 DeepSeek 则用"
  echo "   INFO_COLLECTOR_ENGINE=deepseek）"
  ENGINE="skip"
fi
if [[ -z "$ENGINE" ]]; then
  echo "   选择翻译引擎："
  echo "     1) 内置 DeepSeek 翻译流（推荐，只需一个 DeepSeek API Key）"
  echo "     2) 内置 Claude 翻译流（需要 Anthropic API Key）"
  echo "     3) 稍后自己配置"
  read -r -p "   输入 1、2 或 3（默认 1）: " choice
  case "${choice:-1}" in
    2) ENGINE="claude" ;;
    3) ENGINE="skip" ;;
    *) ENGINE="deepseek" ;;
  esac
fi

if [[ "$ENGINE" == "deepseek" || "$ENGINE" == "claude" ]]; then
  if [[ "$ENGINE" == "deepseek" ]]; then
    if command -v defuddle >/dev/null 2>&1; then
      echo "   已检测到 defuddle，DeepSeek 翻译流会优先用它提取网页正文"
    else
      echo "   未检测到 defuddle；DeepSeek 翻译流仍可运行，但会退回内置简易抓取器"
      echo "   想和 Pi 的 translate-article 流保持一致，可先运行：npm install -g defuddle"
    fi
  fi
  API_KEY="${INFO_COLLECTOR_API_KEY:-}"
  if [[ -z "$API_KEY" ]]; then
    if [[ "$ENGINE" == "deepseek" ]]; then
      echo "   需要 DeepSeek API Key（在 https://platform.deepseek.com/api_keys 创建，"
      echo "   通常以 sk- 开头；现在跳过的话，之后编辑 $SPOOL/config.json 也行）"
    else
      echo "   需要 Anthropic API Key（在 https://console.anthropic.com/settings/keys 创建，"
      echo "   以 sk-ant- 开头；现在跳过的话，之后编辑 $SPOOL/config.json 也行）"
    fi
    read -r -p "   粘贴 API Key（直接回车跳过）: " API_KEY
  fi
  OUT_DIR="${INFO_COLLECTOR_OUTPUT_DIR:-}"
  if [[ -z "$OUT_DIR" ]]; then
    read -r -p "   译文保存到哪个文件夹？（默认 ~/Documents/InfoCollector）: " OUT_DIR
  fi
  OUT_DIR="${OUT_DIR:-~/Documents/InfoCollector}"
  MODEL="${INFO_COLLECTOR_MODEL:-}"
  BASE_URL="${INFO_COLLECTOR_BASE_URL:-}"

  API_KEY="$API_KEY" OUT_DIR="$OUT_DIR" SPOOL="$SPOOL" FLOW_BIN="$FLOW_BIN" \
    PLIST_LABEL="$PLIST_LABEL" ENGINE="$ENGINE" MODEL="$MODEL" BASE_URL="$BASE_URL" python3 <<'PY'
import json, os

spool = os.environ["SPOOL"]
provider = os.environ["ENGINE"]
defaults = {
    "deepseek": {
        "model": "deepseek-v4-flash",
        "baseUrl": "https://api.deepseek.com",
    },
    "claude": {
        "provider": "anthropic",
        "model": "claude-opus-4-8",
        "baseUrl": "https://api.anthropic.com",
    },
}
provider_name = defaults.get(provider, {}).get("provider", provider)
default_model = defaults[provider]["model"]
default_base_url = defaults[provider]["baseUrl"]

# config.json：只补缺，不覆盖已填的 apiKey
cfg_path = os.path.join(spool, "config.json")
cfg = {}
if os.path.exists(cfg_path):
    try:
        cfg = json.load(open(cfg_path))
    except Exception:
        cfg = {}
key = os.environ.get("API_KEY", "").strip()
if key:
    cfg["apiKey"] = key
cfg.setdefault("apiKey", "")
old_provider = cfg.get("provider")
cfg["provider"] = provider_name
model = os.environ.get("MODEL", "").strip()
if model:
    cfg["model"] = model
elif not cfg.get("model") or old_provider != provider_name:
    cfg["model"] = default_model
base_url = os.environ.get("BASE_URL", "").strip()
if base_url:
    cfg["baseUrl"] = base_url.rstrip("/")
elif not cfg.get("baseUrl") or old_provider != provider_name:
    cfg["baseUrl"] = default_base_url
cfg["outputDir"] = os.environ["OUT_DIR"]
with open(cfg_path, "w") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=1)
os.chmod(cfg_path, 0o600)
print(f"   配置已写入 {cfg_path}")

# flows.json：注册内置翻译流
flows_path = os.path.join(spool, "flows.json")
flows = {}
if os.path.exists(flows_path):
    try:
        flows = json.load(open(flows_path))
    except Exception:
        flows = {}
flows["translate"] = {
    "command": ["/usr/bin/python3", os.environ["FLOW_BIN"], "--manual"],
    "lockFile": os.path.join(spool, "state", "translate.lock"),
    "intervalSeconds": 3600,
    "label": os.environ["PLIST_LABEL"],
}
with open(flows_path, "w") as f:
    json.dump(flows, f, ensure_ascii=False, indent=1)
print(f"   已注册内置 {provider_name} 翻译流")
PY

  cp "$REPO/flows/translate-claude-api.py" "$FLOW_BIN"
  chmod +x "$FLOW_BIN"

  echo "== 4/5 安装定时任务（每小时自动翻译）"
  mkdir -p "$(dirname "$PLIST_DST")"
  sed "s|__HOME__|$HOME|g" "$REPO/templates/$PLIST_LABEL.plist" > "$PLIST_DST"
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  echo "   已加载 ${PLIST_LABEL}（每小时运行，也可在 Dashboard 点「立即处理」）"
else
  echo "== 4/5 跳过定时任务（未选择内置翻译流）"
fi

echo "== 5/5 完成"
cat <<EOF

剩余步骤（只需做一次）：
  1. Chrome 打开 chrome://extensions → 打开右上角「开发者模式」
     → 「加载已解压的扩展程序」→ 选择文件夹：
        $REPO/extension
  2. 点浏览器工具栏的 Info Collector 图标 → 「打开 Dashboard」
     → 点「立即导入书签」再点「立即桥接同步」。

自检命令（验证 API Key 和目录配置）：
  /usr/bin/python3 $FLOW_BIN --check

详细图文步骤见 SETUP.md。
EOF

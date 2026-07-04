#!/usr/bin/env python3
"""
通用翻译流（translate）：只需要一个 Anthropic API Key，无任何第三方依赖。
1. 读 ~/.info-collector/outbox/translate.json（Info Collector 扩展导出）
2. 逐篇调 Claude API：用服务端 web_fetch 工具抓取原文并翻译成中文 Markdown
3. 译文存到配置的输出目录，结果写成 Completion Report 放进 inbox/

配置文件 ~/.info-collector/config.json：
  { "apiKey": "sk-ant-...", "model": "claude-opus-4-8",
    "outputDir": "~/Documents/InfoCollector" }

用法：
  translate-flow.py            定时运行（launchd）
  translate-flow.py --manual   手动触发（Dashboard「立即处理」）
  translate-flow.py --check    自检：配置、目录、API Key 有效性，不翻译
"""

import fcntl
import json
import os
import random
import re
import string
import sys
import tempfile
import time
import urllib.error
import urllib.request

SPOOL = os.path.expanduser("~/.info-collector")
CONFIG_FILE = os.path.join(SPOOL, "config.json")
OUTBOX_FILE = os.path.join(SPOOL, "outbox", "translate.json")
INBOX_DIR = os.path.join(SPOOL, "inbox")
STATE_FILE = os.path.join(SPOOL, "state", "translate-reported.json")
STATUS_FILE = os.path.join(SPOOL, "state", "translate-status.json")
LOCK_FILE = os.path.join(SPOOL, "state", "translate.lock")
LOG_FILE = os.path.join(SPOOL, "state", "translate-flow.log")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000          # 非流式安全上限；超长文章会报 failed
REQUEST_TIMEOUT = 900       # 单篇翻译最长等待（秒）
MAX_CONTINUATIONS = 4       # 服务端工具 pause_turn 续跑次数上限

TRIGGER = "manual" if "--manual" in sys.argv else "scheduled"

SYSTEM_PROMPT = (
    "你是一名专业译者。用 web_fetch 工具抓取给定 URL 的文章，"
    "把正文完整翻译成自然通顺的简体中文 Markdown。规则："
    "代码块、命令、路径原样保留不翻译；图片保留原远程链接；"
    "文章主标题用「中文（English）」双语形式。"
    "你的最终回复必须只包含完成的 Markdown 文档本身"
    "（以 --- 开头的 YAML frontmatter 开始），"
    "不要有任何解释、前言或代码围栏。"
)


def log(msg):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}", flush=True)


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default
    return default


def load_config():
    cfg = load_json(CONFIG_FILE, {})
    cfg.setdefault("model", DEFAULT_MODEL)
    cfg.setdefault("outputDir", "~/Documents/InfoCollector")
    return cfg


def config_ok(cfg):
    key = cfg.get("apiKey") or ""
    return key.startswith("sk-ant-") and len(key) > 20


# ===== Claude API（标准库 raw HTTP）=====

def api_request(path, payload, api_key):
    req = urllib.request.Request(
        f"https://api.anthropic.com{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"API {e.code}: {body}") from e


def check_api_key(cfg):
    """用免费的 count_tokens 端点验证 API Key。"""
    api_request("/v1/messages/count_tokens", {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "ping"}],
    }, cfg["apiKey"])


def translate_article(url, title, cfg):
    """翻译一篇文章，返回 Markdown 文本。失败抛 RuntimeError。"""
    now_local = time.strftime("%Y-%m-%dT%H:%M")
    user_prompt = (
        f"翻译这篇文章：{url}\n\n"
        f"frontmatter 需包含：title（中文标题）、source（原文 URL）、"
        f"published（原文发布日期，YYYY-MM-DD，找不到就留空）、"
        f"date: {now_local}（收录时间，原样使用这个值）、"
        f"authors（作者，找不到就留空）。"
    )
    messages = [{"role": "user", "content": user_prompt}]
    payload = {
        "model": cfg["model"],
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "tools": [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 4}],
        "messages": messages,
    }

    for _ in range(MAX_CONTINUATIONS):
        resp = api_request("/v1/messages", payload, cfg["apiKey"])
        stop = resp.get("stop_reason")
        if stop == "pause_turn":
            # 服务端工具循环没跑完，把 assistant 回合附回去继续
            messages.append({"role": "assistant", "content": resp["content"]})
            payload["messages"] = messages
            continue
        if stop == "refusal":
            raise RuntimeError("模型拒绝了该请求（safety refusal）")
        if stop == "max_tokens":
            raise RuntimeError("译文超出输出上限，文章可能过长")
        text = "\n".join(
            b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"
        ).strip()
        if not text:
            raise RuntimeError(f"响应中没有文本内容（stop_reason={stop}）")
        return strip_code_fence(text)
    raise RuntimeError("服务端工具续跑次数超限（pause_turn loop）")


def strip_code_fence(text):
    m = re.match(r"^```(?:markdown|md)?\n(.*)\n```$", text, re.DOTALL)
    return m.group(1) if m else text


# ===== 落盘 =====

def extract_title(markdown, fallback):
    m = re.search(r"^title:\s*(.+)$", markdown, re.MULTILINE)
    title = m.group(1).strip().strip('"\'') if m else fallback
    return title or fallback


def safe_filename(title):
    name = re.sub(r'[/\\:*?"<>|\n]', "·", title).strip()[:80]
    return name or "untitled"


def save_markdown(markdown, title, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    base = safe_filename(title)
    path = os.path.join(out_dir, f"{base}.md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{base}-{n}.md")
        n += 1
    fd, tmp = tempfile.mkstemp(dir=out_dir)
    with os.fdopen(fd, "w") as f:
        f.write(markdown)
    os.replace(tmp, path)
    return path


# ===== spool 契约（与扩展的约定，见仓库 docs/design.md）=====

def write_report(results):
    rid = "translate-%s-%s" % (
        time.strftime("%Y%m%dT%H%M%S"),
        "".join(random.choices(string.ascii_lowercase + string.digits, k=4)),
    )
    atomic_write_json(os.path.join(INBOX_DIR, rid + ".json"), {
        "reportId": rid,
        "processingType": "translate",
        "results": results,
    })
    return rid


def update_status(patch):
    status = load_json(STATUS_FILE, {})
    status.update(patch)
    atomic_write_json(STATUS_FILE, status)


def acquire_lock():
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


# ===== 自检 =====

def run_check():
    print("== Info Collector 翻译流自检 ==")
    ok = True
    cfg = load_config()
    if not os.path.exists(CONFIG_FILE):
        print(f"✕ 配置文件不存在：{CONFIG_FILE}（运行 scripts/setup.sh）")
        ok = False
    elif not config_ok(cfg):
        print(f"✕ API Key 未配置或格式不对（应以 sk-ant- 开头）：{CONFIG_FILE}")
        ok = False
    else:
        try:
            check_api_key(cfg)
            print(f"✓ API Key 有效（模型 {cfg['model']}）")
        except Exception as e:
            print(f"✕ API Key 验证失败：{e}")
            ok = False
    out_dir = os.path.expanduser(cfg["outputDir"])
    try:
        os.makedirs(out_dir, exist_ok=True)
        print(f"✓ 输出目录可写：{out_dir}")
    except OSError as e:
        print(f"✕ 输出目录不可写：{e}")
        ok = False
    if os.path.exists(OUTBOX_FILE):
        n = len(load_json(OUTBOX_FILE, {}).get("articles") or [])
        print(f"✓ outbox 存在，当前待处理 {n} 篇")
    else:
        print("△ outbox 还不存在——扩展装好并完成首次「桥接同步」后会自动生成")
    print("== 自检" + ("通过" if ok else "未通过") + " ==")
    return 0 if ok else 1


# ===== 主流程 =====

def main():
    if "--check" in sys.argv:
        sys.exit(run_check())

    log("=" * 50)
    log(f"开始巡检翻译队列（{TRIGGER}）")

    cfg = load_config()
    if not config_ok(cfg):
        log("❌ API Key 未配置，跳过（编辑 ~/.info-collector/config.json 或重跑 setup.sh）")
        return

    lock_fd = acquire_lock()
    if lock_fd is None:
        log("另有进程在运行，跳过")
        return

    last_run = {"startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "trigger": TRIGGER, "outcome": "running"}
    patch = {"lastRun": last_run}
    if TRIGGER == "scheduled":
        patch["lastScheduledStartAt"] = last_run["startedAt"]
    update_status(patch)

    def finish(outcome, **extra):
        last_run.update({"outcome": outcome, "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **extra})
        update_status({"lastRun": last_run})

    try:
        if not os.path.exists(OUTBOX_FILE):
            log("outbox 不存在——扩展尚未完成首次桥接，跳过")
            finish("no-outbox")
            return
        articles = load_json(OUTBOX_FILE, {}).get("articles") or []
        state = load_json(STATE_FILE, {})
        pending = [
            a for a in articles
            if a.get("articleKey") not in state and a.get("url") not in state
        ]
        log(f"outbox 共 {len(articles)} 条，其中 {len(pending)} 条未报告")
        if not pending:
            log("✅ 无需翻译")
            finish("empty")
            return

        # 认领报告：扩展显示「处理中」；本进程崩溃则自动回退 pending
        urls = [a["url"] for a in pending]
        claim_rid = write_report([{"url": u, "status": "processing"} for u in urls])
        log(f"📌 已认领 {len(urls)} 篇（{claim_rid}）")

        out_dir = os.path.expanduser(cfg["outputDir"])
        results = []
        done = 0
        for a in pending:
            url, title = a["url"], a.get("title", "?")
            log(f"🌐 翻译中: {title}")
            now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                md = translate_article(url, title, cfg)
                path = save_markdown(md, extract_title(md, title), out_dir)
                results.append({"url": url, "status": "done", "processedAt": now_utc,
                                "meta": {"savedTo": path}})
                state[a.get("articleKey") or url] = now_utc
                done += 1
                log(f"  ✅ 已保存: {path}")
            except Exception as e:
                err = str(e)[:300]
                results.append({"url": url, "status": "failed", "processedAt": now_utc,
                                "meta": {"error": err}})
                log(f"  ❌ 失败: {err}")

        rid = write_report(results)
        atomic_write_json(STATE_FILE, state)
        log(f"完成 {done}/{len(pending)} 篇，报告已写入 inbox: {rid}")
        finish("success" if done == len(pending) else "failed",
               count=done, reportId=rid)

    except Exception as e:
        finish("error", error=str(e)[:300])
        raise
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    main()

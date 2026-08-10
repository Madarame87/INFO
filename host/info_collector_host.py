#!/usr/bin/env python3
"""
Info Collector 的 Native Messaging host：文件搬运工 + 流程触发器（ADR 0002、0004）。
- sync：把各处理类型的待处理清单原子写入 ~/.info-collector/outbox/<type>.json，
  把已 ack 的报告移入 inbox/processed/，返回 inbox 里剩余的 Completion Report
  以及各流程的运行状态（来自 flows.json 与 state/<type>-status.json）。
- trigger：按 flows.json 注册表启动对应流程（detached）。命令只来自用户自有的
  flows.json，扩展只能点名 processingType，不能传命令。
- 不含状态语义；队列状态全部留在扩展内。
协议：Chrome Native Messaging 标准（4 字节小端长度前缀 + UTF-8 JSON）。
"""

import json
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

try:
    from info_collector_platform import lock_is_held, user_home
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from info_collector_platform import lock_is_held, user_home


HOME = user_home()
SPOOL = str(HOME / ".info-collector")
OUTBOX = os.path.join(SPOOL, "outbox")
INBOX = os.path.join(SPOOL, "inbox")
PROCESSED = os.path.join(INBOX, "processed")
STATE = os.path.join(SPOOL, "state")
CAPTURES = os.path.join(SPOOL, "captures")
FLOWS_FILE = os.path.join(SPOOL, "flows.json")
_TRIGGERED_PROCESSES = []
MAX_NATIVE_MESSAGE_BYTES = 2_000_000
MAX_SYNC_TYPES = 32
MAX_OUTBOX_ARTICLES = 2000
OPENABLE_OUTPUTS = {
    "weekly-report": ("weekly-report-status.json", "latestReport"),
    "reading-site": ("reading-site-status.json", "siteIndex"),
}


def trigger_env():
    env = dict(os.environ)
    path_parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    candidates = []
    if os.name == "nt":
        if env.get("APPDATA"):
            candidates.append(os.path.join(env["APPDATA"], "npm"))
        if env.get("ProgramFiles"):
            candidates.append(os.path.join(env["ProgramFiles"], "nodejs"))
        candidates.append(str(HOME / ".local" / "bin"))
    else:
        nvm_root = HOME / ".nvm" / "versions" / "node"
        if nvm_root.is_dir():
            for name in sorted(os.listdir(nvm_root), reverse=True):
                candidates.append(str(nvm_root / name / "bin"))
        candidates.extend([
            str(HOME / ".local" / "bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
        ])
    for path in reversed(candidates):
        if os.path.isdir(path) and path not in path_parts:
            path_parts.insert(0, path)
    env["PATH"] = os.pathsep.join(path_parts)
    env["HOME"] = str(HOME)
    # Chrome launches the native host without a console. On Windows, a Python
    # child can otherwise inherit a legacy code page (for example cp1252) and
    # crash as soon as a Chinese log line is written to redirected stdout.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def configure_native_stdio():
    """Chrome Native Messaging requires unmodified binary stdin/stdout on Windows."""
    if os.name != "nt":
        return
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    (length,) = struct.unpack("<I", raw)
    if length > MAX_NATIVE_MESSAGE_BYTES:
        raise ValueError("native message exceeds 2 MB limit")
    data = sys.stdin.buffer.read(length)
    if len(data) < length:
        return None
    return json.loads(data.decode("utf-8"))


def send_message(obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def atomic_write_json(path, obj):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe_name(name):
    """报告 id / 类型名只能是简单文件名，防路径穿越。"""
    return bool(name) and not name.startswith(".") and all(
        c.isalnum() or c in "._-" for c in name
    )


def load_flows():
    if not os.path.exists(FLOWS_FILE):
        return {}
    try:
        with open(FLOWS_FILE, encoding="utf-8") as f:
            flows = json.load(f)
        return flows if isinstance(flows, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def flow_statuses():
    out = {}
    for ptype, cfg in load_flows().items():
        if not safe_name(ptype) or not isinstance(cfg, dict):
            continue
        status = {}
        status_path = os.path.join(STATE, f"{ptype}-status.json")
        if os.path.exists(status_path):
            try:
                with open(status_path, encoding="utf-8") as f:
                    status = json.load(f)
            except (json.JSONDecodeError, OSError):
                status = {}
        out[ptype] = {
            "running": lock_is_held(os.path.expanduser(cfg.get("lockFile") or "")),
            "intervalSeconds": cfg.get("intervalSeconds"),
            "triggerable": isinstance(cfg.get("command"), list) and bool(cfg.get("command")),
            "status": status,
        }
    return out


def handle_sync(msg):
    for d in (OUTBOX, INBOX, PROCESSED, STATE, CAPTURES):
        os.makedirs(d, exist_ok=True)

    errors = []

    outbox_map = msg.get("outbox") or {}
    if not isinstance(outbox_map, dict) or len(outbox_map) > MAX_SYNC_TYPES:
        return {"ok": False, "error": "outbox 类型数量超过限制"}
    for ptype, articles in outbox_map.items():
        if not safe_name(ptype):
            errors.append(f"非法类型名: {ptype}")
            continue
        if not isinstance(articles, list) or len(articles) > MAX_OUTBOX_ARTICLES:
            errors.append(f"{ptype}: outbox 文章数量超过限制")
            continue
        enriched_articles = []
        for article in articles if isinstance(articles, list) else []:
            if not isinstance(article, dict):
                continue
            enriched = dict(article)
            article_key = str(article.get("articleKey") or "")
            if article_key:
                capture_path = os.path.join(
                    CAPTURES,
                    hashlib.sha256(article_key.encode("utf-8")).hexdigest() + ".json",
                )
                if os.path.isfile(capture_path):
                    enriched["captureFile"] = capture_path
            enriched_articles.append(enriched)
        atomic_write_json(os.path.join(OUTBOX, ptype + ".json"), {
            "processingType": ptype,
            "generatedAt": msg.get("generatedAt"),
            "articles": enriched_articles,
        })

    for rid in (msg.get("acks") or []):
        if not safe_name(rid):
            continue
        src = os.path.join(INBOX, rid + ".json")
        if os.path.isfile(src):
            os.replace(src, os.path.join(PROCESSED, rid + ".json"))

    reports = []
    for fname in sorted(os.listdir(INBOX)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(INBOX, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                rep = json.load(f)
            rep["reportId"] = fname[:-5]  # 文件名即 ack 标识
            reports.append(rep)
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"{fname}: {e}")

    return {"ok": True, "reports": reports, "errors": errors, "flows": flow_statuses()}


def handle_capture(msg):
    """Persist a user-initiated rendered-page snapshot without cookies or headers."""
    article_key = str(msg.get("articleKey") or "").strip()
    url = str(msg.get("url") or "").strip()
    capture = msg.get("capture") or {}
    content = str(capture.get("content") or "").strip()
    if not article_key or len(article_key) > 4096:
        return {"ok": False, "error": "页面快照缺少有效 articleKey"}
    try:
        parsed_url = urlparse(url)
    except ValueError:
        parsed_url = None
    if (
        parsed_url is None
        or parsed_url.scheme not in {"https", "http"}
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
    ):
        return {"ok": False, "error": "页面快照只接受 http/https 来源"}
    if len(content) < 160:
        return {"ok": False, "error": "页面正文过短，未保存快照"}
    if len(content.encode("utf-8")) > 1_500_000:
        return {"ok": False, "error": "页面正文超过 1.5 MB 快照上限"}
    os.makedirs(CAPTURES, exist_ok=True)
    capture_path = os.path.join(
        CAPTURES,
        hashlib.sha256(article_key.encode("utf-8")).hexdigest() + ".json",
    )
    atomic_write_json(capture_path, {
        "schemaVersion": 1,
        "articleKey": article_key,
        "url": url,
        "capturedAt": str(msg.get("capturedAt") or ""),
        "extractor": "browser-rendered-user-initiated",
        "title": str(capture.get("title") or "")[:1000],
        "published": str(capture.get("published") or "")[:100],
        "authors": str(capture.get("authors") or "")[:1000],
        "content": content,
    })
    return {"ok": True, "captureFile": capture_path, "chars": len(content)}


def handle_trigger(msg):
    _TRIGGERED_PROCESSES[:] = [p for p in _TRIGGERED_PROCESSES if p.poll() is None]
    ptype = msg.get("processingType")
    if not safe_name(ptype):
        return {"ok": False, "error": f"非法类型名: {ptype}"}
    cfg = load_flows().get(ptype)
    if not cfg or not isinstance(cfg.get("command"), list) or not cfg["command"]:
        return {"ok": False, "error": f"flows.json 未注册可触发的流程: {ptype}"}
    command_error = validate_flow_command(cfg)
    if command_error:
        return {"ok": False, "error": command_error}
    if lock_is_held(os.path.expanduser(cfg.get("lockFile") or "")):
        return {"ok": True, "started": False, "alreadyRunning": True}
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, f"{ptype}-trigger.log"), "ab") as logf:
        proc = subprocess.Popen(
            cfg["command"],
            stdout=logf,
            stderr=logf,
            start_new_session=True,
            cwd=str(HOME),
            env=trigger_env(),
        )
    _TRIGGERED_PROCESSES.append(proc)
    return {"ok": True, "started": True}


def validate_flow_command(cfg):
    command = cfg.get("command") if isinstance(cfg, dict) else None
    if not isinstance(command, list) or len(command) < 2 or len(command) > 8:
        return "流程命令必须是受限 argv 数组"
    if any(not isinstance(part, str) or not part or len(part) > 4096 for part in command):
        return "流程命令参数无效"
    executable = Path(command[0]).expanduser().resolve()
    script = Path(command[1]).expanduser().resolve()
    trusted_bin = (HOME / ".info-collector" / "bin").resolve()
    try:
        script.relative_to(trusted_bin)
    except ValueError:
        return "流程脚本不在受信任 bin 目录内"
    if not executable.is_file() or not script.is_file():
        return "流程可执行文件或脚本不存在"
    expected = str(cfg.get("scriptSha256") or "").casefold()
    if not expected:
        return "流程缺少 scriptSha256，请重新运行安装器"
    actual = hashlib.sha256(script.read_bytes()).hexdigest()
    if actual != expected:
        return "流程脚本哈希不匹配，请重新安装后再触发"
    return ""


def open_local_path(path):
    """Open a trusted generated artifact with the user's default application."""
    if os.name == "nt":
        os.startfile(str(path))
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def handle_open_output(msg):
    ptype = msg.get("processingType")
    contract = OPENABLE_OUTPUTS.get(ptype)
    if not contract:
        return {"ok": False, "error": f"不允许打开该流程输出: {ptype}"}
    status_name, field = contract
    status_path = Path(STATE) / status_name
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "尚未找到可打开的生成结果"}
    raw_path = status.get(field) or (status.get("lastRun") or {}).get(field)
    if not raw_path:
        return {"ok": False, "error": "生成状态中没有输出路径"}
    target = Path(raw_path).expanduser().resolve()
    home = HOME.resolve()
    try:
        target.relative_to(home)
    except ValueError:
        return {"ok": False, "error": "输出路径不在用户目录内，已拒绝打开"}
    if not target.is_file():
        return {"ok": False, "error": "生成文件不存在，请重新生成"}
    open_local_path(target)
    return {"ok": True, "path": str(target)}


def main():
    configure_native_stdio()
    while True:
        try:
            msg = read_message()
        except Exception:
            break
        if msg is None:
            break
        mtype = msg.get("type")
        try:
            if mtype == "sync":
                send_message(handle_sync(msg))
            elif mtype == "trigger":
                send_message(handle_trigger(msg))
            elif mtype == "open-output":
                send_message(handle_open_output(msg))
            elif mtype == "capture":
                send_message(handle_capture(msg))
            elif mtype == "ping":
                send_message({"ok": True, "pong": True})
            else:
                send_message({"ok": False, "error": f"未知消息类型: {mtype}"})
        except Exception as e:
            try:
                send_message({"ok": False, "error": str(e)})
            except Exception:
                break


if __name__ == "__main__":
    main()

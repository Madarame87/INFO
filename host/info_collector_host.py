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
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

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
FLOWS_FILE = os.path.join(SPOOL, "flows.json")
_TRIGGERED_PROCESSES = []


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
    for d in (OUTBOX, INBOX, PROCESSED, STATE):
        os.makedirs(d, exist_ok=True)

    errors = []

    for ptype, articles in (msg.get("outbox") or {}).items():
        if not safe_name(ptype):
            errors.append(f"非法类型名: {ptype}")
            continue
        atomic_write_json(os.path.join(OUTBOX, ptype + ".json"), {
            "processingType": ptype,
            "generatedAt": msg.get("generatedAt"),
            "articles": articles,
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


def handle_trigger(msg):
    _TRIGGERED_PROCESSES[:] = [p for p in _TRIGGERED_PROCESSES if p.poll() is None]
    ptype = msg.get("processingType")
    if not safe_name(ptype):
        return {"ok": False, "error": f"非法类型名: {ptype}"}
    cfg = load_flows().get(ptype)
    if not cfg or not isinstance(cfg.get("command"), list) or not cfg["command"]:
        return {"ok": False, "error": f"flows.json 未注册可触发的流程: {ptype}"}
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

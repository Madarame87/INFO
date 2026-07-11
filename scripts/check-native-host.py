#!/usr/bin/env python3
"""Send a binary-protocol ping through the installed Windows host wrapper."""

import argparse
import json
from pathlib import Path
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wrapper",
        type=Path,
        default=Path.home() / ".info-collector" / "native-host" / "info-collector-host.bat",
    )
    args = parser.parse_args()
    wrapper = args.wrapper.resolve()
    if not wrapper.is_file():
        raise SystemExit(f"Native host wrapper not found: {wrapper}")

    payload = json.dumps({"type": "ping"}).encode("utf-8")
    proc = subprocess.Popen(
        [str(wrapper)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(struct.pack("<I", len(payload)) + payload, timeout=10)
    if proc.returncode != 0:
        raise SystemExit(
            f"Native host exited with {proc.returncode}: "
            f"{stderr.decode('utf-8', errors='replace')}"
        )
    if len(stdout) < 4:
        raise SystemExit("Native host returned no valid length prefix")
    (length,) = struct.unpack("<I", stdout[:4])
    response = json.loads(stdout[4:4 + length].decode("utf-8"))
    if response != {"ok": True, "pong": True}:
        raise SystemExit(f"Unexpected native host response: {response}")
    print(f"OK Native host binary ping: {wrapper}")


if __name__ == "__main__":
    main()

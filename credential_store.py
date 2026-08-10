"""Small Windows DPAPI credential store used by Info Collector.

Secrets are encrypted for the current Windows user and never written to config.json.
"""

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _credential_path(reference, home=None):
    base = Path(home or os.environ.get("INFO_COLLECTOR_HOME") or Path.home())
    name = hashlib.sha256(reference.encode("utf-8")).hexdigest() + ".bin"
    return base / ".info-collector" / "credentials" / name


def protect(secret):
    if os.name != "nt":
        raise RuntimeError("DPAPI credential storage requires Windows")
    source, source_buffer = _blob(secret.encode("utf-8"))
    output = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "Info Collector", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


def unprotect(payload):
    if os.name != "nt":
        raise RuntimeError("DPAPI credential storage requires Windows")
    source, source_buffer = _blob(payload)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del source_buffer


def store_credential(reference, secret, home=None):
    path = _credential_path(reference, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(protect(secret))
    os.replace(temp, path)
    return path


def load_credential(reference, home=None):
    if not reference:
        return ""
    path = _credential_path(reference, home)
    try:
        return unprotect(path.read_bytes())
    except OSError:
        return ""


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", metavar="REFERENCE")
    args = parser.parse_args(argv)
    if not args.store:
        parser.error("--store is required")
    secret = sys.stdin.readline().rstrip("\r\n")
    if not secret:
        raise SystemExit("empty credential")
    store_credential(args.store, secret)
    print("credential stored with Windows DPAPI")


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Info Collector 0.2 supports production-pilot installation on Windows 11 only.
The retired macOS installer stored provider credentials in plaintext and is
intentionally disabled. Use scripts/setup.ps1 on Windows, or contribute a
Keychain-backed installer with equivalent security and integration tests.
EOF
exit 1

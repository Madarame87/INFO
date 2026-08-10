# Windows support matrix

Info Collector 0.2 supports a controlled commercial pilot on Windows 11, Chrome and Python 3.9+.

## Automated gates

- Cross-platform queue and state-machine tests.
- Windows Native Messaging binary protocol tests.
- Typed source, extraction and model failure tests.
- Visible-page capture size, URL and trust-boundary tests.
- Reading-site generation, quarantine and deployable-snapshot tests.
- PowerShell installer syntax validation.

## Manual release gate

Before a pilot release, run the checklist in [OPERATIONS.md](OPERATIONS.md) with representative public, 401/403, login-wall, long-form and multilingual sources. Record the source mix, success denominator, latency, cost and human translation review.

macOS and Linux are not in the supported pilot matrix. `scripts/setup.sh` is intentionally disabled until a Keychain-backed installer and equivalent integration suite exist.

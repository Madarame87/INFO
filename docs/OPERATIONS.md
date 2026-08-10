# Operations and controlled-commercial pilot

## Release gate

A release is eligible for a controlled pilot only when:

1. Node and Python suites pass on a clean Windows machine.
2. Native Host ping, install, upgrade and rollback are exercised.
3. 401, login-page contamination, DNS failure, redirect-to-private-IP, 429, 5xx, API refusal, malformed output, process interruption and disk-full paths are injected.
4. No secret appears in config, logs, static output or Git history.
5. The deployed commit, asset hash and rollback commit are recorded.
6. Source-use, retention and public-republication decisions are approved for the pilot corpus.

## Runtime contract

| Code | Automatic retry | Operator action |
|---|---:|---|
| `source_auth_required` | no | open the authorized page and save the visible article again |
| `source_content_rejected` | no | inspect the page; recapture only when real body text is visible |
| `source_network` / selected 5xx | up to 3 attempts | wait; then inspect DNS/network |
| `model_api_transient` / 429 | up to 3 attempts | honor backoff; check provider status |
| `model_api_rejected` | no | rotate/fix the local credential or model access |
| `translation_segment_incomplete` | bounded | retry from the saved segment checkpoint |
| `translation_cost_limit` | no | shorten the capture or explicitly raise the local budget |

Manual “重新排队” resets the three-attempt budget. A failure with `retryable=false` must never be sent back to the worker automatically.

## Cost and capacity controls

Defaults are 20 articles per run, 300,000 source characters per article, 48,000-character long-form segments, three API attempts and bounded output. Configure `maxArticlesPerRun` and `maxTranslationInputChars` locally only after measuring provider cost. These are safety defaults, not throughput or price claims.

## Pilot SLIs

Record exact denominators by source class and language:

- correct block classification / reviewed access blocks;
- accepted extraction / permitted 2xx article pages;
- structurally valid translation / model attempts;
- critical translation error segments / human-reviewed segments;
- usable artifacts / admitted jobs;
- p50/p95 completion latency and cost per usable artifact;
- retry amplification, queue age and recovery time.

Do not advertise an SLA or accuracy percentage until a frozen representative corpus and observation window support it.

## Runbooks

### Access block

Confirm HTTP status and `operatorAction`. Do not retry 401/403 anonymously. Open the source, verify the operator has access and rights, capture by explicit click, bridge-sync, and verify the job returns to `pending` before triggering.

### Provider incident

Stop manual triggers, retain the outbox, confirm no retry storm, inspect low-cardinality error codes, restore provider access, then requeue a canary article before the backlog.

### Spool corruption

Stop Chrome and workers, copy `.info-collector` for evidence, restore the last consistent backup, validate JSON and hashes, start the Native Host, bridge once, and compare active/archive counts before processing.

### Secret compromise

Stop flows, revoke the provider key, rerun setup to store a replacement with DPAPI, search logs and repository history for exposure, and process one canary. Never paste the key into an issue.

### Bad release / rollback

Keep the prior commit and installed `~/.info-collector/bin` package. Stop flows, back up spool state, restore the prior package, reload the extension, ping the host, bridge once, and verify queue plus artifact hashes. Record the failing and restored commits.

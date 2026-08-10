#!/usr/bin/env python3
"""
é€šç”¨ç¿»è¯‘æµï¼ˆtranslateï¼‰ï¼šæ”¯æŒ DeepSeek API æˆ– Anthropic APIï¼Œæ— ä»»ä½•ç¬¬ä¸‰æ–¹ä¾èµ–ã€‚
1. è¯» ~/.info-collector/outbox/translate.jsonï¼ˆInfo Collector æ‰©å±•å¯¼å‡ºï¼‰
2. é€ç¯‡æŠ“å–åŸæ–‡å¹¶è°ƒ LLM API ç¿»è¯‘æˆä¸­æ–‡ Markdown
3. è¯‘æ–‡å­˜åˆ°é…ç½®çš„è¾“å‡ºç›®å½•ï¼Œç»“æœå†™æˆ Completion Report æ”¾è¿› inbox/

é…ç½®æ–‡ä»¶ ~/.info-collector/config.jsonï¼š
  { "provider": "deepseek", "credentialRef": "info-collector/deepseek",
    "model": "deepseek-v4-flash", "outputDir": "~/Documents/InfoCollector" }

å¯†é’¥ç”± setup.ps1 å†™å…¥ Windows DPAPI å‡­æ®æ–‡ä»¶ï¼›CI å¯ä¸´æ—¶ä½¿ç”¨ INFO_COLLECTOR_API_KEYã€‚

ç”¨æ³•ï¼š
  translate-flow.py            å®šæ—¶è¿è¡Œï¼ˆlaunchdï¼‰
  translate-flow.py --manual   æ‰‹åŠ¨è§¦å‘ï¼ˆDashboardã€Œç«‹å³å¤„ç†ã€ï¼‰
  translate-flow.py --check    è‡ªæ£€ï¼šé…ç½®ã€ç›®å½•ã€API Key æœ‰æ•ˆæ€§ï¼Œä¸ç¿»è¯‘
"""

from html.parser import HTMLParser
import datetime as dt
import ipaddress
import json
import hashlib
import os
from pathlib import Path
import random
import re
import socket
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

try:
    from info_collector_platform import acquire_lock as acquire_file_lock
    from info_collector_platform import release_lock, user_home
    from credential_store import load_credential
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from info_collector_platform import acquire_lock as acquire_file_lock
    from info_collector_platform import release_lock, user_home
    from credential_store import load_credential


HOME = user_home()
SPOOL = str(HOME / ".info-collector")
CONFIG_FILE = os.path.join(SPOOL, "config.json")
OUTBOX_FILE = os.path.join(SPOOL, "outbox", "translate.json")
INBOX_DIR = os.path.join(SPOOL, "inbox")
STATE_FILE = os.path.join(SPOOL, "state", "translate-reported.json")
STATUS_FILE = os.path.join(SPOOL, "state", "translate-status.json")
LOCK_FILE = os.path.join(SPOOL, "state", "translate.lock")
LOG_FILE = os.path.join(SPOOL, "state", "translate-flow.log")
CAPTURE_DIR = Path(SPOOL) / "captures"
CHECKPOINT_DIR = Path(SPOOL) / "checkpoints" / "translate"

API_VERSION = "2023-06-01"
DEFAULT_PROVIDER = "deepseek"
PROVIDER_DEFAULTS = {
    "deepseek": {
        "baseUrl": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    },
    "anthropic": {
        "baseUrl": "https://api.anthropic.com",
        "model": "claude-opus-4-8",
    },
}
MAX_TOKENS = 16000          # Anthropic ä¸ç»“æ„ä¿®å¤çš„ä¿å®ˆè¾“å‡ºä¸Šé™
MAX_DEEPSEEK_OUTPUT_TOKENS = 64000  # V4 Flash æ”¯æŒé•¿è¾“å‡ºï¼Œé¿å…é•¿æ–‡åœ¨ 16K å¤„è¢«æˆªæ–­
REQUEST_TIMEOUT = 900       # å•ç¯‡ç¿»è¯‘æœ€é•¿ç­‰å¾…ï¼ˆç§’ï¼‰
MAX_CONTINUATIONS = 4       # æœåŠ¡ç«¯å·¥å…· pause_turn ç»­è·‘æ¬¡æ•°ä¸Šé™
FETCH_TIMEOUT = 45
DEFUDDLE_TIMEOUT = 90
MAX_FETCH_BYTES = 2_000_000
MAX_DEEPSEEK_INPUT_CHARS = 180_000
MAX_REPAIR_INPUT_CHARS = 180_000
REJECTED_PREVIEW_CHARS = 500
MAX_SUMMARY_CHARS = 240
MAX_TAGS = 5
MAX_API_ATTEMPTS = 3
SEGMENT_INPUT_CHARS = 48_000
MIN_ARTICLE_CHARS = 160
DEFAULT_MAX_ARTICLES_PER_RUN = 20
DEFAULT_MAX_TRANSLATION_INPUT_CHARS = 300_000


class PipelineError(RuntimeError):
    """A typed failure that can cross the Python/extension spool boundary."""

    def __init__(self, message, *, code, stage, retryable, http_status=None,
                 operator_action=None, retry_after_seconds=None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = bool(retryable)
        self.http_status = http_status
        self.operator_action = operator_action
        self.retry_after_seconds = retry_after_seconds

    def report_meta(self):
        meta = {
            "error": str(self)[:300],
            "code": self.code,
            "stage": self.stage,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            meta["httpStatus"] = int(self.http_status)
        if self.operator_action:
            meta["operatorAction"] = self.operator_action
        if self.retry_after_seconds:
            meta["retryAfterSeconds"] = int(self.retry_after_seconds)
        return meta


class SourceAccessBlockedError(PipelineError):
    """The publisher returned an explicit access-control response."""

    def __init__(self, url, status):
        self.url = str(url)
        self.status = int(status)
        super().__init__(
            f"åŸç«™è¦æ±‚æˆæƒï¼ˆHTTP {self.status}ï¼‰ï¼›è¯·åœ¨æµè§ˆå™¨æ‰“å¼€é¡µé¢å¹¶é‡æ–°ä¿å­˜ä»¥é‡‡é›†å½“å‰å¯è§æ­£æ–‡",
            code="source_auth_required",
            stage="extract",
            retryable=False,
            http_status=self.status,
            operator_action="open_and_capture",
        )


class SourceContentRejectedError(PipelineError):
    def __init__(self, message="æŠ“å–ç»“æœç–‘ä¼¼ç™»å½•é¡µã€æŒ‘æˆ˜é¡µæˆ–é¡µé¢æ ·æ¿ï¼Œå·²æ‹’ç»è¿›å…¥ç¿»è¯‘"):
        super().__init__(
            message,
            code="source_content_rejected",
            stage="quality_gate",
            retryable=False,
            operator_action="open_and_capture",
        )

CANONICAL_TAGS = (
    "äººå·¥æ™ºèƒ½", "ä¸–ç•Œæ¨¡å‹", "æœºå™¨äºº", "å…·èº«æ™ºèƒ½", "å¤§æ¨¡å‹", "æ™ºèƒ½ä½“", "å¤šæ¨¡æ€",
    "æ¨¡å‹è¯„ä¼°", "è®°å¿†ç³»ç»Ÿ", "æ¨ç†", "è®­ç»ƒ", "æ•°æ®", "èŠ¯ç‰‡", "å¼€æº", "äº§å“",
    "äº§ä¸šåŠ¨æ€", "å­¦æœ¯ç ”ç©¶",
)

ENRICHMENT_RULES = (
    "é™¤ç¿»è¯‘å¤–ï¼Œè¿˜è¦å®Œæˆä¿¡æ¯æç‚¼ï¼šfrontmatter å¿…é¡»åŒ…å«ä¸€è¡Œ summaryï¼Œ"
    "ç”¨ 80-160 ä¸ªç®€ä½“ä¸­æ–‡å­—ç¬¦æ¦‚æ‹¬æ–‡ç« çš„æ ¸å¿ƒäº‹å®æˆ–ä¸»å¼ ï¼›å¿…é¡»åŒ…å«ä¸€è¡Œ tagsï¼Œ"
    "æ ¼å¼ä¸¥æ ¼ä¸º JSON é£æ ¼æ•°ç»„ï¼Œä¾‹å¦‚ tags: [\"æ™ºèƒ½ä½“\", \"æ¨¡å‹è¯„ä¼°\"]ã€‚"
    "ç»™å‡º 2-5 ä¸ªç®€çŸ­æ ‡ç­¾ï¼Œä¼˜å…ˆå¤ç”¨ä»¥ä¸‹è§„èŒƒæ ‡ç­¾ï¼š"
    + "ã€".join(CANONICAL_TAGS)
    + "ã€‚ç¡®æœ‰å¿…è¦æ—¶æ‰åˆ›å»ºæ–°æ ‡ç­¾ã€‚frontmatter åã€å®Œæ•´è¯‘æ–‡å‰åŠ å…¥ã€Œ## æ‘˜è¦ã€å°èŠ‚ï¼Œ"
      "æ­£æ–‡ä½¿ç”¨ä¸ summary ç›¸åŒçš„æ‘˜è¦ã€‚"
)

TRIGGER = "manual" if "--manual" in sys.argv else "scheduled"

SYSTEM_PROMPT = (
    "ä½ æ˜¯ä¸€åä¸“ä¸šè¯‘è€…ã€‚ç”¨ web_fetch å·¥å…·æŠ“å–ç»™å®š URL çš„æ–‡ç« ï¼Œ"
    "æŠŠæ­£æ–‡å®Œæ•´ç¿»è¯‘æˆè‡ªç„¶é€šé¡ºçš„ç®€ä½“ä¸­æ–‡ Markdownã€‚è§„åˆ™ï¼š"
    "ä»£ç å—ã€å‘½ä»¤ã€è·¯å¾„åŸæ ·ä¿ç•™ä¸ç¿»è¯‘ï¼›å›¾ç‰‡ä¿ç•™åŸè¿œç¨‹é“¾æ¥ï¼›"
    "æ–‡ç« ä¸»æ ‡é¢˜ç”¨ã€Œä¸­æ–‡ï¼ˆEnglishï¼‰ã€åŒè¯­å½¢å¼ã€‚"
    + ENRICHMENT_RULES +
    "frontmatter åªå¡«å†™ titleã€published_atã€authorsã€summaryã€tagsï¼›"
    "ä¸è¦å¡«å†™ article_keyã€sourceã€collected_atã€processed_at æˆ– dateï¼Œè¿™äº›å­—æ®µç”±æœ¬æœºç¡®å®šã€‚"
    "ä½ çš„æœ€ç»ˆå›å¤å¿…é¡»åªåŒ…å«å®Œæˆçš„ Markdown æ–‡æ¡£æœ¬èº«"
    "ï¼ˆä»¥ --- å¼€å¤´çš„ YAML frontmatter å¼€å§‹ï¼‰ï¼Œ"
    "ä¸è¦æœ‰ä»»ä½•è§£é‡Šã€å‰è¨€æˆ–ä»£ç å›´æ ã€‚"
)


def configure_text_stdio():
    """Keep all console output alive on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass


def safe_console_print(text):
    """Print text without allowing a narrow console encoding to abort a run."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_text, flush=True)


def log(msg):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    safe_console_print(f"[{ts}] {msg}")


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default
    return default


def load_config():
    cfg = load_json(CONFIG_FILE, {})
    provider = normalize_provider(cfg)
    cfg["provider"] = provider
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
    cfg["baseUrl"] = (cfg.get("baseUrl") or cfg.get("baseURL") or
                      cfg.get("apiBase") or defaults["baseUrl"]).rstrip("/")
    if not cfg.get("model") or model_looks_like_other_provider(cfg.get("model", ""), provider):
        cfg["model"] = defaults["model"]
    if not cfg.get("apiKey"):
        cfg["apiKey"] = (
            os.environ.get("INFO_COLLECTOR_API_KEY")
            or load_credential(cfg.get("credentialRef") or f"info-collector:{provider}")
        )
    cfg.setdefault("outputDir", str(HOME / "Documents" / "InfoCollector"))
    try:
        cfg["maxArticlesPerRun"] = max(1, min(int(cfg.get("maxArticlesPerRun") or DEFAULT_MAX_ARTICLES_PER_RUN), 100))
    except (TypeError, ValueError):
        cfg["maxArticlesPerRun"] = DEFAULT_MAX_ARTICLES_PER_RUN
    try:
        cfg["maxTranslationInputChars"] = max(
            SEGMENT_INPUT_CHARS,
            min(int(cfg.get("maxTranslationInputChars") or DEFAULT_MAX_TRANSLATION_INPUT_CHARS), 1_000_000),
        )
    except (TypeError, ValueError):
        cfg["maxTranslationInputChars"] = DEFAULT_MAX_TRANSLATION_INPUT_CHARS
    return cfg


def normalize_provider(cfg):
    provider = (cfg.get("provider") or cfg.get("apiProvider") or "").strip().lower()
    if not provider:
        provider = "anthropic" if (cfg.get("apiKey") or "").startswith("sk-ant-") else DEFAULT_PROVIDER
    aliases = {"claude": "anthropic", "anthropic": "anthropic", "deepseek": "deepseek"}
    if provider not in aliases:
        return provider
    return aliases[provider]


def model_looks_like_other_provider(model, provider):
    if provider == "deepseek":
        return model.startswith("claude-")
    if provider == "anthropic":
        return model.startswith("deepseek-")
    return False


def api_base_url_error(cfg):
    """Keep provider credentials on an explicitly trusted HTTPS endpoint."""
    provider = cfg.get("provider")
    base_url = str(cfg.get("baseUrl") or "").strip().rstrip("/")
    if not base_url:
        return "æ¨¡å‹ API baseUrl æœªé…ç½®"
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return "æ¨¡å‹ API baseUrl æ ¼å¼æ— æ•ˆ"
    if not parsed.hostname or parsed.username or parsed.password:
        return "æ¨¡å‹ API baseUrl ä¸å¾—åŒ…å«å‡­æ®ï¼Œä¸”å¿…é¡»åŒ…å«ä¸»æœºå"
    if parsed.query or parsed.fragment:
        return "æ¨¡å‹ API baseUrl ä¸å¾—åŒ…å« query æˆ– fragment"
    if parsed.scheme not in {"https", "http"}:
        return "æ¨¡å‹ API baseUrl å¿…é¡»ä½¿ç”¨ HTTPS"

    official = (PROVIDER_DEFAULTS.get(provider) or {}).get("baseUrl", "").rstrip("/")
    if base_url == official:
        return None

    allow_custom = os.environ.get("INFO_COLLECTOR_ALLOW_CUSTOM_API_BASE") == "1"
    allow_insecure_test = os.environ.get("INFO_COLLECTOR_ALLOW_INSECURE_API_BASE_FOR_TESTS") == "1"
    if parsed.scheme != "https" and not allow_insecure_test:
        return "è‡ªå®šä¹‰æ¨¡å‹ API baseUrl å¿…é¡»ä½¿ç”¨ HTTPS"
    if not allow_custom and not allow_insecure_test:
        return "è‡ªå®šä¹‰æ¨¡å‹ API baseUrl éœ€è¦æ˜¾å¼è®¾ç½® INFO_COLLECTOR_ALLOW_CUSTOM_API_BASE=1"
    return None


def config_error(cfg):
    key = cfg.get("apiKey") or ""
    provider = cfg.get("provider")
    if provider not in PROVIDER_DEFAULTS:
        return f"ä¸æ”¯æŒçš„ API providerï¼š{provider}ï¼ˆå¯é€‰ deepseek æˆ– anthropicï¼‰"
    if len(key) <= 20:
        return "API Key æœªé…ç½®æˆ–è¿‡çŸ­"
    if provider == "anthropic" and not key.startswith("sk-ant-"):
        return "Anthropic API Key åº”ä»¥ sk-ant- å¼€å¤´"
    if provider == "deepseek" and not key.startswith("sk-"):
        return "DeepSeek API Key é€šå¸¸ä»¥ sk- å¼€å¤´"
    return api_base_url_error(cfg)


def config_ok(cfg):
    return config_error(cfg) is None


# ===== APIï¼ˆæ ‡å‡†åº“ raw HTTPï¼‰=====

def post_json(url, payload, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            retry_after = e.headers.get("retry-after") if e.headers else None
            try:
                retry_after_seconds = int(retry_after) if retry_after else None
            except ValueError:
                retry_after_seconds = None
            retryable = e.code in {408, 409, 425, 429} or 500 <= e.code <= 599
            if retryable and attempt < MAX_API_ATTEMPTS:
                delay = min(retry_after_seconds or (2 ** (attempt - 1)), 20)
                time.sleep(delay + random.random() * 0.25)
                continue
            raise PipelineError(
                f"æ¨¡å‹ API HTTP {e.code}: {body}",
                code="model_api_transient" if retryable else "model_api_rejected",
                stage="translate",
                retryable=retryable,
                http_status=e.code,
                operator_action="retry_later" if retryable else "check_api_credentials",
                retry_after_seconds=retry_after_seconds,
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < MAX_API_ATTEMPTS:
                time.sleep((2 ** (attempt - 1)) + random.random() * 0.25)
                continue
            raise PipelineError(
                f"æ¨¡å‹ API ç½‘ç»œå¤±è´¥: {e}",
                code="model_api_network",
                stage="translate",
                retryable=True,
                operator_action="retry_later",
            ) from e


def anthropic_request(path, payload, cfg):
    endpoint_error = api_base_url_error(cfg)
    if endpoint_error:
        raise ValueError(endpoint_error)
    return post_json(
        f"{cfg['baseUrl']}{path}",
        payload,
        {
            "x-api-key": cfg["apiKey"],
            "anthropic-version": API_VERSION,
        },
    )


def deepseek_request(path, payload, cfg):
    endpoint_error = a×MôÚÚ$z{-®éÜj×6æöæ–6Â²&W6W'fVE¶–ç6W'F–öã¥ĞĞ¢&öG’ÒÖ&¶F÷vå¶ÖF6‚æVæB‚“¥ÒæÇ7G&—‚%Ç%Æâ"Ğ¢&WGW&â"ÒÒÕÆâ"²%Æâ"æ¦ö–â†f–æÅöÆ–æW2’ç7G&—‚’²%ÆâÒÒÕÆåÆâ"²&öGĞ Ğ Ğ¦FVbæ÷&ÖÆ—¦U÷Fr‡Fr“ Ğ¢FrÒ&Rç7V"‡"%Ç2²"Â""Â7G"‡Fr’’ç7G&—‚’æÇ7G&—‚">ûÈ2"’ç7G&—‚Ğ¢FrÒDuôÄ”4U2ævWB‡Fræ66VföÆB‚’ÂFrĞ¢&WGW&âFu³£#EÒç7G&—‚Ğ Ğ Ğ¦FVbW‡G&7EöVç&–6†ÖVçB†Ö&¶F÷vâ“ Ğ¢""$W‡G&7BF†R&÷VæFVB7VÖÖ'’õFw26öçG&7Bg&öÒÖ&¶F÷vâg&öçFÖGFW"â"" Ğ¢ÖF6‚Ò&RæÖF6‚‡"%ÄÒÒÕÇ2¥Ç#õÆâ‚â£ò•Ç#õÆâÒÒÒƒó¥Ç#õÆçÅÅ¢’"ÂÖ&¶F÷vâÂ&RäDõDÄÂĞ¢–bæ÷BÖF6ƒ Ğ¢&—6R'VçF–ÖTW'&÷"‚.Šùih~{Ë®[	”ÔÂg&öçFÖGFW""Ğ¢g&öçFÖGFW"ÒÖF6‚æw&÷WƒĞ Ğ¢7VÖÖ'•öÖF6‚Ò&Rç6V&6‚‡""ƒöÒ•ç7VÖÖ'“¥²ÇEÒ¢‚â¢’B"Âg&öçFÖGFW"Ğ¢7VÖÖ'’Ò'6Uög&öçFÖGFW%÷66Æ"‡7VÖÖ'•öÖF6‚æw&÷Wƒ’’–b7VÖÖ'•öÖF6‚VÇ6R" Ğ¢7VÖÖ'’Ò&Rç7V"‡"%Ç2²"Â""Â7VÖÖ'’’ç7G&—‚Ğ¢–bÆVâ‡7VÖÖ'’’âÔ…õ5TÔÔ%•ô4„%3 Ğ¢7VÖÖ'’Ò7VÖÖ'•³¤Ô…õ5TÔÔ%•ô4„%2ÒÒç'7G&—‚’².(
b Ğ¢–bæ÷B7VÖÖ'“ Ğ¢&—6R'VçF–ÖTW'&÷"‚.Šùihrg&öçFÖGFW"{Ë®[	7VÖÖ'’"Ğ Ğ¢Fw2ÒµĞĞ¢Fw5öÖF6‚Ò&Rç6V&6‚‡""ƒöÒ•çFw3¥²ÇEÒ¢‚â¢’B"Âg&öçFÖGFW"Ğ¢–bFw5öÖF6ƒ Ğ¢&u÷Fw2ÒFw5öÖF6‚æw&÷Wƒ’ç7G&—‚Ğ¢–b&u÷Fw3 Ğ¢G'“ Ğ¢'6VBÒ§6öâæÆöG2‡&u÷Fw2Ğ¢Fw2Ò'6VB–b—6–ç7Fæ6R‡'6VBÂÆ—7B’VÇ6R·'6VEĞĞ¢W†6WB§6öâä¥4ôäFV6öFTW'&÷# Ğ¢Fw2Ò·'Bç7G&—‚"uÂ""’f÷"'B–â&Rç7Æ—B‡"%²ÎûÈÅÒ"Â&u÷Fw2ç7G&—‚%µÒ"’•ĞĞ¢VÇ6S Ğ¢F–ÂÒg&öçFÖGFW%·Fw5öÖF6‚æVæB‚“¥ĞĞ¢Fw2Ò&Ræf–æFÆÂ‡""ƒöÒ•åÇ2¢ÕÇ2¢‚â³ò•Ç2¢B"ÂF–ÂĞ Ğ¢æ÷&ÖÆ—¦VBÒµĞĞ¢6VVâÒ6WB‚Ğ¢f÷"Fr–âFw3 Ğ¢6ÆVâÒæ÷&ÖÆ—¦U÷Fr‡FrĞ¢¶W’Ò6ÆVâæ66VföÆB‚Ğ¢–b6ÆVâæB¶W’æ÷B–â6VVã Ğ¢æ÷&ÖÆ—¦VBæVæB†6ÆVâĞ¢6VVâæFB†¶W’Ğ¢–bÆVâ†æ÷&ÖÆ—¦VB’ÓÒÔ…õDu3 Ğ¢'&V°Ğ¢–bÆVâ†æ÷&ÖÆ—¦VB’Â# Ğ¢&—6R'VçF–ÖTW'&÷"‚.Šùihrg&öçFÖGFW"ˆ{>[	™ÈŠh"KŠ®iÈiX‚Fw2"Ğ¢&WGW&â²'7VÖÖ'’#¢7VÖÖ'’Â'Fw2#¢æ÷&ÖÆ—¦VGĞĞ Ğ Ğ¦FVbVç7W&U÷7VÖÖ'•÷6V7F–öâ†Ö&¶F÷vâÂ7VÖÖ'’“ Ğ¢–b&Rç6V&6‚‡""ƒöÒ•â25Ç2¾iŠhÇ2¢B"ÂÖ&¶F÷vâ“ Ğ¢&WGW&âÖ&¶F÷vàĞ¢ÖF6‚Ò&RæÖF6‚‡"%ÄÒÒÕÇ2¥Ç#õÆââ£õÇ#õÆâÒÒÕÇ2¢"ÂÖ&¶F÷vâÂ&RäDõDÄÂĞ¢–bæ÷BÖF6ƒ Ğ¢&WGW&âÖ&¶F÷vàĞ¢&WGW&âÖ&¶F÷vå³¦ÖF6‚æVæB‚•Òç'7G&—‚’²b%ÆåÆâ22iŠhÆåÆç·7VÖÖ'—ÕÆåÆâ"²Ö&¶F÷vå¶ÖF6‚æVæB‚“¥ÒæÇ7G&—‚Ğ Ğ Ğ¦FVb&W—%öÖ&¶F÷våö÷WGWB†Ö&¶F÷vâÂW&ÂÂF—FÆRÂ6fr“ Ğ¢""$6²F†R6öæf–wW&VBÖöFVÂöæ6RFò&W—"7G'V7GW&Rv—F†÷WB&RÖfWF6†–ærâ"" Ğ¢–bÆVâ†Ö&¶F÷vâ’âÔ…õ$U•%ô”åUEô4„%3 Ğ¢&—6R'VçF–ÖTW'&÷"‚.jŠYè¾‹é>X{®‹ø~™[şûÈÎizk9^ZèXZhš~ŠÎjÎ[ÈşKúîZHÒ"Ğ¢7—7FVÕ÷&ö×BÒ€Ğ¢.KÚiŠşKˆYÒÖ&¶F÷vâjÎ[ÈşKúîZHŞYš8.KùŞyY‹é>XZ^KŠŞy¨NKŠŞih~Šùih~Xh^ZëKˆîKúhşûÈÎKˆŞŠhXŠXxşjÚ>ih~ûÈÂ Ğ¢.Xú®KúîZHŞih~j>{¹>ièN8.‹é>X{®[ø^š¾y»Nhê^KºRÒÒÒ[ÈZKNûÈÎKˆŞŠhKº>zY»Njş8Šz>˜x®h‰nX˜ŞŠˆ8" Ğ¢²Tå$”4„ÔTåEõ%TÄU2°Ğ¢&g&öçFÖGFW"Xú®KùŞyY’F—FÆ^8V&Æ—6†VEöN8WF†÷'>87VÖÖ'8Fw>ûÉ² Ğ¢.KˆŞŠhyIşh‰'F–6ÆUö¶W86÷W&6^86öÆÆV7FVEöN8&ö6W76VEöBh‰bFF^8" Ğ¢Ğ¢W6W%÷&ö×BÒ€Ğ¢b.š^™Ú"U$ÎûÈK¸^Ké¾jÎ[ÈşKúîZHŞKˆ®Kˆ¾ih~ûÈ“¢·W&ÇÕÆâ Ğ¢b.KšnzÛîj~š)ƒ¢·F—FÆWÕÆâ Ğ¢.‹ª¾K»Ş8iÚ^k©Y(Îi{n™{NZÙ~jë^KÉ®yKiÊÎiË®YÊKúîZHŞYîXiXZ^8%ÆåÆâ Ğ¢.Kˆ¾™Ú.iŠşKˆjÊjŠYè¾yIşh‰y¨NŠùih~ûÈÎKØnZè>y¨Nih~j>{¹>ièNKˆŞzÊnYŠhk.8" Ğ¢.Šû~KùŞyYXZih~[›nKúîZHŞK‹®ZèÎi[BÖ&¶F÷vîûÉ¥ÆåÆâ Ğ¢²Ö&¶F÷vàĞ¢Ğ Ğ¢–b6fu²'&÷f–FW"%ÒÓÒ&FVW6VV²# Ğ¢–ÆöBÒ°Ğ¢&ÖöFVÂ#¢6fu²&ÖöFVÂ%ÒÀĞ¢&ÖW76vW2#¢°Ğ¢²'&öÆR#¢'7—7FVÒ"Â&6öçFVçB#¢7—7FVÕ÷&ö×GÒÀĞ¢²'&öÆR#¢'W6W""Â&6öçFVçB#¢W6W%÷&ö×GÒÀĞ¢ÒÀĞ¢&Ö…÷Fö¶Vç2#¢Ô…ôDTU4TTµôõUEUEõDô´Tå2ÀĞ¢'7G&VÒ#¢fÇ6RÀĞ¢'FV×W&GW&R#¢ÀĞ¢ĞĞ¢–b6fu²&ÖöFVÂ%Òç7F'G7v—F‚‚&FVW6VV²×cB"“ Ğ¢–ÆöE²'F†–æ¶–ær%ÒÒ²'G—R#¢&F—6&ÆVB'ĞĞ¢&W7ÒFVW6VVµ÷&WVW7B‚"ö6†Bö6ö×ÆWF–öç2"Â–ÆöBÂ6frĞ¢6†ö–6RÒ‡&W7ævWB‚&6†ö–6W2"’÷"··ÕÒ•³ĞĞ¢&W—&VBÒ‚†6†ö–6RævWB‚&ÖW76vR"’÷"·Ò’ævWB‚&6öçFVçB"’÷"""’ç7G&—‚Ğ¢–bæ÷B&W—&VC Ğ¢&—6R'VçF–ÖTW'&÷"‚$FVW6VV²jÎ[ÈşKúîZHŞY8Ş[©NK‹®z›¢"Ğ¢–b6†ö–6RævWB‚&f–æ—6…÷&V6öâ"’ÓÒ&ÆVæwF‚# Ğ¢&—6R'VçF–ÖTW'&÷"‚.jÎ[ÈşKúîZHŞ‹é>X{®‹h^X{®Kˆ®™™"Ğ¢&WGW&â&W—&V@Ğ Ğ¢–b6fu²'&÷f–FW"%ÒÓÒ&çF‡&÷–2# Ğ¢&W7ÒçF‡&÷–5÷&WVW7B‚"÷cöÖW76vW2"Â°Ğ¢&ÖöFVÂ#¢6fu²&ÖöFVÂ%ÒÀĞ¢&Ö…÷Fö¶Vç2#¢Ô…õDô´Tå2ÀĞ¢'7—7FVÒ#¢7—7FVÕ÷&ö×BÀĞ¢&ÖW76vW2#¢·²'&öÆR#¢'W6W""Â&6öçFVçB#¢W6W%÷&ö×GÕÒÀĞ¢ÒÂ6frĞ¢–b&W7ævWB‚'7F÷÷&V6öâ"’ÓÒ&Ö…÷Fö¶Vç2# Ğ¢&—6R'VçF–ÖTW'&÷"‚.jÎ[ÈşKúîZHŞ‹é>X{®‹h^X{®Kˆ®™™"Ğ¢&W—&VBÒ%Æâ"æ¦ö–â€Ğ¢&Æö6²ævWB‚'FW‡B"Â""Ğ¢f÷"&Æö6²–â&W7ævWB‚&6öçFVçB"ÂµÒĞ¢–b&Æö6²ævWB‚'G—R"’ÓÒ'FW‡B Ğ¢’ç7G&—‚Ğ¢–bæ÷B&W—&VC Ğ¢&—6R'VçF–ÖTW'&÷"‚$çF‡&÷–2jÎ[ÈşKúîZHŞY8Ş[©NK‹®z›¢"Ğ¢&WGW&â&W—&V@Ğ Ğ¢&—6R'VçF–ÖTW'&÷"†b.KˆŞiJşhÈy¨B’&÷f–FW.ûÉ§¶6fu²w&÷f–FW"u×Ò"Ğ Ğ Ğ¦FVb&V¦V7FVEö÷WGWE÷&Wf–Wr‡FW‡B“ Ğ¢&Wf–WrÒ&Rç7V"‡"%Ç2²"Â""ÂFW‡B’ç7G&—‚Ğ¢&WGW&â&Wf–Wu³¥$T¤T5DTEõ$Ud”Uuô4„%5ĞĞ Ğ Ğ¦FVb&W&UöVç&–6†VEöÖ&¶F÷vâ†Ö&¶F÷vâÂW&ÂÂF—FÆRÂ6fr“ Ğ¢""$æ÷&ÖÆ—¦RÂfÆ–FFRÂæBBÖ÷7Böæ6R&W—"ÖöFVÂ×&öGV6VBFö7VÖVçBâ"" Ğ¢G'“ Ğ¢Fö7VÖVçBÒæ÷&ÖÆ—¦UöÖ&¶F÷våöFö7VÖVçB†Ö&¶F÷vâĞ¢Vç&–6†ÖVçBÒW‡G&7EöVç&–6†ÖVçB†Fö7VÖVçBĞ¢W†6WB'VçF–ÖTW'&÷"2f—'7EöW'&÷# Ğ¢Æör†b.jŠYè¾‹é>X{®jÎ[ÈşKˆŞYŠxNûÈÎhš~ŠÎKˆjÊˆz®XªKúîZHŞûÉ§¶f—'7EöW'&÷'Ò"Ğ¢&W—&VBÒæöæPĞ¢G'“ Ğ¢&W—&VBÒ&W—%öÖ&¶F÷våö÷WGWB†Ö&¶F÷vâÂW&ÂÂF—FÆRÂ6frĞ¢Fö7VÖVçBÒæ÷&ÖÆ—¦UöÖ&¶F÷våöFö7VÖVçB‡&W—&VBĞ¢Vç&–6†ÖVçBÒW‡G&7EöVç&–6†ÖVçB†Fö7VÖVçBĞ¢W†6WBW†6WF–öâ2&W—%öW'&÷# Ğ¢Æör€Ğ¢.jÎ[ÈşKúîZHŞK¸ŞZK‹J^ûÉ¾XéşZx¾‹é>X{®ZèXZš(NŠxûÉ¢ Ğ¢b'·&V¦V7FVEö÷WGWE÷&Wf–Wr†Ö&¶F÷vâ—Ò Ğ¢Ğ¢–b&W—&VC Ğ¢Æör€Ğ¢.jÎ[ÈşKúîZHŞ‹é>X{®ZèXZš(NŠxûÉ¢ Ğ¢b'·&V¦V7FVEö÷WGWE÷&Wf–Wr‡&W—&VB—Ò Ğ¢Ğ¢&—6R'VçF–ÖTW'&÷"†b.jŠYè¾‹é>X{®jÎ[ÈşKúîZHŞZK‹J^ûÉ§·&W—%öW'&÷'Ò"’g&öÒ&W—%öW'&÷ Ğ¢Æör‚.jŠYè¾‹é>X{®jÎ[Èşˆz®XªKúîZHŞh‰X©ò"Ğ¢Fö7VÖVçBÒVç7W&U÷7VÖÖ'•÷6V7F–öâ†Fö7VÖVçBÂVç&–6†ÖVçE²'7VÖÖ'’%ÒĞ¢&WGW&âFö7VÖVçBÂVç&–6†ÖVç@Ğ Ğ Ğ¢2ÓÓÓÓÒ‰Şy¹‚ÓÓÓÓĞĞ Ğ¦FVbW‡G&7E÷F—FÆR†Ö&¶F÷vâÂfÆÆ&6²“ Ğ¢ÒÒ&Rç6V&6‚‡"%çF—FÆS¥Ç2¢‚â²’B"ÂÖ&¶F÷vâÂ&RäÕTÅD”Ä”äRĞ¢F—FÆRÒÒæw&÷Wƒ’ç7G&—‚’ç7G&—‚r%Ârr’–bÒVÇ6RfÆÆ&6°Ğ¢&WGW&âF—FÆR÷"fÆÆ&6°Ğ Ğ Ğ¦FVb6fUöf–ÆVæÖR‡F—FÆR“ Ğ¢æÖRÒ&Rç7V"‡"u²õÅÃ¢£ò#ÃçÅÆåÒrÂ,+r"ÂF—FÆR’ç7G&—‚•³£ƒĞĞ¢&WGW&âæÖR÷"'VçF—FÆVB Ğ Ğ Ğ¦FVb6fUöÖ&¶F÷vâ†Ö&¶F÷vâÂF—FÆRÂ÷WEöF—"“ Ğ¢÷2æÖ¶VF—'2†÷WEöF—"ÂW†—7Eöö³ÕG'VRĞ¢&6RÒ6fUöf–ÆVæÖR‡F—FÆRĞ¢F‚Ò÷2çF‚æ¦ö–â†÷WEöF—"Âb'¶&6WÒæÖB"Ğ¢âÒ Ğ¢v†–ÆR÷2çF‚æW†—7G2‡F‚“ Ğ¢F‚Ò÷2çF‚æ¦ö–â†÷WEöF—"Âb'¶&6WÒ×¶çÒæÖB"Ğ¢â³ÒĞ¢fBÂF×ÒFV×f–ÆRæÖ·7FV×†F—#Ö÷WEöF—"Ğ¢v—F‚÷2æfF÷Vâ†fBÂ'r"ÂVæ6öF–æsÒ'WFbÓ‚"’2c Ğ¢bçw&—FR†Ö&¶F÷vâĞ¢÷2ç&WÆ6R‡F×ÂF‚Ğ¢&WGW&âF€Ğ Ğ Ğ¢2ÓÓÓÓÒ7ööÂZY{ªnûÈKˆîhš[^y¨N{ªnZé®ûÈÎŠxK¹>[©2Fö72öFW6–vâæÖNûÈ“ÓÓÓÓĞĞ Ğ¦FVbw&—FU÷&W÷'B‡&W7VÇG2“ Ğ¢&–BÒ'G&ç6ÆFRÒW2ÒW2"R€Ğ¢F–ÖRç7G&gF–ÖR‚"U’VÒVEBT‚TÒU2"’ÀĞ¢""æ¦ö–â‡&æFöÒæ6†ö–6W2‡7G&–æræ66–•öÆ÷vW&66R²7G&–æræF–v—G2Â³ÓB’’ÀĞ¢Ğ¢FöÖ–5÷w&—FUö§6öâ†÷2çF‚æ¦ö–â„”ä$õ…ôD•"Â&–B²"æ§6öâ"’Â°Ğ¢'&W÷'D–B#¢&–BÀĞ¢'&ö6W76–æuG—R#¢'G&ç6ÆFR"ÀĞ¢'&W7VÇG2#¢&W7VÇG2ÀĞ¢ÒĞ¢&WGW&â&–@Ğ Ğ Ğ¦FVbWFFU÷7FGW2‡F6‚“ Ğ¢7FGW2ÒÆöEö§6öâ…5DEU5ôd”ÄRÂ·ÒĞ¢7FGW2çWFFR‡F6‚Ğ¢FöÖ–5÷w&—FUö§6öâ…5DEU5ôd”ÄRÂ7FGW2Ğ Ğ Ğ¦FVb7V—&UöÆö6²‚“ Ğ¢&WGW&â7V—&Uöf–ÆUöÆö6²„Äô4µôd”ÄRĞ Ğ Ğ¢2ÓÓÓÓÒˆz®j8ÓÓÓÓĞĞ Ğ¦FVb'Våö6†V6²‚“ Ğ¢&–çB‚#ÓÒ–æfò6öÆÆV7F÷"{û¾ŠùkXˆz®j8ÓÒ"Ğ¢ö²ÒG'VPĞ¢6frÒÆöEö6öæf–r‚Ğ¢–bæ÷B÷2çF‚æW†—7G2„4ôäd”uôd”ÄR“ Ğ¢6WGWöæÖRÒ'67&—G2÷6WGWç3"–b÷2ææÖRÓÒ&çB"VÇ6R'67&—G2÷6WGWç6‚ Ğ¢&–çB†b.)ÉR˜XŞ{Úîih~K»nKˆŞZÙYÊûÉ§´4ôäd”uôd”ÄWŞûÈ‹ùŠÂ·6WGWöæÖWŞûÈ’"Ğ¢ö²ÒfÇ6PĞ¢VÆ–b6öæf–uöW'&÷"†6fr“ Ğ¢&–çB†b.)ÉR¶6öæf–uöW'&÷"†6fr—ŞûÉ§´4ôäd”uôd”ÄWÒ"Ğ¢ö²ÒfÇ6PĞ¢VÇ6S Ğ¢G'“ Ğ¢6†V6µö•ö¶W’†6frĞ¢&–çB†b.)É2’¶W’iÈiXûÈ‡¶6fu²w&÷f–FW"u×Òò¶6fu²vÖöFVÂu×ŞûÈ’"Ğ¢W†6WBW†6WF–öâ2S Ğ¢&–çB†b.)ÉR’¶W’š¨ÎŠøZK‹J^ûÉ§¶WÒ"Ğ¢ö²ÒfÇ6PĞ¢÷WEöF—"Ò÷2çF‚æW‡æGW6W"†6fu²&÷WGWDF—"%ÒĞ¢G'“ Ğ¢÷2æÖ¶VF—'2†÷WEöF—"ÂW†—7Eöö³ÕG'VRĞ¢&–çB†b.)É2‹é>X{®yºî[Ù^XúşXiûÉ§¶÷WEöF—'Ò"Ğ¢W†6WBõ4W'&÷"2S Ğ¢&–çB†b.)ÉR‹é>X{®yºî[Ù^KˆŞXúşXiûÉ§¶WÒ"Ğ¢ö²ÒfÇ6PĞ¢–b÷2çF‚æW†—7G2„õUD$õ…ôd”ÄR“ Ğ¢âÒÆVâ†ÆöEö§6öâ„õUD$õ…ôd”ÄRÂ·Ò’ævWB‚&'F–6ÆW2"’÷"µÒĞ¢&–çB†b.)É2÷WF&÷‚ZÙYÊûÈÎ[Ù>X˜Ş[è^ZHNyb¶çÒzør"Ğ¢VÇ6S Ğ¢&–çB‚.)k2÷WF&÷‚‹ùKˆŞZÙYÊ(	N(	Nhš[^Š8^Z[Ş[›nZèÎh‰šinjÊ8Îj^hê^YÎjÚ^8ŞYîKÉ®ˆz®XªyIşh‰"Ğ¢&–çB‚#ÓÒˆz®j8"²‚.˜	®‹ør"–bö²VÇ6R.iÊ®˜	®‹ør"’²"ÓÒ"Ğ¢&WGW&â–bö²VÇ6RĞ Ğ Ğ¢2ÓÓÓÓÒK‹¾kXzˆ²ÓÓÓÓĞĞ Ğ¦FVbÖ–â‚“ Ğ¢6öæf–wW&U÷FW‡E÷7FF–ò‚Ğ¢–b"ÒÖ6†V6²"–â7—2æ&wc Ğ¢7—2æW†—B‡'Våö6†V6²‚’Ğ Ğ¢Æör‚#Ò"¢SĞ¢Æör†b.[ÈZx¾[zj8{û¾Šù™‰şX‰~ûÈ‡µE$”ttU'ŞûÈ’"Ğ Ğ¢6frÒÆöEö6öæf–r‚Ğ¢–bæ÷B6öæf–uöö²†6fr“ Ğ¢6WGWöæÖRÒ'6WGWç3"–b÷2ææÖRÓÒ&çB"VÇ6R'6WGWç6‚ Ğ¢Æör†b.)ØÂ¶6öæf–uöW'&÷"†6fr—ŞûÈÎ‹{>‹ø~ûÈ{Én‹éâòæ–æfòÖ6öÆÆV7F÷"ö6öæf–ræ§6öâh‰n˜xŞ‹y·6WGWöæÖWŞûÈ’"Ğ¢&WGW&àĞ¢Æör†b.KÛşyJ{û¾Šù[É^i8îûÉ§¶6fu²w&÷f–FW"u×Òò¶6fu²vÖöFVÂu×Ò"Ğ Ğ¢Æö6µöfBÒ7V—&UöÆö6²‚Ğ¢–bÆö6µöfB—2æöæS Ğ¢Æör‚.XúniÈ‹ù¾zˆ¾YÊ‹ùŠÎûÈÎ‹{>‹ør"Ğ¢&WGW&àĞ Ğ¢Æ7E÷'VâÒ²'7F'FVDB#¢F–ÖRç7G&gF–ÖR‚"U’ÒVÒÒVEBTƒ¢TÓ¢U2W¢"’Â'G&–vvW"#¢E$”ttU"Â&÷WF6öÖR#¢''Vææ–ær'ĞĞ¢F6‚Ò²&Æ7E'Vâ#¢Æ7E÷'VçĞĞ¢–bE$”ttU"ÓÒ'66†VGVÆVB# Ğ¢F6…²&Æ7E66†VGVÆVE7F'DB%ÒÒÆ7E÷'Vå²'7F'FVDB%ĞĞ¢WFFU÷7FGW2‡F6‚Ğ Ğ¢FVbf–æ—6‚†÷WF6öÖRÂ¢¦W‡G&“ Ğ¢Æ7E÷'VâçWFFR‡²&÷WF6öÖR#¢÷WF6öÖRÂ&f–æ—6†VDB#¢F–ÖRç7G&gF–ÖR‚"U’ÒVÒÒVEBTƒ¢TÓ¢U2W¢"’Â¢¦W‡G&ÒĞ¢WFFU÷7FGW2‡²&Æ7E'Vâ#¢Æ7E÷'VçÒĞ Ğ¢G'“ Ğ¢–bæ÷B÷2çF‚æW†—7G2„õUD$õ…ôd”ÄR“ Ğ¢Æör‚&÷WF&÷‚KˆŞZÙYÊ(	N(	Nhš[^[	®iÊ®ZèÎh‰šinjÊj^hê^ûÈÎ‹{>‹ør"Ğ¢f–æ—6‚‚&æòÖ÷WF&÷‚"Ğ¢&WGW&àĞ¢'F–6ÆW2ÒÆöEö§6öâ„õUD$õ…ôd”ÄRÂ·Ò’ævWB‚&'F–6ÆW2"’÷"µĞĞ¢7FFRÒÆöEö§6öâ…5DDUôd”ÄRÂ·ÒĞ¢VÆ–v–&ÆRÒ°¢f÷"–â'F–6ÆW0¢–bævWB‚'W&Â"’æBævWB‚&'F–6ÆT¶W’"’æ÷B–â7FFRæBævWB‚'W&Â"’æ÷B–â7FFP¢Ğ¢VæF–ærÒVÆ–v–&ÆU³¦6fu²&Ö„'F–6ÆW5W%'Vâ%ÕĞ¢Æör†b&÷WF&÷‚X[¶ÆVâ†'F–6ÆW2—ÒiÚûÈÎX[nKŠÒ¶ÆVâ‡VæF–ær—ÒiÚiÊ®hª^Y¢"¢–bÆVâ†VÆ–v–&ÆR’âÆVâ‡VæF–ær“ ¢Æör†b.h‰iÊÎ™{™zûÉ®iÊÎjÊiÈZI®ZHNyb¶6fu²vÖ„'F–6ÆW5W%'Vâu×Òzø~ûÈÎ[»nYâ¶ÆVâ†VÆ–v–&ÆR’ÒÆVâ‡VæF–ær—Òzør"¢–bæ÷BVæF–æs Ğ¢Æör‚.)ÈRiz™È{û¾Šù"Ğ¢f–æ—6‚‚&V×G’"Ğ¢&WGW&àĞ Ğ¢2ŠêNš(nhª^Y®ûÉ®hš[^i‹îzK®8ÎZHNynKŠŞ8ŞûÉ¾iÊÎ‹ù¾zˆ¾[Jk¨>X‰ˆz®XªY¹î˜VæF–æpĞ¢W&Ç2Ò¶²'W&Â%Òf÷"–âVæF–æuĞ¢6Æ–Õ÷&–BÒw&—FU÷&W÷'B…°¢²&'F–6ÆT¶W’#¢ævWB‚&'F–6ÆT¶W’"’Â'W&Â#¢²'W&Â%ÒÂ'7FGW2#¢'&ö6W76–ær'Ğ¢f÷"–âVæF–æp¢Ò¢Æör†b/	ù8Â[{.ŠêNš(b¶ÆVâ‡W&Ç2—Òzø~ûÈ‡¶6Æ–Õ÷&–GŞûÈ’"Ğ Ğ¢÷WEöF—"Ò÷2çF‚æW‡æGW6W"†6fu²&÷WGWDF—"%ÒĞ¢&W7VÇG2ÒµĞĞ¢FöæRÒ ¢f÷"–âVæF–æs ¢W&ÂÂF—FÆRÒ²'W&Â%ÒÂævWB‚'F—FÆR"Â#ò"¢'F–6ÆU÷7F'FVBÒF–ÖRæÖöæ÷Föæ–2‚¢Æör†b/	øÉ{û¾ŠùKŠÓ¢·F—FÆWÒ"¢G'“ Ğ¢ÖBÒG&ç6ÆFUö'F–6ÆR€¢W&ÂÀ¢F—FÆRÀ¢6frÀ¢6GW&Uöf–ÆSÖævWB‚&6GW&Tf–ÆR"’À¢'F–6ÆUö¶W“ÖævWB‚&'F–6ÆT¶W’"’À¢¢ÖBÂVç&–6†ÖVçBÒ&W&UöVç&–6†VEöÖ&¶F÷vâ†ÖBÂW&ÂÂF—FÆRÂ6frĞ¢æ÷u÷WF2ÒF–ÖRç7G&gF–ÖR‚"U’ÒVÒÒVEBTƒ¢TÓ¢U5¢"ÂF–ÖRæv×F–ÖR‚’Ğ¢ÖBÒf–æÆ—¦UöFWFW&Ö–æ—7F–5öÖWFFF†ÖBÂÂæ÷u÷WF2Ğ¢G&ç6ÆFVE÷F—FÆRÒW‡G&7E÷F—FÆR†ÖBÂF—FÆRĞ¢F‚Ò6fUöÖ&¶F÷vâ†ÖBÂG&ç6ÆFVE÷F—FÆRÂ÷WEöF—"Ğ¢&W7VÇEöÖWFÒ°¢'6fVEFò#¢F‚À¢'F—FÆR#¢G&ç6ÆFVE÷F—FÆRÀ¢'&÷f–FW"#¢6fu²'&÷f–FW"%ÒÀ¢&GW&F–öä×2#¢&÷VæB‚‡F–ÖRæÖöæ÷Föæ–2‚’Ò'F–6ÆU÷7F'FVB’¢’À¢¢¦Vç&–6†ÖVçBÀ¢Ğ¢6öçFVçE÷7FGW2Òg&öçFÖGFW%÷66Æ"†ÖBÂ&6öçFVçE÷7FGW2"Ğ¢–b6öçFVçE÷7FGW3 Ğ¢&W7VÇEöÖWF²&6öçFVçE7FGW2%ÒÒ6öçFVçE÷7FGW0Ğ¢&W7VÇG2æVæB‡²&'F–6ÆT¶W’#¢ævWB‚&'F–6ÆT¶W’"’Â'W&Â#¢W&ÂÂ'7FGW2#¢&FöæR"Â'&ö6W76VDB#¢æ÷u÷WF2ÀĞ¢&ÖWF#¢&W7VÇEöÖWFÒĞ¢7FFU¶ævWB‚&'F–6ÆT¶W’"’÷"W&ÅÒÒæ÷u÷WF0Ğ¢FöæR³ÒĞ¢Æör†b")ÈR[{.KùŞZÙƒ¢·F‡Ò"Ğ¢W†6WBW†6WF–öâ2S ¢æ÷u÷WF2ÒF–ÖRç7G&gF–ÖR‚"U’ÒVÒÒVEBTƒ¢TÓ¢U5¢"ÂF–ÖRæv×F–ÖR‚’¢W'"Ò7G"†R•³£3Ğ¢–b—6–ç7Fæ6R†RÂ—VÆ–æTW'&÷"“ ¢f–ÇW&UöÖWFÒRç&W÷'EöÖWF‚¢VÇ6S ¢f–ÇW&UöÖWFÒ°¢&W'&÷"#¢W'"À¢&6öFR#¢'—VÆ–æU÷VæW‡V7FVB"À¢'7FvR#¢'—VÆ–æR"À¢'&WG'–&ÆR#¢G'VRÀ¢&÷W&F÷$7F–öâ#¢&–ç7V7EöÆöw2"À¢Ğ¢f–ÇW&UöÖWF²'&÷f–FW"%ÒÒ6fu²'&÷f–FW"%Ğ¢f–ÇW&UöÖWF²&GW&F–öä×2%ÒÒ&÷VæB‚‡F–ÖRæÖöæ÷Föæ–2‚’Ò'F–6ÆU÷7F'FVB’¢¢&W7VÇG2æVæB‡²&'F–6ÆT¶W’#¢ævWB‚&'F–6ÆT¶W’"’Â'W&Â#¢W&ÂÂ'7FGW2#¢&f–ÆVB"Â'&ö6W76VDB#¢æ÷u÷WF2À¢&ÖWF#¢f–ÇW&UöÖWFÒ¢Æör†b")ØÂZK‹JS¢¶W''Ò"Ğ Ğ¢&–BÒw&—FU÷&W÷'B‡&W7VÇG2Ğ¢FöÖ–5÷w&—FUö§6öâ…5DDUôd”ÄRÂ7FFRĞ¢Æör†b.ZèÎh‰¶FöæWÒ÷¶ÆVâ‡VæF–ær—Òzø~ûÈÎhª^Y®[{.XiXZR–æ&÷ƒ¢·&–GÒ"Ğ¢f–æ—6‚‚'7V66W72"–bFöæRÓÒÆVâ‡VæF–ær’VÇ6R&f–ÆVB"ÀĞ¢6÷VçCÖFöæRÂ&W÷'D–C×&–BĞ Ğ¢W†6WBW†6WF–öâ2S Ğ¢f–æ—6‚‚&W'&÷""ÂW'&÷#×7G"†R•³£3ÒĞ¢&—6PĞ¢f–æÆÇ“ Ğ¢&VÆV6UöÆö6²†Æö6µöfBĞ Ğ Ğ¦–bõöæÖUõòÓÒ%õöÖ–åõò# Ğ¢Ö–â‚Ğ
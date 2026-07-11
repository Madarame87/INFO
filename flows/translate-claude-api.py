#!/usr/bin/env python3
"""
通用翻译流（translate）：支持 DeepSeek API 或 Anthropic API，无任何第三方依赖。
1. 读 ~/.info-collector/outbox/translate.json（Info Collector 扩展导出）
2. 逐篇抓取原文并调 LLM API 翻译成中文 Markdown
3. 译文存到配置的输出目录，结果写成 Completion Report 放进 inbox/

配置文件 ~/.info-collector/config.json：
  { "provider": "deepseek", "apiKey": "sk-...", "model": "deepseek-v4-flash",
    "outputDir": "~/Documents/InfoCollector" }

用法：
  translate-flow.py            定时运行（launchd）
  translate-flow.py --manual   手动触发（Dashboard「立即处理」）
  translate-flow.py --check    自检：配置、目录、API Key 有效性，不翻译
"""

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    from info_collector_platform import acquire_lock as acquire_file_lock
    from info_collector_platform import release_lock, user_home
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from info_collector_platform import acquire_lock as acquire_file_lock
    from info_collector_platform import release_lock, user_home


HOME = user_home()
SPOOL = str(HOME / ".info-collector")
CONFIG_FILE = os.path.join(SPOOL, "config.json")
OUTBOX_FILE = os.path.join(SPOOL, "outbox", "translate.json")
INBOX_DIR = os.path.join(SPOOL, "inbox")
STATE_FILE = os.path.join(SPOOL, "state", "translate-reported.json")
STATUS_FILE = os.path.join(SPOOL, "state", "translate-status.json")
LOCK_FILE = os.path.join(SPOOL, "state", "translate.lock")
LOG_FILE = os.path.join(SPOOL, "state", "translate-flow.log")

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
MAX_TOKENS = 16000          # 非流式安全上限；超长文章会报 failed
REQUEST_TIMEOUT = 900       # 单篇翻译最长等待（秒）
MAX_CONTINUATIONS = 4       # 服务端工具 pause_turn 续跑次数上限
FETCH_TIMEOUT = 45
DEFUDDLE_TIMEOUT = 90
MAX_FETCH_BYTES = 2_000_000
MAX_DEEPSEEK_INPUT_CHARS = 180_000
MAX_REPAIR_INPUT_CHARS = 180_000
REJECTED_PREVIEW_CHARS = 500
MAX_SUMMARY_CHARS = 240
MAX_TAGS = 5

CANONICAL_TAGS = (
    "人工智能", "世界模型", "机器人", "具身智能", "大模型", "智能体", "多模态",
    "模型评估", "记忆系统", "推理", "训练", "数据", "芯片", "开源", "产品",
    "产业动态", "学术研究",
)

ENRICHMENT_RULES = (
    "除翻译外，还要完成信息提炼：frontmatter 必须包含一行 summary，"
    "用 80-160 个简体中文字符概括文章的核心事实或主张；必须包含一行 tags，"
    "格式严格为 JSON 风格数组，例如 tags: [\"智能体\", \"模型评估\"]。"
    "给出 2-5 个简短标签，优先复用以下规范标签："
    + "、".join(CANONICAL_TAGS)
    + "。确有必要时才创建新标签。frontmatter 后、完整译文前加入「## 摘要」小节，"
      "正文使用与 summary 相同的摘要。"
)

TRIGGER = "manual" if "--manual" in sys.argv else "scheduled"

SYSTEM_PROMPT = (
    "你是一名专业译者。用 web_fetch 工具抓取给定 URL 的文章，"
    "把正文完整翻译成自然通顺的简体中文 Markdown。规则："
    "代码块、命令、路径原样保留不翻译；图片保留原远程链接；"
    "文章主标题用「中文（English）」双语形式。"
    + ENRICHMENT_RULES +
    "你的最终回复必须只包含完成的 Markdown 文档本身"
    "（以 --- 开头的 YAML frontmatter 开始），"
    "不要有任何解释、前言或代码围栏。"
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
    cfg.setdefault("outputDir", str(HOME / "Documents" / "InfoCollector"))
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


def config_error(cfg):
    key = cfg.get("apiKey") or ""
    provider = cfg.get("provider")
    if provider not in PROVIDER_DEFAULTS:
        return f"不支持的 API provider：{provider}（可选 deepseek 或 anthropic）"
    if len(key) <= 20:
        return "API Key 未配置或过短"
    if provider == "anthropic" and not key.startswith("sk-ant-"):
        return "Anthropic API Key 应以 sk-ant- 开头"
    if provider == "deepseek" and not key.startswith("sk-"):
        return "DeepSeek API Key 通常以 sk- 开头"
    return None


def config_ok(cfg):
    return config_error(cfg) is None


# ===== API（标准库 raw HTTP）=====

def post_json(url, payload, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"API {e.code}: {body}") from e


def anthropic_request(path, payload, cfg):
    return post_json(
        f"{cfg['baseUrl']}{path}",
        payload,
        {
            "x-api-key": cfg["apiKey"],
            "anthropic-version": API_VERSION,
        },
    )


def deepseek_request(path, payload, cfg):
    return post_json(
        f"{cfg['baseUrl']}{path}",
        payload,
        {"authorization": f"Bearer {cfg['apiKey']}"},
    )


def check_api_key(cfg):
    """验证 API Key。Anthropic 用 count_tokens；DeepSeek 用一次极小 chat 请求。"""
    if cfg["provider"] == "anthropic":
        anthropic_request("/v1/messages/count_tokens", {
            "model": cfg["model"],
            "messages": [{"role": "user", "content": "ping"}],
        }, cfg)
        return
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "stream": False,
    }
    if cfg["model"].startswith("deepseek-v4"):
        payload["thinking"] = {"type": "disabled"}
    resp = deepseek_request("/chat/completions", payload, cfg)
    if not resp.get("choices"):
        raise RuntimeError("DeepSeek 响应中没有 choices")


def translate_article(url, title, cfg):
    """翻译一篇文章，返回 Markdown 文本。失败抛 RuntimeError。"""
    if cfg["provider"] == "anthropic":
        return translate_article_anthropic(url, title, cfg)
    if cfg["provider"] == "deepseek":
        return translate_article_deepseek(url, title, cfg)
    raise RuntimeError(f"不支持的 API provider：{cfg['provider']}")


def translate_article_anthropic(url, title, cfg):
    """翻译一篇文章，返回 Markdown 文本。失败抛 RuntimeError。"""
    now_local = time.strftime("%Y-%m-%dT%H:%M")
    user_prompt = (
        f"翻译这篇文章：{url}\n\n"
        f"frontmatter 需包含：title（中文标题）、source（原文 URL）、"
        f"published（原文发布日期，YYYY-MM-DD，找不到就留空）、"
        f"date: {now_local}（收录时间，原样使用这个值）、"
        f"authors（作者，找不到就留空）、summary 和 tags。"
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
        resp = anthropic_request("/v1/messages", payload, cfg)
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


class ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in {"p", "div", "section", "article", "header", "footer", "br",
                   "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
                   "pre"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if not self.skip_depth and tag in {"p", "div", "section", "article", "li",
                                           "h1", "h2", "h3", "h4", "h5", "h6",
                                           "blockquote", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self):
        raw = " ".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_author(meta):
    for item in meta.get("schemaOrgData") or []:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        if isinstance(author, dict) and author.get("name"):
            return author["name"]
        if isinstance(author, list):
            names = [a.get("name") for a in author if isinstance(a, dict) and a.get("name")]
            if names:
                return ", ".join(names)
    return meta.get("author") or ""


def content_from_defuddle(meta):
    for key in ("markdown", "content", "text", "article"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    html = meta.get("html")
    if isinstance(html, str) and html.strip():
        parser = ArticleHTMLParser()
        parser.feed(html)
        return parser.text()
    return ""


def fetch_article_with_defuddle(url):
    if os.environ.get("INFO_COLLECTOR_DISABLE_DEFUDDLE"):
        return None
    exe = shutil.which("defuddle")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "parse", url, "--json"],
            capture_output=True,
            text=True,
            timeout=DEFUDDLE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"defuddle 不可用，改用内置抓取器: {e}")
        return None
    if proc.returncode != 0:
        log(f"defuddle 抓取失败，改用内置抓取器: {proc.stderr[:300]}")
        return None
    try:
        meta = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        log(f"defuddle 输出不是 JSON，改用内置抓取器: {e}")
        return None
    content = content_from_defuddle(meta)
    if len(content) < 80:
        log("defuddle 抓取到的正文太短，改用内置抓取器")
        return None
    return {
        "content": content,
        "title": meta.get("title") or "",
        "published": meta.get("published") or meta.get("date") or "",
        "authors": extract_author(meta),
        "extractor": "defuddle",
    }


def fetch_article_with_builtin(url):
    req = urllib.request.Request(
        url,
        headers={
            "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0 Safari/537.36 InfoCollector/1.0"),
            "accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            content_type = resp.headers.get("content-type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(MAX_FETCH_BYTES + 1)
    except urllib.error.HTTPError as e:
        body = e.read(200).decode("utf-8", errors="replace")
        raise RuntimeError(f"抓取原文失败 HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"抓取原文失败: {e}") from e

    if len(raw) > MAX_FETCH_BYTES:
        raise RuntimeError("原文页面过大，超过本地抓取上限")

    text = raw.decode(charset, errors="replace")
    if "html" in content_type.lower() or re.search(r"<html|<article|<body", text, re.I):
        parser = ArticleHTMLParser()
        parser.feed(text)
        text = parser.text()
    else:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) < 80:
        raise RuntimeError("抓取到的正文太短，网站可能需要登录或阻止抓取")
    return {"content": text, "title": "", "published": "", "authors": "", "extractor": "builtin"}


def fetch_article_source(url):
    return fetch_article_with_defuddle(url) or fetch_article_with_builtin(url)


def translate_article_deepseek(url, title, cfg):
    now_local = time.strftime("%Y-%m-%dT%H:%M")
    article = fetch_article_source(url)
    article_text = article["content"]
    truncated = ""
    if len(article_text) > MAX_DEEPSEEK_INPUT_CHARS:
        article_text = article_text[:MAX_DEEPSEEK_INPUT_CHARS]
        truncated = "\n\n注意：原文很长，以下文本已按本地输入上限截断。"

    system_prompt = (
        "你是一名专业译者。用户会提供从网页抓取出的文章正文。"
        "请把正文完整翻译成自然通顺的简体中文 Markdown。规则："
        "代码块、命令、路径原样保留不翻译；图片链接如正文中出现则保留；"
        "文章主标题用「中文（English）」双语形式。"
        + ENRICHMENT_RULES +
        "你的最终回复必须只包含完成的 Markdown 文档本身"
        "（以 --- 开头的 YAML frontmatter 开始），"
        "不要有任何解释、前言或代码围栏。"
    )
    user_prompt = (
        f"来源 URL: {url}\n"
        f"书签标题: {title}\n\n"
        f"正文提取器: {article['extractor']}\n"
        f"原文标题: {article['title']}\n"
        f"原文发布日期: {article['published']}\n"
        f"作者: {article['authors']}\n\n"
        f"frontmatter 需包含：title（中文标题）、source（原文 URL）、"
        f"published（优先使用上面的原文发布日期，YYYY-MM-DD，找不到就留空）、"
        f"date: {now_local}（收录时间，原样使用这个值）、"
        f"authors（优先使用上面的作者，找不到就留空）、summary 和 tags。{truncated}\n\n"
        f"原文提取文本：\n\n{article_text}"
    )
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "temperature": 0.2,
    }
    if cfg["model"].startswith("deepseek-v4"):
        payload["thinking"] = {"type": "disabled"}
    resp = deepseek_request("/chat/completions", payload, cfg)
    choice = (resp.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    if not text:
        reason = choice.get("finish_reason") or "unknown"
        raise RuntimeError(f"DeepSeek 响应中没有文本内容（finish_reason={reason}）")
    if choice.get("finish_reason") == "length":
        raise RuntimeError("译文超出输出上限，文章可能过长")
    return strip_code_fence(text)


def strip_code_fence(text):
    text = text.lstrip("\ufeff").strip()
    match = re.match(
        r"\A```(?:markdown|md|yaml)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*\Z",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else text


def normalize_markdown_document(text):
    """Return a document beginning with real YAML, tolerating model wrappers."""
    text = strip_code_fence(text)
    separators = list(re.finditer(r"(?m)^---[ \t]*\r?$", text))

    # Some models emit a valid opening delimiter and all required fields, then
    # jump directly to "## 摘要" without the closing delimiter. This is fully
    # repairable locally and should not discard the translation or spend a
    # second API request.
    if len(separators) == 1:
        start = separators[0]
        tail = text[start.end():]
        body_heading = re.search(r"(?m)^#{1,6}[ \t]+\S", tail)
        if body_heading:
            header = tail[:body_heading.start()]
            required = ("title", "source", "summary", "tags")
            if all(re.search(rf"(?m)^{field}:\s*", header) for field in required):
                prefix = text[:start.start()]
                has_outer_fence = bool(re.search(
                    r"```(?:markdown|md|yaml)?[ \t]*\r?\n[ \t]*\Z",
                    prefix,
                    re.IGNORECASE,
                ))
                body = tail[body_heading.start():].strip()
                if has_outer_fence:
                    body = re.sub(r"\r?\n```[ \t]*\Z", "", body).strip()
                return "---\n" + header.strip("\r\n") + "\n---\n\n" + body

    for index in range(len(separators) - 1):
        start = separators[index]
        end = separators[index + 1]
        header = text[start.end():end.start()]
        if not re.search(r"(?m)^title:\s*", header):
            continue
        if not re.search(r"(?m)^source:\s*", header):
            continue
        prefix = text[:start.start()]
        has_outer_fence = bool(re.search(
            r"```(?:markdown|md|yaml)?[ \t]*\r?\n[ \t]*\Z",
            prefix,
            re.IGNORECASE,
        ))
        document = text[start.start():].strip()
        # Strip the trailing fence only when the discarded prefix contained
        # the matching outer fence; a real article may legitimately end in a
        # code block whose closing fence must be preserved.
        if has_outer_fence:
            document = re.sub(r"\r?\n```[ \t]*\Z", "", document).strip()
        return document
    raise RuntimeError("译文缺少 YAML frontmatter")


TAG_ALIASES = {
    "ai": "人工智能",
    "artificial intelligence": "人工智能",
    "llm": "大模型",
    "llms": "大模型",
    "large language model": "大模型",
    "large language models": "大模型",
    "大语言模型": "大模型",
    "agent": "智能体",
    "agents": "智能体",
    "ai agent": "智能体",
    "ai agents": "智能体",
    "eval": "模型评估",
    "evals": "模型评估",
    "evaluation": "模型评估",
    "model evaluation": "模型评估",
    "memory": "记忆系统",
    "memory system": "记忆系统",
    "memory systems": "记忆系统",
    "robotics": "机器人",
    "embodied ai": "具身智能",
    "world model": "世界模型",
    "world models": "世界模型",
}


def parse_frontmatter_scalar(raw):
    raw = raw.strip()
    if not raw:
        return ""
    try:
        value = json.loads(raw)
        return value if isinstance(value, str) else str(value)
    except json.JSONDecodeError:
        return raw.strip("'\"")


def normalize_tag(tag):
    tag = re.sub(r"\s+", " ", str(tag)).strip().lstrip("#＃").strip()
    tag = TAG_ALIASES.get(tag.casefold(), tag)
    return tag[:24].strip()


def extract_enrichment(markdown):
    """Extract the bounded Summary/Tags contract from Markdown frontmatter."""
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", markdown, re.DOTALL)
    if not match:
        raise RuntimeError("译文缺少 YAML frontmatter")
    frontmatter = match.group(1)

    summary_match = re.search(r"(?m)^summary:\s*(.*)$", frontmatter)
    summary = parse_frontmatter_scalar(summary_match.group(1)) if summary_match else ""
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    if not summary:
        raise RuntimeError("译文 frontmatter 缺少 summary")

    tags = []
    tags_match = re.search(r"(?m)^tags:\s*(.*)$", frontmatter)
    if tags_match:
        raw_tags = tags_match.group(1).strip()
        if raw_tags:
            try:
                parsed = json.loads(raw_tags)
                tags = parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                tags = [part.strip(" '\"") for part in re.split(r"[,，]", raw_tags.strip("[]"))]
        else:
            tail = frontmatter[tags_match.end():]
            tags = re.findall(r"(?m)^\s*-\s*(.+?)\s*$", tail)

    normalized = []
    seen = set()
    for tag in tags:
        clean = normalize_tag(tag)
        key = clean.casefold()
        if clean and key not in seen:
            normalized.append(clean)
            seen.add(key)
        if len(normalized) == MAX_TAGS:
            break
    if len(normalized) < 2:
        raise RuntimeError("译文 frontmatter 至少需要 2 个有效 tags")
    return {"summary": summary, "tags": normalized}


def ensure_summary_section(markdown, summary):
    if re.search(r"(?m)^##\s+摘要\s*$", markdown):
        return markdown
    match = re.match(r"\A---\s*\r?\n.*?\r?\n---\s*", markdown, re.DOTALL)
    if not match:
        return markdown
    return markdown[:match.end()].rstrip() + f"\n\n## 摘要\n\n{summary}\n\n" + markdown[match.end():].lstrip()


def repair_markdown_output(markdown, url, title, cfg):
    """Ask the configured model once to repair structure without re-fetching."""
    if len(markdown) > MAX_REPAIR_INPUT_CHARS:
        raise RuntimeError("模型输出过长，无法安全执行格式修复")
    now_local = time.strftime("%Y-%m-%dT%H:%M")
    system_prompt = (
        "你是一名 Markdown 格式修复器。保留输入中的中文译文内容与信息，不要删减正文，"
        "只修复文档结构。输出必须直接以 --- 开头，不要代码围栏、解释或前言。"
        + ENRICHMENT_RULES
    )
    user_prompt = (
        f"来源 URL: {url}\n"
        f"书签标题: {title}\n"
        f"收录时间: {now_local}\n\n"
        "下面是一次模型生成的译文，但它的文档结构不符合要求。"
        "请保留全文并修复为完整 Markdown：\n\n"
        + markdown
    )

    if cfg["provider"] == "deepseek":
        payload = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": MAX_TOKENS,
            "stream": False,
            "temperature": 0,
        }
        if cfg["model"].startswith("deepseek-v4"):
            payload["thinking"] = {"type": "disabled"}
        resp = deepseek_request("/chat/completions", payload, cfg)
        choice = (resp.get("choices") or [{}])[0]
        repaired = ((choice.get("message") or {}).get("content") or "").strip()
        if not repaired:
            raise RuntimeError("DeepSeek 格式修复响应为空")
        if choice.get("finish_reason") == "length":
            raise RuntimeError("格式修复输出超出上限")
        return repaired

    if cfg["provider"] == "anthropic":
        resp = anthropic_request("/v1/messages", {
            "model": cfg["model"],
            "max_tokens": MAX_TOKENS,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }, cfg)
        if resp.get("stop_reason") == "max_tokens":
            raise RuntimeError("格式修复输出超出上限")
        repaired = "\n".join(
            block.get("text", "")
            for block in resp.get("content", [])
            if block.get("type") == "text"
        ).strip()
        if not repaired:
            raise RuntimeError("Anthropic 格式修复响应为空")
        return repaired

    raise RuntimeError(f"不支持的 API provider：{cfg['provider']}")


def rejected_output_preview(text):
    preview = re.sub(r"\s+", " ", text).strip()
    return preview[:REJECTED_PREVIEW_CHARS]


def prepare_enriched_markdown(markdown, url, title, cfg):
    """Normalize, validate, and at most once repair a model-produced document."""
    try:
        document = normalize_markdown_document(markdown)
        enrichment = extract_enrichment(document)
    except RuntimeError as first_error:
        log(f"模型输出格式不合规，执行一次自动修复：{first_error}")
        repaired = None
        try:
            repaired = repair_markdown_output(markdown, url, title, cfg)
            document = normalize_markdown_document(repaired)
            enrichment = extract_enrichment(document)
        except Exception as repair_error:
            log(
                "格式修复仍失败；原始输出安全预览："
                f"{rejected_output_preview(markdown)}"
            )
            if repaired:
                log(
                    "格式修复输出安全预览："
                    f"{rejected_output_preview(repaired)}"
                )
            raise RuntimeError(f"模型输出格式修复失败：{repair_error}") from repair_error
        log("模型输出格式自动修复成功")
    document = ensure_summary_section(document, enrichment["summary"])
    return document, enrichment


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
    with os.fdopen(fd, "w", encoding="utf-8") as f:
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
    return acquire_file_lock(LOCK_FILE)


# ===== 自检 =====

def run_check():
    print("== Info Collector 翻译流自检 ==")
    ok = True
    cfg = load_config()
    if not os.path.exists(CONFIG_FILE):
        setup_name = "scripts/setup.ps1" if os.name == "nt" else "scripts/setup.sh"
        print(f"✕ 配置文件不存在：{CONFIG_FILE}（运行 {setup_name}）")
        ok = False
    elif config_error(cfg):
        print(f"✕ {config_error(cfg)}：{CONFIG_FILE}")
        ok = False
    else:
        try:
            check_api_key(cfg)
            print(f"✓ API Key 有效（{cfg['provider']} / {cfg['model']}）")
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
    configure_text_stdio()
    if "--check" in sys.argv:
        sys.exit(run_check())

    log("=" * 50)
    log(f"开始巡检翻译队列（{TRIGGER}）")

    cfg = load_config()
    if not config_ok(cfg):
        setup_name = "setup.ps1" if os.name == "nt" else "setup.sh"
        log(f"❌ {config_error(cfg)}，跳过（编辑 ~/.info-collector/config.json 或重跑 {setup_name}）")
        return
    log(f"使用翻译引擎：{cfg['provider']} / {cfg['model']}")

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
            if a.get("url") and a.get("articleKey") not in state and a.get("url") not in state
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
                md, enrichment = prepare_enriched_markdown(md, url, title, cfg)
                path = save_markdown(md, extract_title(md, title), out_dir)
                results.append({"url": url, "status": "done", "processedAt": now_utc,
                                "meta": {"savedTo": path, **enrichment}})
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
        release_lock(lock_fd)


if __name__ == "__main__":
    main()

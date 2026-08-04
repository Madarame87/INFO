#!/usr/bin/env python3
"""Build a polished, local-first static reading site from translated Markdown."""

import argparse
from collections import Counter
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urlparse
import webbrowser

try:
    from info_collector_platform import acquire_lock, release_lock, user_home
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from info_collector_platform import acquire_lock, release_lock, user_home


HOME = user_home()
SPOOL = HOME / ".info-collector"
CONFIG_FILE = SPOOL / "config.json"
STATUS_FILE = SPOOL / "state" / "reading-site-status.json"
LOCK_FILE = SPOOL / "state" / "reading-site.lock"
LOG_FILE = SPOOL / "state" / "reading-site.log"
TRIGGER = "manual"

KEYWORD_RULES = [
    ("智能体", r"智能体|agent(?:ic|s)?|coding agent|代理"),
    ("模型评估", r"模型评估|评估|eval(?:uation)?|benchmark|测试"),
    ("大模型", r"大模型|\bllms?\b|claude|deepseek|\bgpt(?:-\w+)?\b"),
    ("提示工程", r"提示工程|提示词|\bprompt(?:ing)?\b"),
    ("软件工程", r"软件工程|编程|代码|开发|software|\bcode\b|coding"),
    ("产品", r"产品|product|用户体验|ux\b"),
    ("推理", r"推理|reasoning|判断力|judgement|未知"),
    ("记忆系统", r"记忆系统|memory system|长期记忆|上下文"),
    ("学术研究", r"学术|科研|研究方法|research"),
    ("AI 协作", r"协作|collaboration|human[ -]ai|人机"),
]


def configure_text_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass


def log(message):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def load_json(path, default):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def atomic_write_json(path, value):
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=1))


def update_status(patch):
    status = load_json(STATUS_FILE, {})
    status.update(patch)
    atomic_write_json(STATUS_FILE, status)


def parse_scalar(raw):
    raw = str(raw or "").strip()
    if not raw:
        return ""
    try:
        value = json.loads(raw)
        return value if isinstance(value, str) else str(value)
    except json.JSONDecodeError:
        return raw.strip("'\"")


def split_document(text):
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        return {}, text
    frontmatter = match.group(1)
    meta = {}
    for found in re.finditer(r"(?m)^([A-Za-z_][\w-]*):[ \t]*(.*)$", frontmatter):
        meta[found.group(1)] = parse_scalar(found.group(2))
    raw_tags = re.search(r"(?m)^tags:[ \t]*(.*)$", frontmatter)
    tags = []
    if raw_tags:
        raw = raw_tags.group(1).strip()
        try:
            value = json.loads(raw)
            tags = value if isinstance(value, list) else []
        except json.JSONDecodeError:
            tags = [item.strip(" '\"") for item in re.split(r"[,，]", raw.strip("[]"))]
    meta["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    return meta, text[match.end():].lstrip()


def plain_markdown(value):
    value = re.sub(r"```.*?```", " ", str(value), flags=re.DOTALL)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*_>#~]", "", value)
    value = re.sub(r"(?m)^\s*[-+*]\s+", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_summary(body):
    summary_section = re.search(
        r"(?ms)^##\s+摘要\s*\n+(.*?)(?=^#{1,6}\s+|\Z)", body
    )
    if summary_section:
        summary = plain_markdown(summary_section.group(1))
        if summary:
            return summary[:320].rstrip()
    chunks = re.split(r"\n\s*\n", body)
    chosen = []
    for chunk in chunks:
        if chunk.lstrip().startswith(("#", "```", "<", "[")):
            continue
        text = plain_markdown(chunk)
        if len(text) < 35:
            continue
        chosen.append(text)
        if len(" ".join(chosen)) >= 220:
            break
    summary = " ".join(chosen) or "这篇文章已完成中文整理，进入全文可查看完整内容。"
    return (summary[:319].rstrip() + "…") if len(summary) > 320 else summary


def infer_tags(title, summary, body, limit=4):
    haystack = f"{title}\n{summary}\n{body[:30000]}"
    ranked = []
    for order, (label, pattern) in enumerate(KEYWORD_RULES):
        score = len(re.findall(pattern, haystack, flags=re.IGNORECASE))
        if score:
            ranked.append((-score, order, label))
    tags = [label for _score, _order, label in sorted(ranked)[:limit]]
    return tags or ["技术观察"]


def safe_http_url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def article_slug(source, title):
    seed = source or title
    return "article-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def normalize_published_at(value, source=""):
    """Validate published precision and use only an explicit full URL date fallback."""
    value = parse_scalar(value)
    normalized = ""
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value)
    if match:
        year = int(match.group(1))
        month_text = match.group(2)
        day_text = match.group(3)
        if 1000 <= year <= 9999:
            if month_text is None:
                normalized = f"{year:04d}"
            month = int(month_text) if month_text is not None else 0
            if month_text is not None and 1 <= month <= 12:
                if day_text is None:
                    normalized = f"{year:04d}-{month:02d}"
                else:
                    try:
                        dt.date(year, month, int(day_text))
                        normalized = f"{year:04d}-{month:02d}-{int(day_text):02d}"
                    except ValueError:
                        pass
    path = urlparse(str(source or "")).path
    for pattern in (
        r"(?<!\d)(\d{4})/(\d{2})/(\d{2})(?!\d)",
        r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)",
    ):
        found = re.search(pattern, path)
        if not found:
            continue
        try:
            year, month, day = map(int, found.groups())
            dt.date(year, month, day)
            url_date = f"{year:04d}-{month:02d}-{day:02d}"
            return url_date if not normalized or len(normalized) < 10 else normalized
        except ValueError:
            continue
    return normalized


def valid_date_part(value):
    match = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", str(value or ""))
    if not match:
        return ""
    try:
        year, month, day = map(int, match.groups())
        dt.date(year, month, day)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return ""


def published_label(article):
    value = article.get("published_at") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return f"发布于 {value}"
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return f"发布于 {value}（精确到月）"
    if re.fullmatch(r"\d{4}", value):
        return f"发布于 {value}（精确到年）"
    return "发布时间未知"


def activity_label(article):
    collected = valid_date_part(article.get("collected_at"))
    if collected:
        return f"收录于 {collected}"
    processed = valid_date_part(article.get("processed_at"))
    if processed:
        return f"整理于 {processed}"
    legacy = valid_date_part(article.get("legacy_date"))
    if legacy:
        return f"整理于 {legacy}"
    return "收录时间未知"


def read_article(path):
    text = Path(path).read_text(encoding="utf-8")
    meta, body = split_document(text)
    title = meta.get("title") or Path(path).stem
    source = safe_http_url(meta.get("source"))
    summary = str(meta.get("summary") or "").strip() or extract_summary(body)
    tags = list(dict.fromkeys(meta.get("tags") or infer_tags(title, summary, body)))[:5]
    slug = article_slug(source, title)
    article_key = str(meta.get("article_key") or "").strip()
    return {
        "title": title,
        "source": source,
        "article_key": article_key,
        "article_id": article_key or slug,
        "published_at": normalize_published_at(
            meta.get("published_at") or meta.get("published"), source
        ),
        "collected_at": str(meta.get("collected_at") or "").strip(),
        "processed_at": str(meta.get("processed_at") or "").strip(),
        "legacy_date": str(meta.get("date") or "").strip(),
        "authors": str(meta.get("authors") or "").strip(),
        "content_status": str(meta.get("content_status") or "").strip(),
        "summary": summary,
        "tags": tags,
        "body": body,
        "path": Path(path),
        "slug": slug,
    }


def collect_articles(output_dir):
    articles = []
    for path in sorted(Path(output_dir).glob("*.md")):
        try:
            articles.append(read_article(path))
        except (OSError, UnicodeError) as exc:
            log(f"跳过无法读取的文章 {path.name}: {exc}")
    return sorted(
        articles,
        key=lambda item: (
            item["collected_at"] or item["processed_at"] or item["legacy_date"],
            item["title"],
        ),
        reverse=True,
    )


def escape_attr(value):
    return html.escape(str(value or ""), quote=True)


def inline_markup(text):
    def style_plain(value):
        escaped = html.escape(value, quote=False)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
        return escaped

    output = []
    cursor = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        output.append(style_plain(text[cursor:match.start()]))
        label, raw_href = match.group(1), match.group(2).strip()
        href = safe_http_url(raw_href)
        if href:
            output.append(
                f'<a href="{escape_attr(href)}" target="_blank" rel="noopener noreferrer">'
                f'{style_plain(label)}</a>'
            )
        else:
            output.append(style_plain(label))
        cursor = match.end()
    output.append(style_plain(text[cursor:]))
    return "".join(output)


def strip_summary_section(body):
    return re.sub(r"(?ms)^##\s+摘要\s*\n+.*?(?=^#{1,6}\s+|\Z)", "", body, count=1).lstrip()


def render_markdown(body, document_title=""):
    lines = strip_summary_section(body).splitlines()
    output = []
    paragraph = []
    in_code = False
    code_lines = []
    code_language = ""
    list_kind = None
    heading_index = 0
    title_skipped = False

    def close_paragraph():
        if paragraph:
            text = " ".join(part.strip() for part in paragraph)
            output.append(f"<p>{inline_markup(text)}</p>")
            paragraph.clear()

    def close_list():
        nonlocal list_kind
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = None

    for line in lines:
        if line.startswith("```"):
            close_paragraph()
            close_list()
            if not in_code:
                in_code = True
                code_language = line[3:].strip()
                code_lines = []
            else:
                language = f' data-language="{escape_attr(code_language)}"' if code_language else ""
                output.append(
                    f'<div class="code-block"><button class="copy-code" type="button">复制</button>'
                    f'<pre{language}><code>{html.escape(chr(10).join(code_lines))}</code></pre></div>'
                )
                in_code = False
            continue
        if in_code:
            code_lines.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            close_paragraph()
            close_list()
            level = len(heading.group(1))
            text = plain_markdown(heading.group(2))
            if level == 1 and not title_skipped and text.strip() == document_title.strip():
                title_skipped = True
                continue
            heading_index += 1
            level = max(2, min(level, 4))
            output.append(
                f'<h{level} id="section-{heading_index}">{inline_markup(heading.group(2))}</h{level}>'
            )
            continue
        unordered = re.match(r"^\s*[-+*]\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            close_paragraph()
            desired = "ul" if unordered else "ol"
            if list_kind != desired:
                close_list()
                output.append(f"<{desired}>")
                list_kind = desired
            output.append(f"<li>{inline_markup((unordered or ordered).group(1))}</li>")
            continue
        if line.startswith(">"):
            close_paragraph()
            close_list()
            output.append(f"<blockquote>{inline_markup(line.lstrip('> ').strip())}</blockquote>")
            continue
        if re.match(r"^\s*(?:---+|___+|\*\*\*+)\s*$", line):
            close_paragraph()
            close_list()
            output.append("<hr>")
            continue
        if not line.strip():
            close_paragraph()
            close_list()
            continue
        paragraph.append(line)

    close_paragraph()
    close_list()
    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(output)


def page_shell(title, description, content, asset_prefix="assets", body_class="", asset_version=""):
    asset_suffix = f"?v={escape_attr(asset_version)}" if asset_version else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{escape_attr(description)}">
  <meta name="color-scheme" content="light">
  <meta name="theme-color" content="#f4f1ea">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{escape_attr(title)} · Info Collector">
  <meta property="og:description" content="{escape_attr(description)}">
  <meta property="og:image" content="https://info-collector-reading-desk.jiligualapiqiu.chatgpt.site/og.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="https://info-collector-reading-desk.jiligualapiqiu.chatgpt.site/og.png">
  <title>{html.escape(title)} · Info Collector</title>
  <link rel="stylesheet" href="{asset_prefix}/style.css{asset_suffix}">
</head>
<body class="{escape_attr(body_class)}">
  <div class="reading-progress" aria-hidden="true"><span id="reading-progress-bar"></span></div>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="site-brand" href="{('../' if asset_prefix.startswith('..') else '')}index.html" aria-label="Info Collector 阅读库首页">
        <span class="brand-signal" aria-hidden="true"></span>
        <span><small>PERSONAL TECHNOLOGY INTELLIGENCE</small><strong>Info Collector<span class="brand-dot" aria-hidden="true">.</span></strong></span>
      </a>
      <div class="site-credits" aria-label="Built by @130U × @aswrise">
        <span class="credit-label">Built by</span>
        <span class="credit-people"><a href="https://github.com/130U" target="_blank" rel="noopener noreferrer">@130U</a> <i aria-hidden="true">×</i> <a href="https://github.com/aswrise" target="_blank" rel="noopener noreferrer">@aswrise</a></span>
      </div>
    </div>
  </header>
  {content}
  <footer class="site-footer" aria-label="Built by @130U × @aswrise"><span>Built by</span> <a href="https://github.com/130U" target="_blank" rel="noopener noreferrer">@130U</a> <i aria-hidden="true">×</i> <a href="https://github.com/aswrise" target="_blank" rel="noopener noreferrer">@aswrise</a></footer>
  <script src="{asset_prefix}/app.js{asset_suffix}" defer></script>
</body>
</html>
"""


def render_tag(tag, active=False, button=False, count=None):
    count_html = f"<span>{count}</span>" if count is not None else ""
    if button:
        return (
            f'<button class="tag-filter{" is-active" if active else ""}" type="button" '
            f'data-tag="{escape_attr(tag)}" aria-pressed="{"true" if active else "false"}">{html.escape(tag)}{count_html}</button>'
        )
    return f'<span class="keyword">{html.escape(tag)}</span>'


def render_index(articles, asset_version=""):
    counts = Counter(tag for article in articles for tag in article["tags"])
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    cards = []
    for article in articles:
        tag_html = "".join(render_tag(tag) for tag in article["tags"])
        status_badge = (
            '<span class="content-status-badge">原文受限</span>'
            if article["content_status"] == "source_blocked" else ""
        )
        article_href = f"articles/{article['slug']}.html"
        source_link = (
            f'<a class="card-source-link" href="{escape_attr(article["source"])}" '
            'target="_blank" rel="noopener noreferrer">原文 ↗</a>'
            if article["source"] else ""
        )
        author_html = (
            f'<p class="card-author">作者：{html.escape(article["authors"])}</p>'
            if article["authors"] else ""
        )
        cards.append(f"""
        <article class="article-card reveal" data-article-id="{escape_attr(article['article_id'])}" data-tags="{escape_attr('|'.join(article['tags']))}" data-title="{escape_attr(article['title'])}" data-summary="{escape_attr(article['summary'])}" data-authors="{escape_attr(article['authors'])}" data-source="{escape_attr(article['source'])}" data-published-value="{escape_attr(article['published_at'])}" data-collected-value="{escape_attr(article['collected_at'])}" data-processed-value="{escape_attr(article['processed_at'] or article['legacy_date'])}" data-content-status="{escape_attr(article['content_status'])}">
          <div class="card-main">
            <div class="keyword-row">{tag_html}{status_badge}</div>
            <h2 title="{escape_attr(article['title'])}"><a class="article-title-link" href="{article_href}">{html.escape(article['title'])}</a></h2>
            <p class="card-summary">{html.escape(article['summary'])}</p>{author_html}
            <div class="card-actions">
              <button class="card-action favorite-action" type="button" data-action="favorite" aria-pressed="false">收藏</button>
              <button class="card-action review-action" type="button" data-action="review">完成整理</button>
              <button class="card-action copy-card-action" type="button" data-action="copy-card">复制资料卡</button>
              {source_link}
            </div>
          </div>
          <div class="card-meta" aria-label="文章时间">
            <span class="published-label">{html.escape(published_label(article))}</span>
            <span class="activity-label">{html.escape(activity_label(article))}</span>
          </div>
        </article>""")
    all_button = render_tag("全部", active=True, button=True)
    tag_buttons = "".join(render_tag(tag, button=True) for tag, _count in ranked)
    content = f"""
  <main class="library-shell">
    <section class="library-hero reveal">
      <p class="eyebrow"><i></i> KNOWLEDGE STREAM</p>
      <div class="hero-grid">
        <div class="hero-copy">
          <h1>文章情报库</h1>
          <p class="hero-lede">将公开技术文章转化为中文摘要、主题线索与可追溯的人工研判。</p>
        </div>
        <div class="library-stats view-filters" id="view-filters" role="group" aria-label="整理视图">
          <button class="view-filter is-active" type="button" data-view="pending" aria-pressed="true"><strong data-count-view="pending">{len(articles)}</strong><span>待整理</span></button>
          <button class="view-filter" type="button" data-view="favorites" aria-pressed="false"><strong data-count-view="favorites">0</strong><span>我的收藏</span></button>
          <button class="view-filter" type="button" data-view="all" aria-pressed="false"><strong data-count-view="all">{len(articles)}</strong><span>全部收录</span></button>
        </div>
      </div>
    </section>
    <section class="discovery-panel reveal" aria-labelledby="filter-title">
      <div class="weekly-activity" aria-labelledby="weekly-activity-title">
        <div class="weekly-activity-head">
          <div class="weekly-activity-title">
            <small>WEEKLY ACTIVITY</small>
            <h2 id="weekly-activity-title">每周阅读趋势</h2>
            <p>最近六周的人工判断节奏</p>
          </div>
          <div class="weekly-activity-meta">
            <p><span id="weekly-range">本周</span><small id="weekly-breakdown">收藏 0 · 已整理 0</small></p>
            <button class="weekly-export" id="export-weekly" type="button" disabled>导出本周 Markdown</button>
          </div>
        </div>
        <div class="weekly-trend" role="img" aria-label="最近六周人工判断文章数量趋势">
          <div class="weekly-chart-caption"><span>人工判断文章数</span><span>周一至周日</span></div>
          <svg viewBox="0 0 760 160" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="weekly-area-gradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#456b5a" stop-opacity=".22"></stop>
                <stop offset="72%" stop-color="#456b5a" stop-opacity=".045"></stop>
                <stop offset="100%" stop-color="#456b5a" stop-opacity="0"></stop>
              </linearGradient>
            </defs>
            <path class="weekly-chart-grid" d="M 18 28 L 742 28 M 18 82 L 742 82 M 18 136 L 742 136"></path>
            <path class="weekly-chart-area" id="weekly-chart-area" d=""></path>
            <path class="weekly-chart-line" id="weekly-chart-line" d=""></path>
            <line class="weekly-chart-marker-line" id="weekly-chart-marker-line" x1="0" y1="0" x2="0" y2="0"></line>
            <circle class="weekly-chart-halo" id="weekly-chart-halo" cx="0" cy="0" r="10"></circle>
            <circle class="weekly-chart-marker" id="weekly-chart-marker" cx="0" cy="0" r="4"></circle>
            <text class="weekly-chart-value" id="weekly-chart-value" x="0" y="0" text-anchor="middle">0</text>
          </svg>
          <div class="weekly-periods" id="weekly-periods" aria-hidden="true"></div>
        </div>
      </div>
      <div class="filter-heading"><h2 id="filter-title">按关键词浏览</h2><output id="result-count" aria-live="polite" aria-atomic="true">显示 {len(articles)} 篇</output></div>
      <div class="tag-filters" id="tag-filters" role="group" aria-label="文章关键词筛选">{all_button}{tag_buttons}</div>
    </section>
    <section class="article-grid" id="article-grid">{''.join(cards)}</section>
    <section class="empty-state" id="empty-state" hidden><span>—</span><h2 id="empty-title">没有符合条件的文章</h2></section>
  </main>"""
    return page_shell("文章情报库", "Info Collector 本地中文技术文章阅读库", content, body_class="library-page", asset_version=asset_version)


def render_article_page(article, asset_version=""):
    tags = "".join(render_tag(tag) for tag in article["tags"])
    meta_items = [
        html.escape(published_label(article)),
        html.escape(activity_label(article)),
    ]
    if article["authors"]:
        meta_items.append(f"作者 {html.escape(article['authors'])}")
    meta_items = [item for item in meta_items if item]
    body_html = render_markdown(article["body"], article["title"])
    source_warning = ""
    if article["content_status"] == "source_blocked":
        source_warning = """
      <aside class="source-warning reveal">
        <span>原文受限</span>
        <p>原站拒绝了自动访问，因此本页只保留可核验的标题、链接与状态说明，没有把未读取的内容伪装成中文译文。</p>
      </aside>"""
    original = ""
    if article["source"]:
        original = f"""
      <section class="source-card reveal">
        <div><p class="eyebrow">ORIGINAL SOURCE</p><h2>继续查看原文</h2><p>中文译文用于高效理解；需要核对语境、图表或引用时，请返回作者原始页面。</p></div>
        <a href="{escape_attr(article['source'])}" target="_blank" rel="noopener noreferrer">访问文章原文 <span>↗</span></a>
      </section>"""
    content = f"""
  <main class="article-shell">
    <a class="back-link" href="../index.html">← 返回文章情报库</a>
    <article data-article-id="{escape_attr(article['article_id'])}">
      <header class="article-hero reveal">
        <p class="eyebrow"><i></i> TRANSLATED INTELLIGENCE</p>
        <div class="keyword-row">{tags}</div>
        <h1>{html.escape(article['title'])}</h1>
        <div class="article-meta">{'<span class="meta-dot"></span>'.join(meta_items)}</div>
      </header>
      <section class="summary-card reveal" aria-labelledby="summary-title">
        <div class="summary-label"><span>01</span><p>EXECUTIVE SUMMARY</p></div>
        <h2 id="summary-title">先读结论</h2>
        <p>{html.escape(article['summary'])}</p>
      </section>
{source_warning}
      <div class="reading-layout">
        <aside class="toc-card" aria-label="文章目录"><p>本页目录</p><nav id="article-toc"><span>正在整理章节…</span></nav></aside>
        <section class="translated-copy reveal">
          <div class="section-kicker"><span>02</span><div><p>CHINESE TRANSLATION</p><h2>中文译文</h2></div></div>
          <div class="prose" id="article-content">{body_html}</div>
        </section>
      </div>
      {original}
    </article>
  </main>"""
    return page_shell(article["title"], article["summary"], content, asset_prefix="../assets", body_class="article-page", asset_version=asset_version)


def asset_source_dir():
    candidates = [
        Path(__file__).resolve().with_name("reader-assets"),
        Path(__file__).resolve().parents[1] / "reader" / "assets",
    ]
    for candidate in candidates:
        if (candidate / "style.css").is_file() and (candidate / "app.js").is_file():
            return candidate
    raise RuntimeError("阅读站前端资源缺失：reader/assets")


def frontend_asset_version(source_assets):
    digest = hashlib.sha256()
    for name in ("style.css", "app.js"):
        digest.update((Path(source_assets) / name).read_bytes())
    return digest.hexdigest()[:12]


def build_site(output_dir, site_dir=None):
    output_dir = Path(output_dir).expanduser().resolve()
    site_dir = Path(site_dir or output_dir / "阅读站").expanduser().resolve()
    articles = collect_articles(output_dir)
    (site_dir / "articles").mkdir(parents=True, exist_ok=True)
    assets_target = site_dir / "assets"
    assets_target.mkdir(parents=True, exist_ok=True)
    source_assets = asset_source_dir()
    asset_version = frontend_asset_version(source_assets)
    shutil.copy2(source_assets / "style.css", assets_target / "style.css")
    shutil.copy2(source_assets / "app.js", assets_target / "app.js")
    atomic_write_text(site_dir / "index.html", render_index(articles, asset_version=asset_version))
    expected = set()
    for article in articles:
        name = f"{article['slug']}.html"
        expected.add(name)
        atomic_write_text(site_dir / "articles" / name, render_article_page(article, asset_version=asset_version))
    for stale in (site_dir / "articles").glob("article-*.html"):
        if stale.name not in expected:
            stale.unlink()
    return site_dir / "index.html", articles


def main(argv=None):
    configure_text_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", help="Translated Markdown directory; defaults to config.json")
    parser.add_argument("--site-dir", help="Static site output directory")
    parser.add_argument("--open", action="store_true", dest="open_site", help="Open the generated index")
    args = parser.parse_args(argv)
    cfg = load_json(CONFIG_FILE, {})
    output_dir = args.output_dir or cfg.get("outputDir") or str(HOME / "Documents" / "InfoCollector")
    site_dir = args.site_dir or cfg.get("readingSiteDir")
    lock_fd = acquire_lock(LOCK_FILE)
    if lock_fd is None:
        log("阅读站生成流程已在运行，跳过")
        return 0
    started = dt.datetime.now().astimezone()
    last_run = {"startedAt": started.isoformat(timespec="seconds"), "trigger": TRIGGER, "outcome": "running"}
    update_status({"lastRun": last_run})
    try:
        index_path, articles = build_site(output_dir, site_dir=site_dir)
        last_run.update({
            "outcome": "success" if articles else "empty",
            "finishedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "count": len(articles),
            "siteIndex": str(index_path),
        })
        update_status({"lastRun": last_run, "siteIndex": str(index_path)})
        log(f"阅读站已生成：{index_path}（{len(articles)} 篇）")
        if args.open_site:
            webbrowser.open(index_path.as_uri(), new=2)
        return 0
    except Exception as exc:
        last_run.update({
            "outcome": "error",
            "finishedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "error": str(exc)[:300],
        })
        update_status({"lastRun": last_run})
        log(f"阅读站生成失败：{exc}")
        return 1
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())

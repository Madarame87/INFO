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
    for found in re.finditer(r"(?m)^([A-Za-z_][\w-]*):\s*(.*)$", frontmatter):
        meta[found.group(1)] = parse_scalar(found.group(2))
    raw_tags = re.search(r"(?m)^tags:\s*(.*)$", frontmatter)
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


def read_article(path):
    text = Path(path).read_text(encoding="utf-8")
    meta, body = split_document(text)
    title = meta.get("title") or Path(path).stem
    source = safe_http_url(meta.get("source"))
    summary = str(meta.get("summary") or "").strip() or extract_summary(body)
    tags = list(dict.fromkeys(meta.get("tags") or infer_tags(title, summary, body)))[:5]
    return {
        "title": title,
        "source": source,
        "published": str(meta.get("published") or "").strip(),
        "collected": str(meta.get("date") or "").strip(),
        "authors": str(meta.get("authors") or "").strip(),
        "summary": summary,
        "tags": tags,
        "body": body,
        "path": Path(path),
        "slug": article_slug(source, title),
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
        key=lambda item: (item["published"] or item["collected"], item["title"]),
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
      <div class="site-credits" aria-label="Powered by @Madarame87 × @aswrise">
        <span class="credit-label">Powered by</span>
        <span class="credit-people"><a href="https://github.com/Madarame87" target="_blank" rel="noopener noreferrer">@Madarame87</a> <i aria-hidden="true">×</i> <a href="https://github.com/aswrise" target="_blank" rel="noopener noreferrer">@aswrise</a></span>
      </div>
    </div>
  </header>
  {content}
  <footer class="site-footer" aria-label="Powered by @Madarame87 × @aswrise"><span>Powered by</span> <a href="https://github.com/Madarame87" target="_blank" rel="noopener noreferrer">@Madarame87</a> <i aria-hidden="true">×</i> <a href="https://github.com/aswrise" target="_blank" rel="noopener noreferrer">@aswrise</a></footer>
  <script src="{asset_prefix}/app.js{asset_suffix}" defer></script>
</body>
</html>
"""


def date_label(article):
    for candidate in (article["published"], article["collected"]):
        match = re.search(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", str(candidate or ""))
        if match:
            return match.group(0)
    return "已收录"


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
        article_href = f"articles/{article['slug']}.html"
        display_date = date_label(article)
        datetime_attr = f' datetime="{escape_attr(display_date)}"' if re.fullmatch(r"\d{4}-\d{2}-\d{2}", display_date) else ""
        cards.append(f"""
        <a class="article-card reveal" href="{article_href}" aria-label="打开文章：{escape_attr(article['title'])}" data-tags="{escape_attr('|'.join(article['tags']))}">
          <div class="card-main">
            <div class="keyword-row">{tag_html}</div>
            <h2 title="{escape_attr(article['title'])}">{html.escape(article['title'])}</h2>
            <p>{html.escape(article['summary'])}</p>
          </div>
          <div class="card-meta">
            <span>DATE</span>
            <time class="card-date"{datetime_attr}>{html.escape(display_date)}</time>
            <b aria-hidden="true">↗</b>
          </div>
        </a>""")
    all_button = render_tag("全部", active=True, button=True)
    tag_buttons = "".join(render_tag(tag, button=True) for tag, _count in ranked)
    newest = date_label(articles[0]) if articles else "—"
    content = f"""
  <main class="library-shell">
    <section class="library-hero reveal">
      <p class="eyebrow"><i></i> KNOWLEDGE STREAM</p>
      <div class="hero-grid">
        <div><h1>文章情报库</h1></div>
        <dl class="library-stats"><div><dt>篇文章</dt><dd>{len(articles)}</dd></div><div><dt>个关键词</dt><dd>{len(ranked)}</dd></div><div><dt>最近更新</dt><dd>{html.escape(newest)}</dd></div></dl>
      </div>
    </section>
    <section class="discovery-panel reveal" aria-labelledby="filter-title">
      <div class="filter-heading"><h2 id="filter-title">按关键词浏览</h2><output id="result-count" aria-live="polite" aria-atomic="true">显示 {len(articles)} 篇</output></div>
      <div class="tag-filters" id="tag-filters" role="group" aria-label="文章关键词筛选">{all_button}{tag_buttons}</div>
    </section>
    <section class="article-grid" id="article-grid">{''.join(cards)}</section>
    <section class="empty-state" id="empty-state" hidden><span>—</span><h2>没有找到对应文章</h2><p>请选择其他关键词查看文章。</p></section>
  </main>"""
    return page_shell("文章情报库", "Info Collector 本地中文技术文章阅读库", content, body_class="library-page", asset_version=asset_version)


def render_article_page(article, asset_version=""):
    tags = "".join(render_tag(tag) for tag in article["tags"])
    meta_items = [f"发布于 {html.escape(article['published'][:10])}" if article["published"] else ""]
    if article["authors"]:
        meta_items.append(f"作者 {html.escape(article['authors'])}")
    meta_items = [item for item in meta_items if item]
    body_html = render_markdown(article["body"], article["title"])
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
    <article>
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

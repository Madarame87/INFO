#!/usr/bin/env python3
"""Refresh the checked-in public snapshot without needing the private Markdown library.

The snapshot index already contains the public metadata contract. This script reads that
contract, reapplies current quality gates and templates, and quarantines rejected pages.
"""

from html.parser import HTMLParser
import html
import importlib.util
from pathlib import Path
import re
import shutil
from xml.sax.saxutils import escape as xml_escape


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "flows" / "generate-reading-site.py"
PUBLIC = ROOT / "site" / "public"
PUBLIC_SITE_URL = "https://info.theodoreoy.com"


def load_generator():
    spec = importlib.util.spec_from_file_location("info_collector_reading_site", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SnapshotIndexParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.articles = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set(values.get("class", "").split())
        if tag == "article" and ("article-card" in classes or "recovery-card" in classes):
            self.current = values
            if values.get("data-article-href"):
                self.current["article-href"] = values["data-article-href"]
        elif self.current is not None and tag == "a" and "article-title-link" in classes:
            self.current["article-href"] = values.get("href", "")

    def handle_endtag(self, tag):
        if tag == "article" and self.current is not None:
            self.articles.append(self.current)
            self.current = None


def article_from_attrs(attrs, generator):
    href = attrs.get("article-href", "")
    slug = Path(href).stem
    tags = [tag for tag in attrs.get("data-tags", "").split("|") if tag]
    summary = attrs.get("data-summary", "")
    existing_page = PUBLIC / "articles" / f"{slug}.html"
    existing_text = existing_page.read_text(encoding="utf-8") if existing_page.exists() else ""
    body_match = re.search(
        r'<div class="prose" id="article-content">([\s\S]*?)</div>\s*</section>',
        existing_text,
    )
    body_html = body_match.group(1) if body_match else ""
    status = generator.content_quality_status(summary, existing_text, attrs.get("data-content-status", ""))
    if status == "quality_rejected":
        summary = "抓取结果疑似登录页或页面样板，已从译文库隔离；请在可见原文页重新采集。"
    elif status == "privacy_review_required":
        summary = "正文包含结构化用户画像或类似敏感字段，已从公开译文库隔离并等待人工隐私审查。"
    return {
        "title": attrs.get("data-title", "未命名文章"),
        "source": generator.safe_http_url(attrs.get("data-source", "")),
        "article_key": attrs.get("data-article-id", ""),
        "article_id": attrs.get("data-article-id", "") or slug,
        "published_at": attrs.get("data-published-value", ""),
        "collected_at": attrs.get("data-collected-value", ""),
        "processed_at": attrs.get("data-processed-value", ""),
        "legacy_date": "",
        "authors": attrs.get("data-authors", ""),
        "content_status": status,
        "summary": summary,
        "tags": tags or ["技术观察"],
        "body": "",
        "body_html": body_html,
        "path": PUBLIC / "articles" / f"{slug}.html",
        "slug": slug,
    }


def quarantined_article_from_page(path, generator):
    text = path.read_text(encoding="utf-8")
    if "quarantined-copy" not in text:
        return None
    title_match = re.search(r'<meta property="og:title" content="([^"]*)"', text)
    description_match = re.search(r'<meta name="description" content="([^"]*)"', text)
    source_match = re.search(r'<section class="source-card.*?<a href="([^"]+)"', text, re.DOTALL)
    tags = [html.unescape(value) for value in re.findall(r'<span class="keyword">(.*?)</span>', text)]
    title = html.unescape(title_match.group(1) if title_match else path.stem)
    title = re.sub(r" · Info Collector$", "", title)
    status_match = re.search(r'<article\b[^>]*data-content-status="([^"]+)"', text)
    status = status_match.group(1) if status_match else ""
    if status not in {"source_blocked", "quality_rejected", "privacy_review_required", "translation_missing"}:
        status = "source_blocked" if "原站拒绝匿名访问" in text else "quality_rejected"
    return {
        "title": title,
        "source": generator.safe_http_url(html.unescape(source_match.group(1))) if source_match else "",
        "article_key": path.stem,
        "article_id": path.stem,
        "published_at": "",
        "collected_at": "",
        "processed_at": "",
        "legacy_date": "",
        "authors": "",
        "content_status": status,
        "summary": html.unescape(description_match.group(1) if description_match else "来源尚未形成可信译文"),
        "tags": tags or ["待恢复"],
        "body": "",
        "path": path,
        "slug": path.stem,
    }


def write_discovery_files(articles, generator):
    routes = [""] + [f"articles/{article['slug']}.html" for article in articles]
    sitemap = "\n".join(
        f"  <url><loc>{xml_escape(f'{PUBLIC_SITE_URL}/{route}')}</loc></url>"
        for route in routes
    )
    generator.atomic_write_text(
        PUBLIC / "robots.txt",
        f"User-agent: *\nAllow: /\n\nSitemap: {PUBLIC_SITE_URL}/sitemap.xml\n",
    )
    generator.atomic_write_text(
        PUBLIC / "sitemap.xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{sitemap}\n"
        "</urlset>\n",
    )


def main():
    generator = load_generator()
    parser = SnapshotIndexParser()
    parser.feed((PUBLIC / "index.html").read_text(encoding="utf-8"))
    articles = [article_from_attrs(attrs, generator) for attrs in parser.articles]
    known_slugs = {article["slug"] for article in articles}
    for path in sorted((PUBLIC / "articles").glob("article-*.html")):
        if path.stem in known_slugs:
            continue
        quarantined = quarantined_article_from_page(path, generator)
        if quarantined:
            articles.append(quarantined)
    if not articles:
        raise SystemExit("public snapshot contains no article metadata")

    assets = generator.asset_source_dir()
    (PUBLIC / "assets").mkdir(parents=True, exist_ok=True)
    for name in ("style.css", "app.js"):
        shutil.copy2(assets / name, PUBLIC / "assets" / name)
    version = generator.frontend_asset_version(assets)
    generator.atomic_write_text(PUBLIC / "index.html", generator.render_index(articles, version))
    for article in articles:
        generator.atomic_write_text(
            PUBLIC / "articles" / f"{article['slug']}.html",
            generator.render_article_page(article, version),
        )
    write_discovery_files(articles, generator)
    print(f"refreshed {len(articles)} public records; quarantined {sum(bool(a['content_status']) for a in articles)}")


if __name__ == "__main__":
    main()

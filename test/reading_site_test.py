import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "flows" / "generate-reading-site.py"


def import_reader(home):
    old_home = os.environ.get("INFO_COLLECTOR_HOME")
    os.environ["INFO_COLLECTOR_HOME"] = str(home)
    try:
        spec = importlib.util.spec_from_file_location("reading_site_under_test", FLOW_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old_home is None:
            os.environ.pop("INFO_COLLECTOR_HOME", None)
        else:
            os.environ["INFO_COLLECTOR_HOME"] = old_home


class ReadingSiteTest(unittest.TestCase):
    def write_articles(self, output):
        output.mkdir(parents=True)
        (output / "agent.md").write_text(
            "---\n"
            'title: "智能体如何理解代码"\n'
            'article_key: "stable-agent-key"\n'
            "source: https://example.test/agent\n"
            "published_at: 2026-07-10\n"
            "collected_at: 2026-07-11T13:30:00-04:00\n"
            "processed_at: 2026-07-11T13:35:00-04:00\n"
            'authors: "研究团队"\n'
            'summary: "本文讨论智能体时代的人类代码理解问题，并给出可执行的评估方法。"\n'
            'tags: ["智能体", "模型评估"]\n'
            "---\n\n"
            "## 摘要\n\n这段摘要不应在正文中重复。\n\n"
            "# 智能体如何理解代码\n\n"
            "## 理解是新的瓶颈\n\n这是完整中文译文的第一段。\n\n"
            "### 方法\n\n- 解释文档\n- 微型世界\n\n"
            "[原文引用](https://example.test/reference)\n\n"
            "<script>alert('unsafe')</script>\n",
            encoding="utf-8",
        )
        (output / "fallback.md").write_text(
            "---\n"
            "title: 产品设计中的未知因素\n"
            "date: 2026-07-09T09:00\n"
            "---\n\n"
            "# 产品设计中的未知因素\n\n"
            "这是一段足够长的正文，用来验证没有 frontmatter 摘要时能够自动形成可读的卡片摘要，并在进入全文前帮助读者判断文章价值。\n\n"
            "## 设计方法\n\n通过用户访谈和原型发现未知问题。\n",
            encoding="utf-8",
        )
        (output / "blocked.md").write_text(
            "---\n"
            "title: 原站限制访问的机器人文章\n"
            "source: https://example.test/blocked\n"
            "processed_at: 2026-07-12T02:36:00-04:00\n"
            'summary: "原站拒绝自动抓取，未生成伪造译文。"\n'
            'tags: ["机器人", "产业动态"]\n'
            'content_status: "source_blocked"\n'
            "---\n\n## 正文状态\n\n原站拒绝自动抓取。\n",
            encoding="utf-8",
        )
        (output / "missing.md").write_text(
            "---\n"
            "title: 只有摘要、没有正文的文章\n"
            "source: https://example.test/missing\n"
            "processed_at: 2026-07-12T02:37:00-04:00\n"
            'summary: "摘要已经生成，但正文译文缺失，不能作为可信译文发布。"\n'
            'tags: ["机器人", "产品"]\n'
            "---\n",
            encoding="utf-8",
        )

    def test_builds_index_and_article_pages_with_keywords_summary_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            output = Path(tmp) / "translated"
            self.write_articles(output)
            index_path, articles = reader.build_site(output)
            self.assertEqual(len(articles), 4)
            self.assertTrue(index_path.exists())
            index = index_path.read_text(encoding="utf-8")
            self.assertIn("技术情报终端", index)
            self.assertIn("阅读收件箱", index)
            self.assertIn('data-tag="智能体"', index)
            self.assertIn("本文讨论智能体时代", index)
            self.assertIn('id="view-filters"', index)
            self.assertIn('data-view="pending" aria-pressed="true"', index)
            self.assertIn('data-view="favorites" aria-pressed="false"', index)
            self.assertIn('data-view="all" aria-pressed="false"', index)
            self.assertNotIn('data-view="weekly"', index)
            self.assertIn('id="export-weekly"', index)
            self.assertIn("阅读进度", index)
            self.assertIn('id="weekly-chart-line"', index)
            self.assertIn('id="weekly-chart-area"', index)
            self.assertIn('id="weekly-chart-marker"', index)
            self.assertIn('id="weekly-chart-value"', index)
            self.assertIn('id="weekly-periods"', index)
            self.assertNotIn('id="weekly-count"', index)
            self.assertNotIn('id="weekly-chart-points"', index)
            self.assertIn("导出 Markdown", index)
            self.assertIn("待整理", index)
            self.assertIn("我的收藏", index)
            self.assertIn("可信译文", index)
            self.assertIn("搜索标题、摘要、作者或主题", index)
            self.assertIn('id="article-search"', index)
            self.assertIn('class="command-bar"', index)
            self.assertNotIn("data-search=", index)
            self.assertIn('id="result-count" aria-live="polite" aria-atomic="true"', index)
            self.assertIn("主题筛选", index)
            self.assertRegex(index, r'href="assets/style\.css\?v=[0-9a-f]{12}"')
            self.assertIn('rel="icon" type="image/svg+xml" href="favicon.svg"', index)
            self.assertRegex(index, r'src="assets/app\.js\?v=[0-9a-f]{12}"')
            self.assertIn("Built by", index)
            self.assertIn("@130U", index)
            self.assertIn("@aswrise", index)
            self.assertEqual(index.count('href="https://github.com/130U"'), 2)
            self.assertEqual(index.count('href="https://github.com/aswrise"'), 2)
            self.assertIn("先判断价值，再进入全文", index)
            self.assertNotIn("Madarame87", index)
            self.assertNotIn("@THEO", index)
            self.assertNotIn("@AQUA", index)
            self.assertNotIn("WINDOWS 11 · LOCAL-FIRST", index)
            self.assertNotIn("INFO COLLECTOR / READING DESK", index)
            self.assertIn('class="brand-signal"', index)
            self.assertNotIn('class="brand-mark"', index)
            self.assertNotIn('class="feature-stage', index)
            self.assertIn('<details class="recovery-section"', index)
            self.assertEqual(index.count('<article class="article-card terminal-row'), 2)
            self.assertNotIn('<a class="article-card', index)
            self.assertEqual(index.count('class="article-title-link" href="articles/'), 2)
            self.assertIn('data-article-id="stable-agent-key"', index)
            self.assertIn('data-article-id="article-', index)
            self.assertEqual(index.count('data-action="favorite" aria-pressed="false"'), 2)
            self.assertEqual(index.count('data-action="review" aria-pressed="false"'), 2)
            self.assertEqual(index.count('data-action="copy-card"'), 2)
            self.assertEqual(index.count('class="card-source-link"'), 1)
            self.assertIn('data-content-status="source_blocked"', index)
            self.assertNotIn('class="content-status-badge"', index)
            self.assertNotIn('href=""', index)
            self.assertIn('class="card-meta"', index)
            self.assertIn('class="card-main"', index)
            self.assertIn("发布于 2026-07-10", index)
            self.assertIn("收录于 2026-07-11", index)
            self.assertIn("发布时间未知", index)
            self.assertIn("整理于 2026-07-09", index)
            self.assertNotIn(">DATE<", index)
            self.assertIn("阅读译文", index)
            self.assertNotIn('class="card-foot"', index)
            self.assertIn("作者 研究团队", index)
            agent = next(item for item in articles if item["article_id"] == "stable-agent-key")
            article_path = index_path.parent / "articles" / f"{agent['slug']}.html"
            article = article_path.read_text(encoding="utf-8")
            self.assertIn('data-return-library>返回阅读收件箱', article)
            self.assertIn("先读结论", article)
            self.assertIn("中文译文", article)
            self.assertIn("访问文章原文", article)
            self.assertIn("作者 研究团队", article)
            self.assertIn("发布于 2026-07-10", article)
            self.assertIn("收录于 2026-07-11", article)
            self.assertIn('data-article-id="stable-agent-key"', article)
            self.assertIn('href="https://example.test/agent" target="_blank" rel="noopener noreferrer"', article)
            self.assertRegex(article, r'href="\.\./assets/style\.css\?v=[0-9a-f]{12}"')
            self.assertIn('rel="icon" type="image/svg+xml" href="../favicon.svg"', article)
            self.assertRegex(article, r'src="\.\./assets/app\.js\?v=[0-9a-f]{12}"')
            self.assertLess(article.index("先读结论"), article.index("中文译文"))
            self.assertLess(article.index("中文译文"), article.index("继续查看原文"))
            self.assertNotIn("这段摘要不应在正文中重复", article)
            self.assertNotIn("<script>alert", article)
            self.assertIn("&lt;script&gt;", article)
            self.assertTrue((index_path.parent / "assets" / "style.css").exists())
            self.assertTrue((index_path.parent / "assets" / "app.js").exists())
            self.assertTrue((index_path.parent / "favicon.svg").exists())
            style = (index_path.parent / "assets" / "style.css").read_text(encoding="utf-8")
            app = (index_path.parent / "assets" / "app.js").read_text(encoding="utf-8")
            self.assertIn(".terminal-layout { display: grid;", style)
            self.assertIn(".article-grid { display: grid; grid-template-columns: 1fr;", style)
            self.assertIn("[hidden] { display: none !important; }", style)
            self.assertIn(".search-control", style)
            self.assertNotIn(".brand-mark", style)
            self.assertIn(".workspace-intro", style)
            self.assertIn(".terminal-sidebar", style)
            self.assertIn("system-ui", style)
            self.assertIn("prefers-reduced-motion", style)
            self.assertIn("prefers-reduced-transparency", style)
            self.assertIn(".site-credits { display: flex; align-items: center; gap: 7px; padding: 0; border: 0; background: transparent;", style)
            self.assertIn(".view-filter, .tag-filter { display: flex;", style)
            self.assertIn("var(--accent-soft)", style)
            self.assertIn("animation-timeline: scroll()", style)
            self.assertIn("@media (max-width: 900px)", style)
            self.assertIn("-webkit-line-clamp: 2", style)
            self.assertIn(".article-title-link", style)
            self.assertIn(".card-action", style)
            self.assertIn("article-search", app)
            self.assertIn("matchesQuery", app)
            self.assertIn("syncUrlState", app)
            self.assertIn("window.history.back()", app)
            self.assertIn("info-collector:reader-state:v1", app)
            self.assertIn("buildInfoCardMarkdown", app)
            self.assertIn("matchesView", app)
            self.assertIn("weeklyActivitySeries", app)
            self.assertIn("smoothChartPath", app)
            self.assertIn("buildWeeklyReviewMarkdown", app)

            blocked = next(item for item in articles if item["content_status"] == "source_blocked")
            blocked_page = (index_path.parent / "articles" / f"{blocked['slug']}.html").read_text(encoding="utf-8")
            self.assertIn('class="source-warning"', blocked_page)
            self.assertIn("译文尚未生成", blocked_page)
            self.assertIn("本页不计入可信译文库", blocked_page)

            missing = next(item for item in articles if item["content_status"] == "translation_missing")
            missing_page = (index_path.parent / "articles" / f"{missing['slug']}.html").read_text(encoding="utf-8")
            self.assertIn('data-content-status="translation_missing"', missing_page)
            self.assertIn("恢复状态", missing_page)
            self.assertIn("系统已阻止它继续伪装成完整译文", missing_page)
            self.assertIn('data-content-status="translation_missing"', index)
            self.assertIn("查看状态", index)

    def test_falls_back_to_summary_and_keywords_without_model_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            output = Path(tmp) / "translated"
            self.write_articles(output)
            article = reader.read_article(output / "fallback.md")
            self.assertIn("没有 frontmatter 摘要", article["summary"])
            self.assertIn("产品", article["tags"])

    def test_structured_profile_fields_require_privacy_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            body = '{"user_id":"user_042","hidden_profile":{"budget":"$200k","location":"Example"}}'
            self.assertEqual(reader.content_quality_status("", body), "privacy_review_required")

    def test_empty_markdown_and_empty_snapshot_page_require_translation_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            self.assertEqual(reader.content_quality_status("摘要存在", ""), "translation_missing")
            empty_page = '<div class="prose" id="article-content"></div>'
            self.assertEqual(reader.content_quality_status("摘要存在", empty_page), "translation_missing")
            filled_page = '<div class="prose" id="article-content"><p>正文存在。</p></div>'
            self.assertEqual(reader.content_quality_status("摘要存在", filled_page), "")

    def test_snapshot_html_body_is_preserved_inside_the_current_article_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            article = {
                "title": "保留的译文",
                "summary": "摘要",
                "source": "https://example.test/source",
                "article_id": "stable-snapshot",
                "published_at": "2026-07-12",
                "collected_at": "",
                "processed_at": "2026-07-12",
                "legacy_date": "",
                "authors": "",
                "tags": ["产品"],
                "content_status": "",
                "body": "",
                "body_html": "<h2>保留章节</h2><p>保留正文。</p>",
            }
            page = reader.render_article_page(article, "123456789abc")
            self.assertIn("<h2>保留章节</h2><p>保留正文。</p>", page)
            self.assertNotIn("&lt;h2&gt;保留章节", page)
            self.assertIn("data-return-library", page)
            self.assertIn('data-content-status=""', page)

    def test_public_excluded_article_is_removed_even_if_a_stale_page_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            output = Path(tmp) / "translated"
            output.mkdir()
            site_dir = Path(tmp) / "site"
            article_dir = site_dir / "articles"
            article_dir.mkdir(parents=True)
            excluded_slug = "article-8a0810a163f4"
            (article_dir / f"{excluded_slug}.html").write_text("stale public page", encoding="utf-8")
            reader.collect_articles = lambda _output: [{"slug": excluded_slug}]

            index_path, articles = reader.build_site(output, site_dir)

            self.assertEqual(articles, [])
            self.assertNotIn(excluded_slug, index_path.read_text(encoding="utf-8"))
            self.assertFalse((article_dir / f"{excluded_slug}.html").exists())

    def test_date_semantics_preserve_precision_and_never_impersonate_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            self.assertEqual(reader.normalize_published_at("2026-07-02"), "2026-07-02")
            self.assertEqual(reader.normalize_published_at("2026-07"), "2026-07")
            self.assertEqual(reader.normalize_published_at("2026"), "2026")
            self.assertEqual(reader.normalize_published_at("2026-02-31"), "")
            self.assertEqual(
                reader.normalize_published_at("", "https://www.geoffreylitt.com/2026/07/02/article"),
                "2026-07-02",
            )
            self.assertEqual(
                reader.normalize_published_at("2026-07", "https://www.geoffreylitt.com/2026/07/02/article"),
                "2026-07-02",
            )
            partial = {"published_at": "2026-07", "collected_at": "2026-07-11T13:30:00-04:00"}
            self.assertEqual(reader.published_label(partial), "发布于 2026-07（精确到月）")
            self.assertEqual(reader.activity_label(partial), "收录于 2026-07-11")
            unknown = {"published_at": "", "collected_at": "", "processed_at": "", "legacy_date": "2026-07-11"}
            self.assertEqual(reader.published_label(unknown), "发布时间未知")
            self.assertEqual(reader.activity_label(unknown), "整理于 2026-07-11")

    def test_collection_sort_uses_collected_then_processing_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            output = Path(tmp) / "translated"
            output.mkdir()
            for name, title, collected, processed in (
                ("old.md", "旧收录", "2026-07-01T10:00:00Z", "2026-07-12T10:00:00Z"),
                ("new.md", "新收录", "2026-07-11T10:00:00Z", "2026-07-11T10:01:00Z"),
                ("legacy.md", "旧格式", "", "2026-07-10T10:00:00Z"),
            ):
                (output / name).write_text(
                    "---\n"
                    f"title: {title}\n"
                    f"collected_at: {collected}\n"
                    f"processed_at: {processed}\n"
                    'summary: "测试摘要内容足够用于卡片。"\n'
                    'tags: ["智能体", "产品"]\n'
                    "---\n\n正文",
                    encoding="utf-8",
                )
            articles = reader.collect_articles(output)
            self.assertEqual([article["title"] for article in articles], ["新收录", "旧格式", "旧收录"])

    def test_main_writes_status_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            reader = import_reader(home)
            output = home / "translated"
            site = home / "public-reading"
            self.write_articles(output)
            reader.CONFIG_FILE.parent.mkdir(parents=True)
            reader.CONFIG_FILE.write_text(json.dumps({
                "outputDir": str(output),
                "readingSiteDir": str(site),
            }), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                first = reader.main([])
                second = reader.main([])
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            self.assertEqual(len(list((site / "articles").glob("*.html"))), 4)
            status = json.loads(reader.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(status["lastRun"]["outcome"], "success")
            self.assertEqual(status["lastRun"]["count"], 4)
            # Compare filesystem identity so Windows long paths and their 8.3
            # aliases do not create a false negative in CI.
            self.assertTrue(Path(status["siteIndex"]).samefile(site / "index.html"))


if __name__ == "__main__":
    unittest.main()

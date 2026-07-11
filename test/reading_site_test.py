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
            "source: https://example.test/agent\n"
            "published: 2026-07-10\n"
            "date: 2026-07-11T13:30\n"
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
            "source: https://example.test/fallback\n"
            "published: 2026-07-09\n"
            "---\n\n"
            "# 产品设计中的未知因素\n\n"
            "这是一段足够长的正文，用来验证没有 frontmatter 摘要时能够自动形成可读的卡片摘要，并在进入全文前帮助读者判断文章价值。\n\n"
            "## 设计方法\n\n通过用户访谈和原型发现未知问题。\n",
            encoding="utf-8",
        )

    def test_builds_index_and_article_pages_with_keywords_summary_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            output = Path(tmp) / "translated"
            self.write_articles(output)
            index_path, articles = reader.build_site(output)
            self.assertEqual(len(articles), 2)
            self.assertTrue(index_path.exists())
            index = index_path.read_text(encoding="utf-8")
            self.assertIn("文章情报库", index)
            self.assertIn('data-tag="智能体"', index)
            self.assertIn("本文讨论智能体时代", index)
            self.assertNotIn("搜索标题、摘要或关键词", index)
            self.assertNotIn("从关键词进入主题，从摘要判断价值", index)
            self.assertNotIn('id="article-search"', index)
            self.assertNotIn('class="search-box"', index)
            self.assertNotIn("data-search=", index)
            self.assertIn('id="result-count" aria-live="polite" aria-atomic="true"', index)
            self.assertIn("按关键词浏览", index)
            self.assertRegex(index, r'href="assets/style\.css\?v=[0-9a-f]{12}"')
            self.assertRegex(index, r'src="assets/app\.js\?v=[0-9a-f]{12}"')
            self.assertIn("Powered by", index)
            self.assertIn("@Madarame87", index)
            self.assertIn("@aswrise", index)
            self.assertEqual(index.count('href="https://github.com/Madarame87"'), 2)
            self.assertEqual(index.count('href="https://github.com/aswrise"'), 2)
            self.assertNotIn("@THEO", index)
            self.assertNotIn("@AQUA", index)
            self.assertNotIn("WINDOWS 11 · LOCAL-FIRST", index)
            self.assertNotIn("INFO COLLECTOR / READING DESK", index)
            self.assertIn('class="brand-signal"', index)
            self.assertNotIn('class="brand-mark"', index)
            self.assertEqual(index.count('class="article-card reveal" href="articles/'), 2)
            self.assertNotIn('role="article"', index)
            self.assertIn('class="card-meta"', index)
            self.assertIn('class="card-main"', index)
            self.assertIn('<time class="card-date" datetime="2026-07-10">2026-07-10</time>', index)
            self.assertIn('<time class="card-date" datetime="2026-07-09">2026-07-09</time>', index)
            self.assertNotIn("阅读中文全文", index)
            self.assertNotIn('class="card-foot"', index)
            self.assertNotIn("研究团队", index)
            article_path = index_path.parent / "articles" / f"{articles[0]['slug']}.html"
            article = article_path.read_text(encoding="utf-8")
            self.assertIn("EXECUTIVE SUMMARY", article)
            self.assertIn("先读结论", article)
            self.assertIn("CHINESE TRANSLATION", article)
            self.assertIn("访问文章原文", article)
            self.assertIn("作者 研究团队", article)
            self.assertIn('href="https://example.test/agent" target="_blank" rel="noopener noreferrer"', article)
            self.assertRegex(article, r'href="\.\./assets/style\.css\?v=[0-9a-f]{12}"')
            self.assertRegex(article, r'src="\.\./assets/app\.js\?v=[0-9a-f]{12}"')
            self.assertLess(article.index("EXECUTIVE SUMMARY"), article.index("CHINESE TRANSLATION"))
            self.assertLess(article.index("CHINESE TRANSLATION"), article.index("ORIGINAL SOURCE"))
            self.assertNotIn("这段摘要不应在正文中重复", article)
            self.assertNotIn("<script>alert", article)
            self.assertIn("&lt;script&gt;", article)
            self.assertTrue((index_path.parent / "assets" / "style.css").exists())
            self.assertTrue((index_path.parent / "assets" / "app.js").exists())
            style = (index_path.parent / "assets" / "style.css").read_text(encoding="utf-8")
            app = (index_path.parent / "assets" / "app.js").read_text(encoding="utf-8")
            self.assertIn(".article-grid { display: grid; grid-template-columns: 1fr;", style)
            self.assertIn("[hidden] { display: none !important; }", style)
            self.assertNotIn(".search-box", style)
            self.assertNotIn(".brand-mark", style)
            self.assertIn(".library-hero { position: relative; min-height: 320px; padding: 76px 0 58px; border: 0; background: transparent;", style)
            self.assertIn(".site-credits { display: flex; align-items: center; gap: 11px; padding: 0; border: 0; background: transparent;", style)
            self.assertIn(".tag-filter { position: relative; min-height: 40px; padding: 8px 0 7px; border: 0;", style)
            self.assertIn("var(--aquatic-soft)", style)
            self.assertIn("text-overflow: ellipsis", style)
            self.assertIn(".card-meta time", style)
            self.assertNotIn("article-search", app)
            self.assertIn("card.hidden = !show", app)
            self.assertIn("applyFilters();", app)

    def test_falls_back_to_summary_and_keywords_without_model_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            output = Path(tmp) / "translated"
            self.write_articles(output)
            article = reader.read_article(output / "fallback.md")
            self.assertIn("没有 frontmatter 摘要", article["summary"])
            self.assertIn("产品", article["tags"])

    def test_date_label_falls_back_when_published_date_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = import_reader(Path(tmp))
            self.assertEqual(reader.date_label({
                "published": "2026-07",
                "collected": "2026-07-11T13:30:00-04:00",
            }), "2026-07-11")
            self.assertEqual(reader.date_label({"published": "", "collected": ""}), "已收录")

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
            self.assertEqual(len(list((site / "articles").glob("*.html"))), 2)
            status = json.loads(reader.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(status["lastRun"]["outcome"], "success")
            self.assertEqual(status["lastRun"]["count"], 2)
            self.assertEqual(status["siteIndex"], str(site / "index.html"))


if __name__ == "__main__":
    unittest.main()

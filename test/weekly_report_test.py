import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "flows" / "generate-weekly-report.py"


def import_weekly(home):
    old_home = os.environ.get("INFO_COLLECTOR_HOME")
    os.environ["INFO_COLLECTOR_HOME"] = str(home)
    try:
        spec = importlib.util.spec_from_file_location("weekly_report_under_test", FLOW_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old_home is None:
            os.environ.pop("INFO_COLLECTOR_HOME", None)
        else:
            os.environ["INFO_COLLECTOR_HOME"] = old_home


def write_report(path, results):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "reportId": path.stem,
        "processingType": "translate",
        "results": results,
    }, ensure_ascii=False), encoding="utf-8")


class WeeklyReportTest(unittest.TestCase):
    def create_fixture(self, home):
        weekly = import_weekly(home)
        spool = home / ".info-collector"
        processed = spool / "inbox" / "processed"
        output = home / "translated"
        output.mkdir()
        (spool / "config.json").parent.mkdir(parents=True)
        (spool / "config.json").write_text(json.dumps({
            "outputDir": str(output),
        }), encoding="utf-8")

        fallback_md = output / "fallback.md"
        fallback_md.write_text(
            "---\n"
            "title: 从文件读取的标题\n"
            "source: https://example.test/b\n"
            "published: 2026-07-10\n"
            "summary: \"从 Markdown frontmatter 补回的摘要。\"\n"
            "tags: [\"智能体\", \"产品\"]\n"
            "---\n\n# 正文",
            encoding="utf-8",
        )

        write_report(processed / "translate-1.json", [
            {
                "url": "https://example.test/a",
                "status": "done",
                "processedAt": "2026-07-06T12:00:00Z",
                "meta": {"title": "旧标题", "summary": "旧摘要", "tags": ["模型评估"]},
            },
            {
                "url": "https://example.test/outside",
                "status": "done",
                "processedAt": "2026-06-30T12:00:00Z",
                "meta": {"title": "周外", "summary": "周外摘要", "tags": ["产品"]},
            },
        ])
        write_report(processed / "translate-2.json", [
            {
                "url": "https://example.test/a",
                "status": "done",
                "processedAt": "2026-07-08T12:00:00Z",
                "meta": {
                    "title": "最新标题",
                    "summary": "最新摘要",
                    "tags": ["智能体", "模型评估"],
                },
            },
            {
                "url": "https://example.test/b",
                "status": "done",
                "processedAt": "2026-07-11T12:00:00Z",
                "meta": {"savedTo": str(fallback_md)},
            },
            {
                "url": "https://example.test/failed",
                "status": "failed",
                "processedAt": "2026-07-11T13:00:00Z",
                "meta": {"summary": "失败摘要", "tags": ["产品"]},
            },
        ])
        return weekly, output

    def test_collects_current_week_deduplicates_and_reads_markdown_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly, _output = self.create_fixture(Path(tmp))
            articles = weekly.collect_articles(
                dt.date(2026, 7, 6),
                dt.date(2026, 7, 12),
                timezone=dt.timezone.utc,
            )
            self.assertEqual([article["url"] for article in articles], [
                "https://example.test/a",
                "https://example.test/b",
            ])
            self.assertEqual(articles[0]["title"], "最新标题")
            self.assertEqual(articles[0]["summary"], "最新摘要")
            self.assertEqual(articles[1]["title"], "从文件读取的标题")
            self.assertEqual(articles[1]["tags"], ["智能体", "产品"])

    def test_render_has_ranked_themes_groups_and_daily_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly, _output = self.create_fixture(Path(tmp))
            articles = weekly.collect_articles(
                dt.date(2026, 7, 6),
                dt.date(2026, 7, 12),
                timezone=dt.timezone.utc,
            )
            markdown = weekly.render_weekly_report(
                articles,
                dt.date(2026, 7, 6),
                dt.date(2026, 7, 12),
                generated_at=dt.datetime(2026, 7, 11, 14, 0, tzinfo=dt.timezone.utc),
            )
            self.assertIn("article_count: 2", markdown)
            self.assertIn("1. **智能体** — 2 篇", markdown)
            self.assertIn("## 按主题归类", markdown)
            self.assertIn("### 模型评估（1）", markdown)
            self.assertIn("## 每日收录", markdown)
            self.assertIn("### 2026-07-11", markdown)
            self.assertIn("从 Markdown frontmatter 补回的摘要", markdown)

    def test_main_writes_deterministic_report_and_success_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            weekly, output = self.create_fixture(Path(tmp))
            with contextlib.redirect_stdout(io.StringIO()):
                code = weekly.main(["--week-start", "2026-07-06"])
                second_code = weekly.main(["--week-start", "2026-07-06"])
            self.assertEqual(code, 0)
            self.assertEqual(second_code, 0)
            report = output / "周报" / "技术动态周报-2026-07-06.md"
            self.assertTrue(report.exists())
            self.assertEqual(len(list((output / "周报").glob("*.md"))), 1)
            self.assertIn("本周共收录 2 篇", report.read_text(encoding="utf-8"))
            status = json.loads(weekly.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertEqual(status["lastRun"]["outcome"], "success")
            self.assertEqual(status["lastRun"]["count"], 2)
            self.assertEqual(status["latestReport"], str(report))


if __name__ == "__main__":
    unittest.main()

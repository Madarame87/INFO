#!/usr/bin/env python3
"""Generate one deterministic Monday-Sunday digest from completed translations."""

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

try:
    from info_collector_platform import acquire_lock, release_lock, user_home
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from info_collector_platform import acquire_lock, release_lock, user_home


HOME = user_home()
SPOOL = HOME / ".info-collector"
CONFIG_FILE = SPOOL / "config.json"
INBOX_DIR = SPOOL / "inbox"
PROCESSED_DIR = INBOX_DIR / "processed"
STATUS_FILE = SPOOL / "state" / "weekly-report-status.json"
LOCK_FILE = SPOOL / "state" / "weekly-report.lock"
LOG_FILE = SPOOL / "state" / "weekly-report.log"
TRIGGER = "manual"


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
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_json(path, value):
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=1))


def update_status(patch):
    status = load_json(STATUS_FILE, {})
    status.update(patch)
    atomic_write_json(STATUS_FILE, status)


def parse_iso(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        return None


def week_bounds(week_start=None, today=None):
    if week_start:
        start = dt.date.fromisoformat(str(week_start))
    else:
        today = today or dt.datetime.now().astimezone().date()
        start = today - dt.timedelta(days=today.weekday())
    return start, start + dt.timedelta(days=6)


def parse_scalar(raw):
    raw = str(raw or "").strip()
    if not raw:
        return ""
    try:
        value = json.loads(raw)
        return value if isinstance(value, str) else str(value)
    except json.JSONDecodeError:
        return raw.strip("'\"")


def parse_markdown_meta(path):
    if not path:
        return {}
    try:
        text = Path(os.path.expanduser(path)).read_text(encoding="utf-8")
    except OSError:
        return {}
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        return {}
    frontmatter = match.group(1)

    def field(name):
        found = re.search(rf"(?m)^{name}:\s*(.*)$", frontmatter)
        return parse_scalar(found.group(1)) if found else ""

    tags = []
    tags_line = re.search(r"(?m)^tags:\s*(.*)$", frontmatter)
    if tags_line:
        raw = tags_line.group(1).strip()
        try:
            value = json.loads(raw)
            tags = value if isinstance(value, list) else []
        except json.JSONDecodeError:
            tags = [item.strip(" '\"") for item in re.split(r"[,，]", raw.strip("[]"))]
    return {
        "title": field("title"),
        "summary": field("summary"),
        "published": field("published"),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
    }


def report_files():
    paths = []
    for directory in (INBOX_DIR, PROCESSED_DIR):
        if directory.is_dir():
            paths.extend(directory.glob("translate-*.json"))
    return sorted(paths)


def collect_articles(start, end, timezone=None):
    timezone = timezone or dt.datetime.now().astimezone().tzinfo
    newest_by_url = {}
    for path in report_files():
        report = load_json(path, {})
        for result in report.get("results") or []:
            if result.get("status") != "done" or not result.get("url"):
                continue
            processed = parse_iso(result.get("processedAt"))
            if not processed:
                continue
            local_date = processed.astimezone(timezone).date()
            if local_date < start or local_date > end:
                continue
            meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
            file_meta = parse_markdown_meta(meta.get("savedTo"))
            summary = str(meta.get("summary") or file_meta.get("summary") or "").strip()
            tags = meta.get("tags") or file_meta.get("tags") or []
            if not isinstance(tags, list):
                tags = []
            tags = list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip()))
            if not summary or not tags:
                continue
            saved_to = str(meta.get("savedTo") or "")
            fallback_title = Path(saved_to).stem if saved_to else result["url"]
            article = {
                "url": result["url"],
                "title": str(meta.get("title") or file_meta.get("title") or fallback_title),
                "summary": summary,
                "tags": tags,
                "published": str(meta.get("published") or file_meta.get("published") or ""),
                "processedAt": processed,
                "localDate": local_date,
                "savedTo": saved_to,
            }
            previous = newest_by_url.get(article["url"])
            if not previous or article["processedAt"] > previous["processedAt"]:
                newest_by_url[article["url"]] = article
    return sorted(newest_by_url.values(), key=lambda item: item["processedAt"])


def yaml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def markdown_link_text(value):
    return str(value).replace("[", "［").replace("]", "］")


def render_weekly_report(articles, start, end, generated_at=None):
    generated_at = generated_at or dt.datetime.now().astimezone()
    title = f"技术动态周报 {start.isoformat()} 至 {end.isoformat()}"
    lines = [
        "---",
        f"title: {yaml_string(title)}",
        f"week_start: {start.isoformat()}",
        f"week_end: {end.isoformat()}",
        f"generated: {generated_at.isoformat(timespec='minutes')}",
        f"article_count: {len(articles)}",
        "---",
        "",
        f"# {title}",
        "",
        f"> 本周共收录 {len(articles)} 篇已完成摘要与标签提炼的文章。",
        "",
    ]
    if not articles:
        lines.extend(["本周暂无符合条件的文章。", ""])
        return "\n".join(lines)

    counts = Counter(tag for article in articles for tag in article["tags"])
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    lines.extend(["## 主题排行", ""])
    for index, (tag, count) in enumerate(ranked, 1):
        lines.append(f"{index}. **{tag}** — {count} 篇")

    lines.extend(["", "## 按主题归类", ""])
    for tag, count in ranked:
        lines.extend([f"### {tag}（{count}）", ""])
        tagged = [article for article in articles if tag in article["tags"]]
        for article in sorted(tagged, key=lambda item: item["processedAt"], reverse=True):
            lines.append(
                f"- [{markdown_link_text(article['title'])}]({article['url']}) — {article['summary']}"
            )
        lines.append("")

    by_date = defaultdict(list)
    for article in articles:
        by_date[article["localDate"]].append(article)
    lines.extend(["## 每日收录", ""])
    for day in sorted(by_date, reverse=True):
        lines.extend([f"### {day.isoformat()}", ""])
        for article in sorted(by_date[day], key=lambda item: item["processedAt"], reverse=True):
            lines.extend([
                f"- [{markdown_link_text(article['title'])}]({article['url']})",
                f"  - 标签：{'、'.join(article['tags'])}",
                f"  - 摘要：{article['summary']}",
            ])
        lines.append("")
    return "\n".join(lines)


def generate_weekly_report(week_start=None, today=None, now=None):
    cfg = load_json(CONFIG_FILE, {})
    output_dir = Path(os.path.expanduser(cfg.get("outputDir") or str(HOME / "Documents" / "InfoCollector")))
    start, end = week_bounds(week_start=week_start, today=today)
    articles = collect_articles(start, end)
    generated_at = now or dt.datetime.now().astimezone()
    markdown = render_weekly_report(articles, start, end, generated_at=generated_at)
    path = output_dir / "周报" / f"技术动态周报-{start.isoformat()}.md"
    atomic_write_text(path, markdown)
    return path, articles, start, end


def main(argv=None):
    configure_text_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-start", help="Monday in YYYY-MM-DD; defaults to current week")
    args = parser.parse_args(argv)
    lock_fd = acquire_lock(LOCK_FILE)
    if lock_fd is None:
        log("周报流程已在运行，跳过")
        return 0
    started = dt.datetime.now().astimezone()
    last_run = {"startedAt": started.isoformat(timespec="seconds"), "trigger": TRIGGER, "outcome": "running"}
    update_status({"lastRun": last_run})
    try:
        path, articles, start, end = generate_weekly_report(week_start=args.week_start)
        outcome = "success" if articles else "empty"
        last_run.update({
            "outcome": outcome,
            "finishedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "count": len(articles),
            "weekStart": start.isoformat(),
            "weekEnd": end.isoformat(),
            "latestReport": str(path),
        })
        update_status({"lastRun": last_run, "latestReport": str(path)})
        log(f"周报已生成：{path}（{len(articles)} 篇）")
        return 0
    except Exception as exc:
        last_run.update({
            "outcome": "error",
            "finishedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "error": str(exc)[:300],
        })
        update_status({"lastRun": last_run})
        log(f"周报生成失败：{exc}")
        return 1
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())

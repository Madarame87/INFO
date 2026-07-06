---
name: podcast-digest
description: 根据 Info Collector podcast flow 的 workdir 生成播客三件套：TLDR、深度总结、中文全文稿。
---

# Podcast Digest

输入只传一个 workdir 路径。不要重新询问。读取：

- `source.md`：既有网页文稿或 YouTube transcript 原文。可能不存在。
- `meta.json`：URL、标题、来源元数据、输出目录、`resultFile`。

输出只以 `meta.json` 里的 `resultFile` 为准。stdout 不算成功信号。

## 1. 补 transcript（仅按需）

如果 `source.md` 不存在，且 `meta.json` 里有
`resolutionStatus=needs_browser_resolution`：

1. 用 Browser Use / Chrome 绑定用户现有且已登录的 Chrome。
2. 打开 `mediaSource`。
3. 读取 YouTube Transcript panel，或页面可用时点击 `Copy Transcript`。
4. 把 transcript 写入 `source.md`。
5. 更新 `meta.json`：
   - `transcriptSource: youtube_unknown_caption`
   - `transcriptProvider: chrome_transcript_ui`
   - `captionKind: unknown`
   - `sourceReliability: unknown_caption`
   - `transcriptLanguage: zh|en`

禁止杀掉或重启用户 Chrome，禁止创建临时 `--user-data-dir` profile。
无法绑定现有登录态时，写：

```json
{"status":"failed","error":"youtube-login-required"}
```

绑定成功但页面没有 transcript 时，写：

```json
{"status":"failed","error":"youtube-transcript-unavailable"}
```

## 2. 日期

运行：

```bash
date +%Y-%m-%dT%H:%M
```

frontmatter 的 `date` 必须使用这个真实输出。

## 3. 生成三件套

输出目录是 `meta.json.outputDir`。确保目录存在。

生成三个独立 Markdown 文件：

- `<中文标题>（TLDR）.md`
- `<中文标题>（深度总结）.md`
- `<中文标题>（全文稿）.md`

三个文件都写 frontmatter：

```yaml
---
title: <中文标题>
source: <原文 URL>
published: <YYYY-MM-DD，可空>
date: <date 命令输出>
authors: <作者，可空>
category: 播客
duration: <时长，可空>
transcript_source: webpage_transcript | youtube_manual_caption | youtube_auto_caption | youtube_unknown_caption
transcript_provider: defuddle | firecrawl_youtube | yt_dlp | chrome_transcript_ui
caption_kind: manual | auto | unknown
transcript_language: zh | en
source_reliability: edited | manual_caption | auto_caption | unknown_caption
---
```

### TLDR

约 500 汉字（450-650），一段式核心结论。文件内链接：

```markdown
相关：[[<中文标题>（深度总结）]] / [[<中文标题>（全文稿）]]
```

### 深度总结

约 7000 汉字（6000-8000）。保留论证链、关键数据、金句引用。全文稿不足
1.2 万汉字时，压缩到全文 50-60%，不硬凑长度。

### 全文稿

- 源是中文：清理原文，保留说话人结构，去广告推广，不改写不删减。
- 源是英文：完整翻译成中文。分段翻译、逐段追加，避免输出截断。
- 人名/术语首次出现保留英文原文。

完成前自查：全文稿段落数与原文一致或有明确合并理由，无截断。

## 4. result.json

成功时写：

```json
{
  "status": "ok",
  "tldrFile": "/absolute/path/标题（TLDR）.md",
  "deepSummaryFile": "/absolute/path/标题（深度总结）.md",
  "transcriptFile": "/absolute/path/标题（全文稿）.md"
}
```

任何失败都写：

```json
{"status":"failed","error":"<error-code>"}
```

允许的 error code：
`youtube-login-required`、`youtube-transcript-unavailable`、`pi-failed`。

v1 不同步 Notion，不下载音频，不做语音转写。

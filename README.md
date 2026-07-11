# Info Collector

把 Chrome 书签变成本机处理流水线：文章放进「收藏文章」自动翻译成带摘要与
标签的中文 Markdown；播客 / YouTube 访谈放进「收藏播客」自动生成 TLDR、深度总结和
全文稿。处理状态在扩展的 Dashboard 里一目了然（待处理 → 处理中 → 已完成），
跨设备同步。

Dashboard 长这样：状态卡片、流水线运行时间、逐篇文章的状态与操作按钮：

![Info Collector Dashboard：文章处理台账，显示待处理/已完成状态、来源、更新时间和操作按钮](docs/images/dashboard.png)

## 快速上手（普通用户）

### Windows 11

Windows 第一版支持 Chrome Dashboard 手动触发文章翻译，不安装定时任务。运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

完整安装与阶段 1 验收步骤见 [SETUP-WINDOWS.md](SETUP-WINDOWS.md)。

### macOS

文章翻译只需要一个 DeepSeek API Key（也支持 Anthropic API Key），三步装好，全程约 10 分钟：

1. 获取 API Key
2. Chrome 加载扩展
3. 终端跑 `bash scripts/setup.sh`

**手把手图文指南（写给非技术用户）：[SETUP.md](SETUP.md)**

也可以让 AI 替你装：把项目文件夹交给 AI 编程助手，说「按 SETUP.md 装好」。
安装脚本支持非交互模式（`INFO_COLLECTOR_ENGINE=deepseek INFO_COLLECTOR_API_KEY=sk-... bash scripts/setup.sh`），
装完可用 `translate-flow.py --check` 自检。

播客流是可选的，需要本机已安装 `pi` CLI。装好文章流后再运行：

```bash
bash scripts/setup-pi-podcast-flow.sh
```

之后把 YouTube / 播客页面收藏到 Chrome 书签文件夹「收藏播客」，Dashboard 里选
`播客 (podcast)` 可以查看状态并点「立即处理」。

## 工作原理

```
Chrome 书签「收藏文章」 → 扩展（队列 + Dashboard） ⇄ 文件桥 ⇄ 翻译流（DeepSeek/Claude API）
                                                              ↓
                                                     ~/Documents/InfoCollector/*.md

Chrome 书签「收藏播客」 → 扩展（队列 + Dashboard） ⇄ 文件桥 ⇄ 播客流（transcript + pi）
                                                              ↓
                                                     Obsidian「播客收集」三件套
```

- **扩展**（MV3）是唯一事实来源：从书签只读导入，状态存 `chrome.storage.sync`
  跨设备同步；书签本身永远不会被修改。
- **翻译流**是普通本机脚本，经 `~/.info-collector/` 下的文件契约与扩展
  交换数据（outbox 待处理清单 / inbox 完成报告），由 launchd 每小时调度，
  也可在 Dashboard 里点「▶ 立即处理」立刻触发。
- 内置翻译流支持 DeepSeek API 和 Claude API。DeepSeek 路径会优先用本机
  `defuddle parse --json` 提取正文与 metadata，再调 OpenAI-compatible
  `/chat/completions`；未安装 defuddle 时退回内置简易抓取器。Claude 路径继续
  使用 Anthropic Messages API 的服务端 `web_fetch`。译文 frontmatter 与完成报告
  都包含一段限长摘要和 2–5 个规范化标签；Dashboard 可按标签汇总、筛选同类文章。
- 播客流由 `scripts/setup-pi-podcast-flow.sh` 注册，消费 `podcast` 队列；
  YouTube 会优先复用已有字幕 / transcript，记录频道、频道链接和发布日期，再交给
  `podcast-digest` Pi skill 写入 Obsidian「播客收集」。

## 开发者

- 领域语言：[CONTEXT.md](CONTEXT.md) · 总体设计：[docs/design.md](docs/design.md)
  · 关键决策：[docs/adr/](docs/adr/)
- 目录：`extension/`（MV3 扩展）· `host/`（native messaging 文件桥）·
  `flows/`（处理流脚本）· `templates/`（launchd 模板）· `scripts/`（安装）·
  `test/`（`npm test`，node --test）
- 配置文件：`~/.info-collector/config.json`（provider / apiKey / baseUrl / model / outputDir）·
  `~/.info-collector/flows.json`（流程注册表，见 ADR 0004）
- 内置处理类型：`translate`（书签「收藏文章」，自动入队）· `podcast`
  （书签「收藏播客」，去重后入队）。

### 新增一条处理流（文稿、书籍……）

1. Dashboard → 设置 → 新增处理类型（如 `transcript`）。
2. 写脚本：读 `~/.info-collector/outbox/transcript.json`，处理完写报告到
   `~/.info-collector/inbox/<reportId>.json`（原子写：临时文件 + rename）：

```json
{ "reportId": "transcript-20260705T120000-ab12", "processingType": "transcript",
  "results": [ { "url": "…", "status": "done", "processedAt": "…",
    "meta": { "summary": "…", "tags": ["智能体", "模型评估"] } } ] }
```

`status` 支持 `processing`（认领，显示「处理中」）/ `done` / `failed`。
`flows/translate-claude-api.py` 是完整参考实现（含状态文件、锁、认领报告）。

3. 想要 Dashboard 的「▶ 立即处理」按钮和运行状态，往
   `~/.info-collector/flows.json` 加一条注册：
   `{"command": [...启动命令, "--manual"], "lockFile": "…", "intervalSeconds": 3600}`。

## 平台支持

- Windows 11：文章流水线支持手动触发；不安装计划任务，播客/Pi 流暂不支持。
- macOS：保留原有 launchd 自动调度与文章/可选播客安装方式。

Chrome 需要
以「加载已解压的扩展程序」方式安装（manifest 内置固定 key，所有设备
上扩展 ID 一致：`fmdbamjmoabmcggjfgeopaijnbjkjbhm`）。

<p align="center">
  <img src="docs/images/readme-hero.svg" alt="Info Collector — Local Intelligence OS" width="100%">
</p>

<p align="center">
  <a href="SETUP-WINDOWS.md"><img alt="Windows 11" src="https://img.shields.io/badge/Windows_11-supported-2E8B67?style=flat-square"></a>
  <img alt="Chrome Extension" src="https://img.shields.io/badge/Chrome-Manifest_V3-C65F3D?style=flat-square">
  <img alt="Local first" src="https://img.shields.io/badge/data-local--first-25221E?style=flat-square">
  <img alt="Node tests" src="https://img.shields.io/badge/Node_tests-38_passing-2E8B67?style=flat-square">
  <img alt="Python tests" src="https://img.shields.io/badge/Python_tests-23_passing-2E8B67?style=flat-square">
</p>

<p align="center">
  <strong>收藏文章 → 抓取正文 → 翻译提炼 → 自动归类 → 生成技术动态周报</strong>
</p>

Info Collector 是一套运行在本机的个人技术情报工作台。你只需要把文章加入 Chrome 的「收藏文章」书签文件夹，系统就会把它送入处理队列，生成带有中文翻译、摘要和标签的 Markdown，并在 Dashboard 中持续记录状态。每周还可以一键聚合主题排行、同类文章与收录日历。

它不是另一个“稍后读”列表。它把零散阅读转化为一条可追踪、可检索、可复用的研究工作流。

## 产品界面

<p align="center">
  <img src="docs/images/dashboard.png" alt="Info Collector Windows Dashboard：处理流水线、运行状态和文章情报库" width="100%">
</p>

<details>
<summary><strong>查看文章情报库完整列表</strong></summary>
<br>
<p align="center">
  <img src="docs/images/dashboard-library.png" alt="Info Collector 文章情报库：摘要、标签、状态与操作" width="100%">
</p>
</details>

## 它能做什么

| 能力 | 结果 |
|---|---|
| 书签即入口 | 只读导入 Chrome 书签，不修改原始书签 |
| AI 翻译与提炼 | 输出中文 Markdown、限长摘要和 2–5 个规范化标签 |
| 状态可追踪 | 在 Dashboard 查看待处理、处理中、失败、完成与归档状态 |
| 同类信息归档 | 按标签聚合和筛选文章，快速识别持续出现的技术主题 |
| 一键生成周报 | 汇总本周主题排行、文章分组和每日收录日历 |
| 本地优先 | API Key、处理队列和 Markdown 结果保存在本机 |
| 跨设备状态同步 | 使用 `chrome.storage.sync` 同步轻量任务状态 |

## 从收藏到周报

```text
Chrome「收藏文章」
        │
        ▼
扩展只读导入 ──→ 任务队列 / Dashboard
        │
        ▼
Native Messaging 文件桥
        │
        ▼
正文抓取 ──→ DeepSeek / Claude ──→ 翻译 + Summary + Tags
        │
        ├──→ ~/Documents/InfoCollector/*.md
        │
        └──→ 周报/技术动态周报-*.md
```

扩展是任务状态的唯一事实来源。本地处理流通过 `~/.info-collector/` 下的 outbox / inbox 文件契约与扩展交换数据，因此浏览器界面、模型调用与 Markdown 产物彼此解耦。

## Windows 11 快速开始

### 1. 下载并进入项目

```powershell
git clone https://github.com/Madarame87/INFO.git
cd INFO
```

> 当前 Windows 功能正在 `agent/windows-port` / Draft PR #1 中验收。合并前体验最新版时，请先切换该分支：`git switch agent/windows-port`。

### 2. 运行安装器

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

安装器会引导你设置模型、API Key、输出目录以及 Chrome 扩展。完整截图式步骤与故障排查见 **[Windows 安装指南](SETUP-WINDOWS.md)**。

### 3. 收藏并处理文章

1. 在 Chrome 中创建「收藏文章」书签文件夹。
2. 把想处理的文章保存到该文件夹。
3. 打开 Info Collector Dashboard，依次点击「导入书签」和「桥接同步」。
4. 点击「立即处理」，完成后查看摘要、标签和本地 Markdown。

## 当前支持范围

| 平台 / 流程 | 状态 | 说明 |
|---|---:|---|
| Windows 11 · 文章处理 | ✅ 已验证 | Dashboard 手动触发，真实文章端到端通过 |
| Windows 11 · Summary / Tags | ✅ 已验证 | 展示、筛选、同步与异常输出修复已覆盖 |
| Windows 11 · 技术周报 | ✅ MVP | 本地确定性聚合，不重复调用模型 |
| Windows 11 · 播客处理 | ◻︎ 计划中 | 界面保留入口，暂未接入 Windows 后端 |
| macOS · 文章处理 | ✅ 保留 | 支持原有 launchd 定时调度 |
| macOS · 播客处理 | ✅ 可选 | 需要本机安装 `pi` CLI |

## 为什么做这个项目

技术信息真正的瓶颈通常不是“找不到文章”，而是读过之后没有形成可以复用的结构。收藏夹会不断增长，重要观点却很难再次被找到，也难以看出某个主题在一周内是否持续升温。

Info Collector 试图补上中间这一层：保留原文入口，同时生成统一的中文摘要与标签，再把个人阅读记录压缩成可回顾的技术动态周报。它既是个人知识工作流，也是一种轻量的行业技术雷达。

## 技术结构

```text
extension/   Chrome MV3 扩展、Dashboard、任务队列与同步
host/        Windows / macOS Native Messaging 文件桥
flows/       文章翻译、摘要标签、播客和周报生成流程
scripts/     Windows 与 macOS 安装、自检和测试入口
test/        Node + Python 回归测试
docs/        架构设计、ADR 与平台迁移记录
```

- 架构说明：[docs/design.md](docs/design.md)
- 领域语言：[CONTEXT.md](CONTEXT.md)
- 关键决策：[docs/adr/](docs/adr/)
- Windows 迁移清单：[docs/windows-porting-checklist.md](docs/windows-porting-checklist.md)

## 开发与验证

```powershell
npm.cmd test
```

当前回归基线：**38 个 Node 测试 + 23 个 Python 测试全部通过**，并覆盖 URL 归一化、队列状态机、跨端同步、摘要标签、异常模型输出、周报聚合、Windows UTF-8 输出和页面 ID 契约。

## Roadmap

- [x] Windows Native Host 与安装器
- [x] 真实文章抓取、翻译与 Markdown 输出
- [x] Summary / Tags 提取、展示与同类筛选
- [x] 本地确定性技术动态周报
- [ ] 扩大真实文章验收样本并完成阶段门禁
- [ ] Windows 播客 / YouTube 处理流
- [ ] 专家、机构、事实与观点的结构化情报层

---

<p align="center">
  <sub>Local-first · Windows-native · Built for repeatable intelligence work</sub>
</p>

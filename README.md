<p align="center">
  <img src="docs/images/readme-hero.svg" alt="Info Collector — Local Intelligence OS" width="100%">
</p>

<p align="center">
  <a href="SETUP-WINDOWS.md"><img alt="Windows 11" src="https://img.shields.io/badge/Windows_11-supported-2E8B67?style=flat-square"></a>
  <img alt="Chrome Extension" src="https://img.shields.io/badge/Chrome-Manifest_V3-C65F3D?style=flat-square">
  <img alt="Local first" src="https://img.shields.io/badge/data-local--first-25221E?style=flat-square">
  <img alt="Node tests" src="https://img.shields.io/badge/Node_tests-38_passing-2E8B67?style=flat-square">
  <img alt="Python tests" src="https://img.shields.io/badge/Python_tests-26_passing-2E8B67?style=flat-square">
</p>

<p align="center">
  <strong>收藏文章 → 抓取正文 → 翻译提炼 → 自动归类 → 生成技术动态周报</strong>
</p>

Info Collector 是一套运行在本机的个人技术情报工作台。你只需要把文章加入 Chrome 的「收藏文章」书签文件夹，系统就会把它送入处理队列，生成带有中文翻译、摘要和标签的 Markdown，并在 Dashboard 中持续记录状态。处理后的文章可以一键生成静态阅读库，每周还可以聚合主题排行、同类文章与收录日历。

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

<p align="center">
  <img src="docs/images/readme-capabilities.svg" alt="Info Collector 六项核心能力：收藏入队、AI 翻译提炼、状态追踪、标签化情报库、本地 Markdown 和技术动态周报" width="100%">
</p>

## 从收藏到周报

<p align="center">
  <img src="docs/images/readme-workflow.svg" alt="Info Collector 技术情报流水线：收藏文章、导入桥接、翻译提炼、文章情报库、技术动态周报" width="100%">
</p>

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
5. 点击「生成并打开阅读库」，浏览关键词、Summary 与完整中文译文。

## 静态文章阅读前台

阅读站由本地 Markdown 自动生成，默认输出到：

```text
%USERPROFILE%\Documents\InfoCollector\阅读站\index.html
```

索引页提供关键词、全文搜索、摘要预览和响应式文章卡片；单篇页面依次展示关键词、Summary、中文译文、章节目录、阅读进度和原文链接。它不需要数据库，也不会上传 API Key 或私人阅读数据。

## 当前支持范围

<p align="center">
  <img src="docs/images/readme-scope.svg" alt="Info Collector Windows 11 已验证范围：原生桥接、文章情报处理和技术动态周报" width="100%">
</p>

这个仓库的产品目标明确限定为 **Windows 11 技术文章情报工作流**：从 Chrome 收藏进入队列，到本机生成结构化文章、静态阅读站与技术动态周报。

## 为什么做这个项目

技术信息真正的瓶颈通常不是“找不到文章”，而是读过之后没有形成可以复用的结构。收藏夹会不断增长，重要观点却很难再次被找到，也难以看出某个主题在一周内是否持续升温。

Info Collector 试图补上中间这一层：保留原文入口，同时生成统一的中文摘要与标签，再把个人阅读记录压缩成可回顾的技术动态周报。它既是个人知识工作流，也是一种轻量的行业技术雷达。

## 技术结构

<p align="center">
  <img src="docs/images/readme-architecture.svg" alt="Info Collector 技术结构：Chrome MV3 扩展、Windows 文件桥、文章处理流和本地 Markdown 产物" width="100%">
</p>

- 架构说明：[docs/design.md](docs/design.md)
- 领域语言：[CONTEXT.md](CONTEXT.md)
- 关键决策：[docs/adr/](docs/adr/)
- Windows 迁移清单：[docs/windows-porting-checklist.md](docs/windows-porting-checklist.md)

## 开发与验证

```powershell
npm.cmd test
```

当前回归覆盖 URL 归一化、队列状态机、跨端同步、摘要标签、异常模型输出、周报聚合、Windows UTF-8 输出和页面 ID 契约。

## Roadmap · 已完成

<p align="center">
  <img src="docs/images/readme-validation.svg" alt="Info Collector 验证结果与已完成 Roadmap：38 个 Node 测试、26 个 Python 测试、Windows Native Host 与五项已交付能力" width="100%">
</p>

---

<p align="center">
  <sub>Local-first · Windows-native · Built for repeatable intelligence work</sub>
</p>

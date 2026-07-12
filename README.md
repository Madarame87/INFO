<p align="center">
  <img src="docs/images/readme-hero.svg" alt="Info Collector — Personal Technology Intelligence" width="100%">
</p>

<p align="center">
  <a href="https://madarame87.github.io/INFO/"><strong>在线体验文章情报库 →</strong></a>
</p>

<p align="center">
  <a href="SETUP-WINDOWS.md"><img alt="Windows 11" src="https://img.shields.io/badge/Windows_11-supported-2E8B67?style=flat-square"></a>
  <img alt="Chrome Extension" src="https://img.shields.io/badge/Chrome-Manifest_V3-C65F3D?style=flat-square">
  <img alt="Local first" src="https://img.shields.io/badge/data-local--first-25221E?style=flat-square">
  <img alt="Node tests" src="https://img.shields.io/badge/Node_tests-46_passing-2E8B67?style=flat-square">
  <img alt="Python tests" src="https://img.shields.io/badge/Python_tests-32_passing-2E8B67?style=flat-square">
</p>

<p align="center">
  <strong>文章采集 → AI 辅助内容提炼 → 人工研判 → 知识归档 → 周度回顾</strong>
</p>

Info Collector 是一套面向 **Windows 11** 的本地优先技术阅读与情报整理工作台。它把 Chrome 书签中的公开文章转化为中文译文、结构化摘要、主题标签和可追溯 Markdown，并通过任务面板、阅读工作台与周度回顾，完成从采集到人工研判的闭环。

它解决的不是“保存更多”，而是让已经保存的内容经过机器提炼与人工判断，成为可检索、可迁移、可复用的个人知识资产。

## 产品工作台

<p align="center">
  <img src="docs/images/dashboard.png" alt="Info Collector Windows 11 工作台：任务状态、处理流水线与文章知识库" width="100%">
</p>

<details>
<summary><strong>查看文章知识库完整列表</strong></summary>
<br>
<p align="center">
  <img src="docs/images/dashboard-library.png" alt="Info Collector 文章知识库：摘要、标签、状态与操作" width="100%">
</p>
</details>

## 核心能力

<p align="center">
  <img src="docs/images/readme-capabilities.svg" alt="Info Collector 六项核心能力：浏览器采集、AI 辅助提炼、任务可观测、结构化知识库、沉浸式阅读与周度回顾" width="100%">
</p>

## 从采集到知识资产

<p align="center">
  <img src="docs/images/readme-workflow.svg" alt="Info Collector 工作流：浏览器采集、任务编排、内容提炼、人工研判与阅读回顾" width="100%">
</p>

Chrome 扩展的同步存储承担任务状态的 **system of record**。Windows Native Host 与本地处理引擎通过 `~/.info-collector/` 下的 outbox / inbox 文件契约交换数据，使浏览器交互、模型调用与 Markdown 产物彼此解耦；API Key 仅保存在本机配置中。

## Windows 11 快速开始

### 1. 下载项目

```powershell
git clone https://github.com/Madarame87/INFO.git
cd INFO
```

### 2. 运行安装器

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

安装器会引导配置模型、API Key、输出目录与 Chrome 扩展。完整步骤与故障排查见 **[Windows 安装指南](SETUP-WINDOWS.md)**。

### 3. 完成一条真实工作流

1. 在 Chrome 中创建「收藏文章」书签文件夹并保存公开文章。
2. 打开 Dashboard，依次点击「导入书签」与「桥接同步」。
3. 点击「立即处理」，等待任务从排队、运行进入完成状态。
4. 查看中文译文、结构化摘要、主题标签与本地 Markdown。
5. 打开阅读工作台，在「待整理 / 我的收藏 / 全部收录」间完成研判；查看最近六周阅读趋势，并按明确日期区间导出 Markdown 回顾。

## 阅读与人工研判

阅读站由本地 Markdown 确定性生成，默认输出到：

```text
%USERPROFILE%\Documents\InfoCollector\阅读站\index.html
```

三个主视图分别承担不同语义：

- **待整理**：尚未完成人工研判的新文章；
- **我的收藏**：确认值得长期保留的文章；
- **全部收录**：所有进入系统的文章。

主题标签可与主视图组合筛选。文章卡片支持收藏、完成整理、复制资料卡与打开原文；标题进入完整中文译文。人工研判状态保存在当前浏览器 origin 的 `localStorage` 中，不会上传，也不会跨浏览器或跨设备同步；重新生成页面不会改变稳定文章 ID 对应的状态。

「每周阅读」是统计而非筛选器：它按人工研判时间展示最近六周趋势、本周收藏数与已整理数，不隐藏文章。导出按钮会标明七天起止日期，并生成包含研判状态、摘要、主题标签与原文链接的 Markdown 回顾。

## 已验证范围

<p align="center">
  <img src="docs/images/readme-scope.svg" alt="Info Collector Windows 11 已验证能力：原生集成、文章处理流水线、阅读研判与周度回顾" width="100%">
</p>

产品边界明确限定为 **Windows 11 上的个人技术文章处理工作流**：Chrome 负责采集与任务管理，本机负责正文抽取与 AI 辅助提炼，阅读工作台负责人工研判与知识迁移。它不把个人阅读量包装成行业趋势，也不宣称替代专业研究判断。

## 为什么做这个项目

技术信息管理的瓶颈通常不是找不到文章，而是首次保存后缺少结构化处理与再次判断。Info Collector 在原文和长期知识库之间增加一层可审计的处理链：保留来源，统一生成译文、摘要和标签，再由用户决定收藏、归档或迁移。

Dashboard 的「本周处理回顾」按机器 `processedAt` 汇总，用于复盘系统处理量，不代表行业趋势或世界动态；阅读工作台的「每周阅读」按人工 `reviewedAt` 汇总，用于观察研判节奏。两组指标口径独立，避免把机器吞吐与人工阅读混为一谈。

## 技术架构

<p align="center">
  <img src="docs/images/readme-architecture.svg" alt="Info Collector 技术架构：Chrome MV3、Windows Native Host、本地处理引擎与知识资产" width="100%">
</p>

- 架构说明：[docs/design.md](docs/design.md)
- 领域语言：[CONTEXT.md](CONTEXT.md)
- 关键决策：[docs/adr/](docs/adr/)
- Windows 移植清单：[docs/windows-porting-checklist.md](docs/windows-porting-checklist.md)
- 目标完成度审查：[docs/goal-audit-2026-07-11.md](docs/goal-audit-2026-07-11.md)

## 开发与验证

```powershell
npm.cmd test
```

回归基线覆盖 URL 归一化、任务状态机、跨端文件契约、真实网页抽取、模型异常输出、摘要与标签、浏览器本地研判状态、组合筛选、资料卡复制、周度聚合、Windows UTF-8 子进程、Native Messaging 与静态页面契约。

## 验证基线

<p align="center">
  <img src="docs/images/readme-validation.svg" alt="Info Collector 验证基线：46 个 Node 测试、32 个 Python 测试与 Windows Native Host 验收" width="100%">
</p>

---

<p align="center">
  <sub>Powered by <a href="https://github.com/Madarame87">@Madarame87</a> × <a href="https://github.com/aswrise">@aswrise</a> · Personal Technology Intelligence</sub>
</p>

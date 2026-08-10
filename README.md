# Info Collector

把浏览器里的文章，转成可恢复、可审计的中文阅读库。

[在线阅读桌](https://info-collector-reading-desk.jiligualapiqiu.chatgpt.site/) · [Windows 安装](SETUP-WINDOWS.md) · [架构](docs/design.md) · [运维手册](docs/OPERATIONS.md)

## 它解决什么

- 在 Chrome 中保存文章或导入书签；
- 优先采集用户当前可见正文，再使用受限的网络抽取；
- 生成中文译文、摘要、标签和可追溯 Markdown；
- 把 401、登录页、低质量正文和模型故障分开处理；
- 在阅读桌完成收藏、研判与每周回顾。

系统不会把 401 占位页或登录页样板算作成功译文。受限来源进入恢复队列：打开有权访问的原文，在正文可见时再次点击扩展保存即可。

## 快速开始（Windows 11）

```powershell
git clone https://github.com/130U/info-collector-2026.git
cd info-collector-2026
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

在 `chrome://extensions` 打开开发者模式，加载 `extension/`。API Key 由 Windows DPAPI 加密，不写入 `config.json`。

## 可靠性边界

- 401/403 不自动绕过；用户可显式采集自己有权查看的当前页面。
- 自动重试最多 3 次，遵守退避时间；不可恢复失败不会无限循环。
- 长文按段翻译并写检查点；网页正文被视为不可信数据。
- 外部抓取仅允许公网 HTTP(S)，限制重定向、正文大小和单次成本。
- 默认每次最多处理 20 篇、单篇最多 300,000 字符，可在本机配置中显式调整。

这是一套可用于受控商业 pilot 的本地优先工程基础，不代表对任意网站、翻译准确率、全球隐私合规或 SLA 的无条件承诺。公开发布来源内容前，部署方仍需确认其访问、翻译与再发布权利。

## 开发

```powershell
npm.cmd test
```

发布门槛、故障恢复和 pilot SLI 见 [docs/OPERATIONS.md](docs/OPERATIONS.md)，安全边界见 [SECURITY.md](SECURITY.md)。

Apache-2.0 licensed. Built by [@130U](https://github.com/130U) × [@aswrise](https://github.com/aswrise).

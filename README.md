# Info Collector

本地优先的信息收集与中文阅读终端：采集网页，提取正文，翻译归档，并把失败留在可恢复队列中。

[在线阅读桌](https://info-collector-reading-desk.jiligualapiqiu.chatgpt.site/) · [安装](SETUP-WINDOWS.md) · [安全](SECURITY.md) · [运维](docs/OPERATIONS.md)

## 能做什么

- Chrome 保存当前文章或批量导入书签；
- 生成中文译文、摘要、标签与可追溯 Markdown；
- 区分 401/403、登录页、低质量正文和模型故障；
- 在阅读桌搜索、收藏、整理和周度回顾。

系统不会把登录页或 401 占位内容伪装成成功译文。受限来源进入恢复队列，用户可在有权访问且正文可见时重新采集。

## 安装（Windows 11）

```powershell
git clone https://github.com/130U/info-collector-2026.git
cd info-collector-2026
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

随后在 `chrome://extensions` 加载 `extension/`。API Key 由 Windows DPAPI 加密保存；模型端点默认锁定官方 HTTPS 地址。

## 工程边界

- 401/403 不绕过；网络抽取仅允许公网 HTTP(S)。
- 自动重试最多 3 次；长文分段并写检查点。
- 网页正文按不可信输入处理；抓取、翻译与公开发布权由部署方确认。
- 这是受控商业 pilot 的工程基础，不是翻译准确率、隐私合规或 SLA 的无条件承诺。

## 验证

```powershell
npm.cmd test
```

[架构](docs/design.md) · [工程审计](docs/ENGINEERING_AUDIT.md) · Apache-2.0

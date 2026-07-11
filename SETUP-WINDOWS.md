# Info Collector Windows 安装与阶段 1 验收

适用环境：Windows 11、Google Chrome、Python 3.9+。第一版只支持 Dashboard 手动触发文章翻译，不安装计划任务，也不安装播客/Pi 流。

## 1. 准备 API Key

- DeepSeek：<https://platform.deepseek.com/api_keys>
- Anthropic：<https://console.anthropic.com/settings/keys>

API Key 只写入 `%USERPROFILE%\.info-collector\config.json`，不要把它放进仓库。

## 2. 运行安装器

在仓库根目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

安装器会：

1. 探测 Python 3.9+；
2. 创建 `%USERPROFILE%\.info-collector\`；
3. 写入本机配置并复制 Host/Flow；
4. 生成 `.bat` Native Host 包装器；
5. 在当前用户注册表注册 Chrome Native Messaging Host。

如果 Python 已安装但不在 PATH，可先设置：

```powershell
$env:INFO_COLLECTOR_PYTHON = "C:\完整路径\python.exe"
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

非交互安装示例：

```powershell
$env:INFO_COLLECTOR_ENGINE = "deepseek"
$env:INFO_COLLECTOR_API_KEY = "你的本机 API Key"
$env:INFO_COLLECTOR_OUTPUT_DIR = "$env:USERPROFILE\Documents\InfoCollector"
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

## 3. 运行自检

安装器结尾会打印包含实际 Python 路径的自检命令。复制运行它，预期看到：

- API Key 有效；
- 输出目录可写；
- outbox 已存在，或者在首次桥接前提示尚不存在。

## 4. 加载 Chrome 扩展

1. 完全退出并重新打开 Chrome。
2. 打开 `chrome://extensions`。
3. 开启“开发者模式”。
4. 点击“加载已解压的扩展程序”。
5. 选择本仓库的 `extension` 文件夹。
6. 确认扩展 ID 是 `fmdbamjmoabmcggjfgeopaijnbjkjbhm`。

## 5. 阶段 1 手动验收

对 3–5 个不同网站分别执行并记录结果：

1. 在 Chrome 建立名为“收藏文章”的书签文件夹。
2. 把一篇公开文章加入该文件夹。
3. 打开 Info Collector Dashboard。
4. 点击“立即导入书签”，确认任务为“待处理”。
5. 点击“立即桥接同步”，确认没有 Host 错误。
6. 点击该任务的“▶ 立即处理”。
7. 等待状态变为“处理中”；翻译结束后再次桥接，确认变为“已完成”。
8. 打开 `%USERPROFILE%\Documents\InfoCollector`（或自定义目录），确认生成中文 Markdown。

建议记录：文章 URL、网站、正文是否完整、最终状态、输出文件、失败原因。

阶段 1 的 3–5 篇未全部验收前，不进入 Summary/Tags 开发。

## 6. 阶段 2 Summary/Tags 验收

阶段 1 通过后，重新运行安装器并在 `chrome://extensions` 重新加载扩展。再处理
2–3 篇至少共享一个主题的新文章，确认：

1. 每个新 Markdown 的 frontmatter 都有单行 `summary` 和 2–5 个 `tags`；
2. Markdown 正文开头有“摘要”小节；
3. Dashboard 的文章行显示摘要与标签；
4. 标签上方显示文章数量，点击标签或使用“标签”下拉框能筛出同类文章；
5. 旧的阶段 1 文章没有摘要/标签时仍能正常显示，不报错。

阶段 2 不包含周报、关键词趋势、专家/机构分析。

## 7. 阶段 3 周报验收

阶段 2 通过后，在 Dashboard 点击“生成本周周报”。周报流不会再次调用模型，
只聚合当前周（周一至周日）已经包含 Summary/Tags 的完成记录。确认：

1. 流水线状态显示“周报流 ✓ 成功”；
2. 输出目录的 `周报` 子目录生成 `技术动态周报-YYYY-MM-DD.md`；
3. 文件包含主题排行、按主题归类和每日收录；
4. 同一 URL 的重试记录只出现一次；
5. 同一周重复生成会覆盖更新同一个文件，不制造重复周报。

阶段 3 的最小范围不包含模型二次综合、趋势预测和专家/机构分析。

## 排错

### `host 未找到` 或 `host 已断开`

- 重新运行 `scripts/setup.ps1`；
- 完全退出所有 Chrome 进程再打开；
- 检查注册表：
  `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.pi.info_collector`；
- 检查其默认值指向的 manifest 文件存在。

### 找不到 Python

设置 `INFO_COLLECTOR_PYTHON` 为 `python.exe` 的绝对路径后重跑安装器。

### 文章失败

查看：

- `%USERPROFILE%\.info-collector\state\translate-flow.log`
- `%USERPROFILE%\.info-collector\state\translate-trigger.log`

登录墙、付费墙、强 JavaScript 页面可能无法由内置抓取器读取。

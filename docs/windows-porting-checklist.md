# Windows 移植清单

**审计基线：** `aswrise/info-collector@9d5935b`  
**目标仓库：** `130U/info`
**范围：** 阶段 1 只移植文章翻译流水线；不改变扩展与 Native Messaging 的消息协议。

## 审计结论

Chrome MV3 扩展、队列状态机、JSON spool 契约和文章抓取/API 请求主体均可继续复用。Windows 阻塞点集中在安装、Native Messaging 注册、标准输入输出模式、文件锁、解释器路径和文档/测试命令。播客与 Pi 流保留在仓库中，但阶段 1 不安装、不验收。

当前 Windows 基线结果：

- Node 测试：31/31 通过。
- Python 测试：9/9 在导入阶段失败，直接原因均为 Windows 没有 `fcntl`。
- 当前终端可用 Node/npm，但 `python` 与 `py` 不在 PATH；开发验证可使用 Codex 自带 Python。正式安装脚本必须自行探测用户 Python，不能假设固定命令名。

### 阶段 1 自动验证状态（2026-07-11）

- Node 测试：31/31 通过。
- Python 测试：12/12 通过，覆盖跨平台锁、Host 二进制 ping、spool sync、注册命令触发和文章 Flow mock 全链路。
- `setup.ps1`：Windows PowerShell 语法通过；非交互模拟安装通过。
- 真实用户目录：`skip` 模式安装成功，HKCU 注册表值、manifest、`.bat`、Host/兼容层文件均已核对。
- 安装后的 `.bat`：二进制 Native Messaging ping 通过。
- 尚未通过：Chrome UI 与真实 API 的 3–5 篇文章手动验收。因此阶段 1 仍未完成，阶段 2 保持锁定。

## Unix / macOS 专属依赖点

| 类别 | 当前位置 | Windows 影响 | 阶段 1 处理 |
|---|---|---|---|
| Bash 安装器 | `scripts/setup.sh` | Windows 默认不能执行 | 新增 `scripts/setup.ps1`，保留原脚本 |
| Shell 命令 | `mkdir -p`、`cp`、`chmod`、`sed`、heredoc、`date` | PowerShell 语法不同 | 用 PowerShell/.NET 等价实现 |
| Native host manifest 路径 | `~/Library/Application Support/Google/Chrome/NativeMessagingHosts` | Windows 通过注册表发现 manifest | manifest 写入 `~\.info-collector\native-host\`，注册到 HKCU |
| Native host 可执行入口 | manifest 直接指向 `.py` | Windows 需要可执行包装入口 | 新增无 stdout 噪音的 `.bat` 包装器，内部调用绝对 Python 路径 |
| Native Messaging 文本模式 | `host/info_collector_host.py` 未设置 | Windows CRT 可能转换换行并破坏四字节长度前缀 | Host 启动时将 stdin/stdout 设为 `O_BINARY` |
| Unix 文件锁 | Host 和三个 flow 直接 `import fcntl` | Windows 导入即失败 | 提供跨平台锁实现，替换所有 `fcntl` 导入与 `flock` 调用 |
| launchd | `templates/*.plist`、`launchctl` | Windows 不支持 | 阶段 1 不安装任何定时任务，只保留手动触发 |
| 固定 Python 路径 | `/usr/bin/python3`、`python3` | Windows 路径和命令名不固定 | setup 探测解释器并把绝对路径写入 `flows.json` |
| POSIX 可执行权限 | `chmod +x`、`os.chmod(..., 0o600)` | Windows 权限模型不同 | `.bat` 无需 chmod；配置文件留在用户目录，必要时用用户 ACL 最小化访问 |
| Unix 用户目录 | `$HOME`、`~/.info-collector`、`~/Documents/...` | PowerShell 和 GUI Chrome 环境变量不同 | 安装器用用户目录绝对路径；Python 用 `Path.home()`/`expanduser` |
| Unix PATH 候选 | `/opt/homebrew/bin`、`/usr/local/bin`、`/usr/bin`、`/bin`、`~/.nvm/.../bin` | Windows 无这些目录 | Host 按平台构造 PATH；Windows补 `%APPDATA%\npm` 等用户工具目录 |
| 后台进程 | `subprocess.Popen(..., start_new_session=True)` | 需确认 Windows 行为 | 已在当前 Windows Python 验证可运行；保留并补测试 |
| 测试入口 | `package.json` 使用 `python3 -m unittest` | 当前 Windows PATH 无 `python3` | 增加跨平台测试入口或明确使用 setup 解析出的解释器 |
| 抓取 User-Agent | 内置抓取器声明 `Macintosh` | 不阻塞，但与 Windows 实际平台不符 | 改为中性或 Windows Chrome UA |
| macOS 用户文档 | `README.md`、`SETUP.md` | Windows 用户无法按文档安装 | 增加 Windows 安装与手动验收步骤，保留 macOS 说明 |

### `fcntl` 出现位置

必须全部清除直接导入，避免 Windows 上任何 Python 测试在收集阶段失败：

1. `host/info_collector_host.py`
   - `lock_is_held()` 需要非阻塞探测已有锁。
2. `flows/translate-claude-api.py`
   - `acquire_lock()` 需要保证翻译流不能并发运行。
3. `flows/translate-bookmarks.py`
   - 阶段 1 不安装，但仍需能在 Windows 被导入和测试。
4. `flows/podcast-bookmarks.py`
   - 阶段 1 不安装，但仍需能在 Windows 被导入和测试。

跨平台锁必须同时满足：

- 非阻塞获取；
- 获取失败时返回“已有进程运行”，不崩溃；
- 文件描述符关闭后释放；
- Host 可以只探测锁是否被占用；
- macOS/Linux 现有语义不退化。

## Windows Native Messaging 安装清单

Host 名称继续使用 `com.pi.info_collector`，扩展协议和 `extension/lib/bridge.js` 不改。

1. 创建 `~\.info-collector\native-host\`。
2. 生成 `.bat` 包装器：
   - 第一行 `@echo off`；
   - Python 和 Host 路径使用绝对路径并加双引号；
   - 不向 stdout 输出任何日志；
   - 透传 Chrome 附加的命令行参数。
3. 生成 UTF-8（无 BOM）host manifest：
   - `name`: `com.pi.info_collector`；
   - `path`: `.bat` 的绝对路径；
   - `type`: `stdio`；
   - `allowed_origins`: 固定扩展 ID `fmdbamjmoabmcggjfgeopaijnbjkjbhm`。
4. 写入注册表：
   - `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.pi.info_collector`；
   - 默认值为 manifest 的绝对路径。
5. Host 在读取任何消息前调用 Windows 二进制模式初始化。
6. 安装后先做 Host `ping` 协议测试，再由 Chrome 手动桥接。

## `setup.ps1` 行为清单

### 必须支持

- 可重复运行，已有 API key 在没有新输入时不被清空；
- 交互式选择 `deepseek` / `claude` / `skip`；
- 非交互环境变量：
  - `INFO_COLLECTOR_ENGINE`；
  - `INFO_COLLECTOR_API_KEY`；
  - `INFO_COLLECTOR_MODEL`；
  - `INFO_COLLECTOR_BASE_URL`；
  - `INFO_COLLECTOR_OUTPUT_DIR`；
- Python 探测顺序覆盖 `py -3`、`python`、`python3`及常见用户安装位置；
- 创建 `outbox`、`inbox\processed`、`state`、`bin`、`native-host`；
- 复制文章翻译脚本到 `~\.info-collector\bin\translate-flow.py`；
- 写入 `config.json`，API key 只存在用户目录；
- 写入 `flows.json`，`command[0]` 使用探测到的 Python 绝对路径；
- 不注册计划任务，不安装播客/Pi 流；
- 输出 Chrome 扩展加载路径、自检命令和重启 Chrome 提示。

### 默认路径

- Spool：`%USERPROFILE%\.info-collector`；
- 译文：`%USERPROFILE%\Documents\InfoCollector`；
- Native host：`%USERPROFILE%\.info-collector\native-host`。

## 阶段 1 自动验证

实现后至少执行：

1. Node 队列/扩展纯函数测试全部通过。
2. Python 测试在 Windows 完成收集并全部通过。
3. 新增跨平台锁测试：获取、冲突、释放、探测。
4. Native host 二进制协议测试：`ping`、`sync`、`trigger`。
5. PowerShell 脚本语法检查。
6. 仓库扫描确认：
   - 无代码路径继续直接依赖 `fcntl`；
   - Windows `flows.json` 不含 `/usr/bin/python3`；
   - 仓库内无 API key。

自动测试不能代替 Chrome 手动验收。

## 阶段 1 手动门禁

只有以下步骤由用户在 Windows Chrome 亲手验证全部通过，才能进入阶段 2：

1. 运行 `scripts/setup.ps1` 并完成自检。
2. 在 `chrome://extensions` 加载仓库的 `extension` 目录。
3. 确认扩展 ID 为 `fmdbamjmoabmcggjfgeopaijnbjkjbhm`。
4. 创建“收藏文章”书签文件夹并添加一篇公开文章。
5. Dashboard 点击“立即导入书签”，出现待处理任务。
6. 点击“立即桥接同步”，无 host 错误。
7. 点击“▶ 立即处理”，状态依次出现待处理、处理中、已完成。
8. 输出目录出现可读的中文 Markdown。
9. 使用 3–5 个不同网站重复验证并记录成功/失败结果。

## 阶段门禁

- 阶段 1 手动门禁未通过：禁止修改 Summary/Tags 提示词。
- 阶段 2 的 5–10 篇 YAML/标签白名单验收未通过：禁止实现周报。
- 阶段 3 完成至少 12 篇真实分组和链接核验后，才进行最终完成审计。

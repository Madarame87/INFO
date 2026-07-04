# Info Collector 安装指南

这份指南写给**没有编程经验的人**。全程只需要做一次，大约 10 分钟。
装好之后：你在 Chrome 里把文章存进「收藏文章」书签文件夹，它每小时自动
把文章翻译成中文 Markdown，存到你指定的文件夹里。

整个安装分四部分，请按顺序做（Part C 会用到 Part A 拿到的 API Key）：

- **Part A**：获取一个 Anthropic API Key（翻译要用的「钥匙」）
- **Part B**：把扩展装进 Chrome
- **Part C**：在终端里跑一条安装命令
- **Part D**：验证一切正常

---

## Part A：获取 Anthropic API Key（约 3 分钟）

API Key 是一串以 `sk-ant-` 开头的字符，相当于你调用 Claude 翻译服务的
钥匙。翻译按用量计费，一篇普通文章大约几美分。

1. 打开 <https://console.anthropic.com/> 并注册/登录。
2. 左侧菜单进入 **API Keys**（或直接打开
   <https://console.anthropic.com/settings/keys>）。
3. 点 **Create Key**，名字随便填（比如 `info-collector`），点创建。
4. 屏幕上会显示一串 `sk-ant-` 开头的字符——**点复制，找个地方暂存**
   （备忘录就行）。⚠️ 这串字符只显示这一次，关掉就看不到了；
   丢了也没关系，重新创建一个即可。
5. 如果账户还没有余额，去 **Billing** 页面充值（最低 $5 足够翻译很久）。

✅ **检查点**：你手上有一串 `sk-ant-` 开头的字符。

---

## Part B：把扩展装进 Chrome（约 2 分钟）

先把本项目下载到电脑上（如果还没有）：打开项目的 GitHub 页面 →
绿色 **Code** 按钮 → **Download ZIP** → 解压到一个**以后不会挪动**的
位置（比如「文稿」文件夹）。⚠️ 之后请不要移动或删除这个文件夹，
扩展和翻译程序都住在里面。

1. 打开 Chrome，在地址栏输入 `chrome://extensions` 并回车。
2. 打开右上角的 **开发者模式** 开关。（这只是解锁「从文件夹安装扩展」
   的功能，不会有其他影响。）
3. 点左上角出现的 **加载已解压的扩展程序** 按钮。
4. 在弹出的选择框里，进入刚才解压的项目文件夹，**选中里面的
   `extension` 文件夹**，点选择。

✅ **检查点**：扩展列表里出现一张名为 **Info Collector** 的卡片，
卡片上的 ID 是 `fmdbamjmoabmcggjfgeopaijnbjkjbhm`。
如果工具栏看不到它的图标，点工具栏的拼图🧩图标，把 Info Collector
旁边的图钉点亮。

---

## Part C：跑一条安装命令（约 3 分钟）

这一步会自动完成剩下的所有配置：创建工作目录、连接 Chrome、
写入你的 API Key、装上每小时自动翻译的定时任务。

1. 打开「终端」App：按 `⌘ + 空格` 打开聚焦搜索，输入 `终端`
   （或 `Terminal`），回车。会出现一个黑底或白底的命令行窗口——
   这是正常的，我们只需要粘贴一条命令。
2. 把下面这行粘贴进去（把路径换成你解压的位置），回车：

   ```
   bash ~/Documents/info-collector/scripts/setup.sh
   ```

   💡 不确定路径？把解压出来的文件夹里的 `scripts/setup.sh` 文件
   **直接拖进终端窗口**，它会自动填好路径，你只需要在最前面补上
   `bash ` 再回车。

3. 脚本会问你两三个问题：
   - **选择翻译引擎**：直接回车（默认选 1，内置 Claude 翻译）。
   - **粘贴 API Key**：把 Part A 复制的 `sk-ant-...` 粘贴进来，回车。
     （终端里粘贴用 `⌘V`；粘贴后看不到字符变化也是正常的。）
   - **译文保存到哪**：直接回车用默认位置（文稿/InfoCollector），
     或输入你想要的文件夹路径。

4. 跑一下自检，确认配置没问题：

   ```
   /usr/bin/python3 ~/.info-collector/bin/translate-flow.py --check
   ```

✅ **检查点**：自检输出里每一行都是 ✓（「API Key 有效」「输出目录可写」）。
「outbox 还不存在」前面是 △ 也没关系——Part D 做完它就有了。

---

## Part D：验证（约 2 分钟）

1. 在 Chrome 书签里建一个名为 **收藏文章** 的文件夹（名字要完全一致；
   之后想改，可以在 Dashboard 的「设置」里改）。往里面存一篇文章的书签。
2. 点浏览器工具栏的 Info Collector 图标 → **打开 Dashboard**。
3. 点 **立即导入书签**——表格里应该出现刚才那篇文章，状态「⏳ 待处理」。
4. 点 **立即桥接同步**——顶部流水线状态条会更新。
5. 点文章行里的 **▶ 立即处理**——状态很快变成「⚙ 处理中」，
   翻译需要几分钟，完成后自动变成「✓ 已完成」。
6. 打开你在 Part C 选的输出文件夹——里面有翻译好的中文 `.md` 文件。🎉

从现在起一切都是自动的：存书签 → 扩展每 30 分钟导入 → 翻译流每小时
处理 → 译文出现在输出文件夹。等不及就去 Dashboard 点「▶ 立即处理」。

---

## 出问题了？

**Dashboard 点「立即桥接同步」报错「host 已断开」或「未找到」**
→ Part C 的脚本没跑，或跑完之后 Chrome 还没重启过。重跑一遍
`setup.sh`，然后完全退出 Chrome（`⌘Q`）再打开。

**自检说「API Key 验证失败：API 401」**
→ Key 粘贴错了或被删除了。去 <https://console.anthropic.com/settings/keys>
重新创建一个，然后打开 `~/.info-collector/config.json`（终端里输入
`open ~/.info-collector/config.json`），把 `apiKey` 的值换掉。

**自检说「API 400」且提到 credit**
→ 账户余额不足，去 Console 的 Billing 页面充值。

**文章一直「⏳ 待处理」**
→ 定时任务每小时才跑一次。点文章行的「▶ 立即处理」立刻开始；
Dashboard 顶部的流水线条会显示「翻译流」上次运行时间和下次定时时间。

**某篇文章「✕ 失败」**
→ 把鼠标悬停在状态上能看到原因。常见原因：网站挡了抓取（比如需要
登录的页面）、文章太长。点「▶ 立即处理」可以重试，或点「忽略」跳过。

**扩展卡片上的 ID 不是 `fmdbamjmo...`**
→ 你选的不是项目里的 `extension` 文件夹，删掉重新加载一次。

**想换翻译模型或输出文件夹**
→ 编辑 `~/.info-collector/config.json`（`model` 可改为
`claude-sonnet-5`，更便宜）。改完不用重启任何东西，下次翻译自动生效。

**用 AI 帮你装**
→ 把整个项目文件夹给任何 AI 编程助手（如 Claude Code），说
「按 SETUP.md 帮我装好」。安装脚本支持非交互模式：
`INFO_COLLECTOR_API_KEY=sk-ant-... INFO_COLLECTOR_ENGINE=claude bash scripts/setup.sh`，
装完让它跑 `--check` 自检即可。

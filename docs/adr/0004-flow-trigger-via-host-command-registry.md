# 流程触发经 host + 用户自有命令注册表

Dashboard 的「立即处理」通过 native host 启动外部流程。host 只执行
`~/.info-collector/flows.json`（由 setup 脚本写入、用户自有）中按处理类型
注册的命令；扩展在协议里只能点名 `processingType`，不能传任何命令或参数。
host 用注册表里的 lockFile 探测流程是否已在运行，用 detached 子进程启动，
不等待完成——结果仍走标准的 Completion Report 路径回来。手动触发带
`--manual` 参数，流程据此不更新定时锚点（`lastScheduledStartAt`），
保证「下次定时运行」的估算不被手动触发污染。

约束背景：扩展进程不能启动本机程序；等待定时任务到点的体验太差
（存书签到完成最长一个多小时）。

**Considered Options**

- 不做触发，只靠定时 + 命令行手动 kickstart。零改动，但用户在 Dashboard
  里看着待处理干着急，工具链割裂。
- `launchctl kickstart`。不能传参，手动与定时运行无法区分，定时锚点估算
  会被污染；且 label 硬编码进 host。
- 扩展在消息里携带要执行的命令。表达力最强，但等于给任何能对 host 说话的
  扩展开了任意命令执行口，不可接受。
- host + flows.json 命令注册表（选此）。命令面收敛在一个用户自有文件里，
  扩展只有「点名」能力；新流程注册一条 JSON 即获得触发与状态展示。

**Consequences**

host 不再是纯文件搬运工，多了「按注册表启动进程」一项能力；ADR 0002 的
「哑」原则收窄为「无状态语义、无扩展可注入的执行面」。触发是队列级而非
文章级：启动的流程会处理该类型 outbox 里全部未报告文章（对小队列这正是
想要的行为）。流程状态（运行中、上次结果、定时锚点）经 sync 响应带回
扩展展示，来源是 lockFile 探测与 `state/<type>-status.json`，均由流程
自己维护——流程崩溃时状态可能短暂失真，以下一轮运行自愈。

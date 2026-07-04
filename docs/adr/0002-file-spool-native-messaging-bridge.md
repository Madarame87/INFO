# 外部流通过文件 spool + Native Messaging 桥接

外部处理流（launchd 定时脚本等）与扩展之间通过 `~/.info-collector/` 下的
文件契约交换数据：扩展导出待处理清单到 `outbox/<type>.json`，外部流写
Completion Report 到 `inbox/`。扩展无法直接读写本机文件，由一个不含业务
逻辑的 Native Messaging host（python）代为搬运，扩展经 `chrome.alarms`
周期性发起桥接会话。

约束背景：MV3 扩展不能监听端口、不能读任意本机文件；外部进程不能写
`chrome.storage`。两个世界必须有一座桥。

**Considered Options**

- 纯手动：Dashboard 点击标记 + 批量粘贴 URL。零基础设施，但现有 translate
  流是 launchd 全自动定时任务，手动回报会把自动化流程降级成人肉流程。
- 扩展轮询本机 HTTP 服务。需要用户常驻一个服务进程，且 MV3 service worker
  休眠使轮询时机不可控；为个人工具引入网络面没有必要。
- Native Messaging 直接 RPC（外部流通过 host 与扩展实时对话）。host 只能由
  扩展侧发起连接，外部流无法主动推送，实时性是假的；且每条流都要学会
  Native Messaging 协议。
- 文件 spool 作为契约 + host 只做文件搬运（选此）。外部流保持普通脚本形态，
  读一个 JSON、写一个 JSON 即完成集成，不依赖 Chrome 在场即可开发和测试；
  新增流程（文稿、书籍）零协议成本。

**Consequences**

完成回报最多延迟一个桥接周期（约 10 分钟），对小时级的定时流无感。host
必须保持「哑」：所有状态语义留在扩展内，spool 文件格式即公共契约，改动
需要同时考虑所有外部流。报告应用采用幂等语义 + ack 后归档文件，容忍重复
投递。Dashboard 保留手动标记与批量粘贴作为桥失效时的兜底。

// 桥接会话（ADR 0002）：经 Native Messaging host 写 outbox、收 inbox 报告并 ack。
// host 是哑文件搬运工，全部状态语义在这里应用。

import { normalizeUrl } from './normalize.js';
import { applyResult, outboxEntries, reclaimIfStale } from './queue.js';
import * as store from './storage.js';

const HOST_NAME = 'com.pi.info_collector';
const EXCHANGE_TIMEOUT_MS = 10_000;

function exchange(port, msg) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('host 响应超时')), EXCHANGE_TIMEOUT_MS);
    port.onMessage.addListener(function onMsg(resp) {
      clearTimeout(timer);
      port.onMessage.removeListener(onMsg);
      resolve(resp);
    });
    port.onDisconnect.addListener(() => {
      clearTimeout(timer);
      reject(new Error(chrome.runtime.lastError?.message || 'host 已断开'));
    });
    port.postMessage(msg);
  });
}

export async function bridgeSync() {
  const meta = await store.loadMeta();
  const active = await store.loadActive();

  const outbox = {};
  for (const type of Object.keys(meta.types)) {
    outbox[type] = outboxEntries(active, type);
  }
  const acks = await store.getAcks();

  const port = chrome.runtime.connectNative(HOST_NAME);
  let resp;
  try {
    resp = await exchange(port, {
      type: 'sync',
      generatedAt: new Date().toISOString(),
      outbox,
      acks,
    });
  } finally {
    try { port.disconnect(); } catch { /* 已断开 */ }
  }
  if (!resp || !resp.ok) throw new Error(resp?.error || 'host 返回异常');

  const archive = await store.loadArchive();
  const now = new Date().toISOString();
  const changed = new Map();
  const appliedIds = [];
  let newTypes = 0;

  for (const rep of resp.reports || []) {
    const type = rep.processingType;
    if (!type || typeof type !== 'string') continue;
    // 未注册类型自动登记（autoEnroll 关闭）：新外部流只写报告即可自我引入
    if (!meta.types[type]) {
      meta.types[type] = { label: type, autoEnroll: false, createdAt: now };
      newTypes++;
    }
    for (const r of rep.results || []) {
      const key = normalizeUrl(r.url);
      if (!key) continue;
      if (archive.has(key)) continue; // 归档即已完成历史，重复报告幂等跳过
      const prev = changed.get(key) || active.get(key) || null;
      const { record, changed: ch } = applyResult(prev, {
        articleKey: key,
        url: r.url,
        type,
        status: r.status,
        processedAt: r.processedAt,
        meta: r.meta,
        now,
      });
      if (ch) {
        changed.set(key, record);
        active.set(key, record);
      }
    }
    if (rep.reportId) appliedIds.push(rep.reportId);
  }

  // 认领过期回收：流程未在运行却仍是 processing 的文章回退 pending（崩溃自愈）
  let reclaimed = 0;
  const flows = resp.flows || {};
  for (const type of Object.keys(meta.types)) {
    if (flows[type]?.running) continue;
    for (const rec of active.values()) {
      const cur = changed.get(rec.articleKey) || rec;
      const reverted = reclaimIfStale(cur, type, now);
      if (reverted) {
        changed.set(reverted.articleKey, reverted);
        active.set(reverted.articleKey, reverted);
        reclaimed++;
      }
    }
  }

  if (newTypes) await store.saveMeta(meta);
  await store.putRecords([...changed.values()]);
  await store.setAcks(appliedIds);
  await store.setFlows(flows);
  await store.compact(now);
  return { reports: (resp.reports || []).length, applied: changed.size, reclaimed, hostErrors: resp.errors || [] };
}

// 立即触发一条外部流程（ADR 0004）：host 只执行 flows.json 注册的命令，
// 这里只能点名 processingType。
export async function triggerFlow(type) {
  const port = chrome.runtime.connectNative(HOST_NAME);
  let resp;
  try {
    resp = await exchange(port, { type: 'trigger', processingType: type });
  } finally {
    try { port.disconnect(); } catch { /* 已断开 */ }
  }
  if (!resp || !resp.ok) throw new Error(resp?.error || 'host 返回异常');
  return resp;
}

export async function openFlowOutput(type) {
  const port = chrome.runtime.connectNative(HOST_NAME);
  let resp;
  try {
    resp = await exchange(port, { type: 'open-output', processingType: type });
  } finally {
    try { port.disconnect(); } catch { /* 已断开 */ }
  }
  if (!resp || !resp.ok) throw new Error(resp?.error || 'host 返回异常');
  return resp;
}

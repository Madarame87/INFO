// Service worker：定时导入/桥接，集中处理来自 dashboard 与 popup 的全部写操作，
// 用单一 promise 链串行化，避免桶级读-改-写互相踩踏。

import * as store from './lib/storage.js';
import { importFromBookmarks } from './lib/importer.js';
import { bridgeSync, triggerFlow } from './lib/bridge.js';
import { mergeSource, setJobStatus, applyResult, manualSaveTypes } from './lib/queue.js';
import { normalizeUrl } from './lib/normalize.js';

chrome.runtime.onInstalled.addListener(init);
chrome.runtime.onStartup.addListener(init);

async function init() {
  await store.loadMeta();
  chrome.alarms.create('import', { periodInMinutes: 30, delayInMinutes: 1 });
  chrome.alarms.create('bridge', { periodInMinutes: 10, delayInMinutes: 2 });
}

let chain = Promise.resolve();
function serial(fn) {
  const p = chain.then(fn, fn);
  chain = p.catch(() => {});
  return p;
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'import') runImport();
  else if (alarm.name.startsWith('bridge')) runBridge();
});

function runImport() {
  return serial(async () => {
    const at = new Date().toISOString();
    try {
      const counts = await importFromBookmarks();
      await store.setRun('import', { at, ok: true, ...counts });
      return { ok: true, ...counts };
    } catch (e) {
      await store.setRun('import', { at, ok: false, error: String(e?.message || e) });
      return { ok: false, error: String(e?.message || e) };
    }
  });
}

function runBridge() {
  return serial(async () => {
    const at = new Date().toISOString();
    try {
      const counts = await bridgeSync();
      await store.setRun('bridge', { at, ok: true, ...counts });
      return { ok: true, ...counts };
    } catch (e) {
      await store.setRun('bridge', { at, ok: false, error: String(e?.message || e) });
      return { ok: false, error: String(e?.message || e) };
    }
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handle(msg).then(sendResponse, (e) => sendResponse({ ok: false, error: String(e?.message || e) }));
  return true;
});

async function handle(msg) {
  switch (msg.cmd) {
    case 'importNow':
      return runImport();
    case 'bridgeNow':
      return runBridge();

    case 'triggerFlow': {
      const resp = await serial(() => triggerFlow(msg.type));
      // 流程要跑几分钟，安排两次跟进桥接尽快收报告
      chrome.alarms.create('bridge-followup-1', { delayInMinutes: 3 });
      chrome.alarms.create('bridge-followup-2', { delayInMinutes: 8 });
      return resp;
    }

    case 'saveTab':
      return serial(async () => {
        const key = normalizeUrl(msg.url);
        if (!key) return { ok: false, error: '该页面无法入队（仅支持 http/https）' };
        const now = new Date().toISOString();
        // 已归档＝处理历史已完成，和导入/桥接一样跳过，避免复活成新的活跃记录被重复处理。
        const archive = await store.loadArchive();
        if (archive.has(key)) return { ok: true, articleKey: key, existed: true, archived: true };
        const meta = await store.loadMeta();
        const autoTypes = manualSaveTypes(meta, msg.types);
        const prev = await store.getRecord(key);
        const { record, changed } = mergeSource(prev, {
          articleKey: key, url: msg.url, title: msg.title || '',
          source: { kind: 'manual' }, autoTypes, now,
        });
        if (changed) await store.putRecords([record]);
        return { ok: true, articleKey: key, existed: !!prev };
      });

    case 'getTabStatus': {
      const key = normalizeUrl(msg.url);
      if (!key) return { ok: true, queueable: false };
      let record = await store.getRecord(key);
      let archived = false;
      if (!record) {
        const archive = await store.loadArchive();
        record = archive.get(key) || null;
        archived = !!record;
      }
      return { ok: true, queueable: true, articleKey: key, record, archived };
    }

    case 'setJobStatus':
      return serial(async () => {
        const now = new Date().toISOString();
        const active = await store.loadActive();
        const updated = [];
        for (const key of msg.keys || []) {
          const rec = active.get(key);
          if (rec) updated.push(setJobStatus(rec, msg.type, msg.status, now));
        }
        await store.putRecords(updated);
        return { ok: true, updated: updated.length };
      });

    case 'deleteRecords':
      return serial(async () => {
        await store.removeRecords(msg.keys || []);
        return { ok: true, deleted: (msg.keys || []).length };
      });

    case 'bulkDone':
      return serial(async () => {
        const now = new Date().toISOString();
        const active = await store.loadActive();
        const archive = await store.loadArchive();
        const changed = new Map();
        let applied = 0;
        let skipped = 0;
        for (const raw of msg.urls || []) {
          const key = normalizeUrl(raw);
          if (!key || archive.has(key)) {
            skipped++;
            continue;
          }
          const prev = changed.get(key) || active.get(key) || null;
          const { record, changed: ch } = applyResult(prev, {
            articleKey: key, url: raw, type: msg.type, status: 'done', now,
            meta: { manual: true },
          });
          if (ch) {
            changed.set(key, record);
            applied++;
          }
        }
        await store.putRecords([...changed.values()]);
        return { ok: true, applied, skipped };
      });

    case 'addType':
      return serial(async () => {
        const id = String(msg.id || '').trim();
        if (!/^[a-z][a-z0-9_-]*$/.test(id)) return { ok: false, error: '类型 id 需为小写字母开头的英文标识' };
        const meta = await store.loadMeta();
        if (meta.types[id]) return { ok: false, error: `类型 ${id} 已存在` };
        meta.types[id] = { label: msg.label || id, autoEnroll: !!msg.autoEnroll, createdAt: new Date().toISOString() };
        await store.saveMeta(meta);
        return { ok: true };
      });

    case 'setFolders':
      return serial(async () => {
        const folders = (msg.folders || []).map((s) => String(s).trim()).filter(Boolean);
        if (!folders.length) return { ok: false, error: '至少保留一个文件夹名' };
        const podcastFolders = (msg.podcastFolders || []).map((s) => String(s).trim()).filter(Boolean);
        const meta = await store.loadMeta();
        meta.settings.folders = folders;
        meta.settings.typeFolders ||= {};
        meta.settings.typeFolders.podcast = podcastFolders.length ? podcastFolders : ['收藏播客'];
        await store.saveMeta(meta);
        return { ok: true };
      });

    default:
      return { ok: false, error: `未知命令: ${msg.cmd}` };
  }
}

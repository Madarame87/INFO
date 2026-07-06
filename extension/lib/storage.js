// chrome.storage 读写层：sync 分桶 + local 归档（ADR 0003）。
// 对外只暴露完整形态的 Queue Record，压缩编码在此层内完成。

import { BUCKET_KEYS, bucketKeyOf, encodeRecord, decodeRecord } from './codec.js';
import { isFinished } from './queue.js';

const META_KEY = 'aq:meta';
const ARCHIVE_KEY = 'aq:archive';
const ACKS_KEY = 'aq:acks';
const RUNS_KEY = 'aq:runs';
const FLOWS_KEY = 'aq:flows';

const ARCHIVE_AFTER_DAYS = 30;
const QUOTA_SOFT_LIMIT = 0.8;

export function defaultMeta(now) {
  return {
    version: 1,
    settings: {
      folders: ['收藏文章'],
      typeFolders: { podcast: ['收藏播客'] },
    },
    types: {
      translate: { label: '翻译', autoEnroll: true, createdAt: now },
      podcast: { label: '播客', autoEnroll: false, createdAt: now },
    },
  };
}

export async function loadMeta() {
  const got = await chrome.storage.sync.get(META_KEY);
  if (got[META_KEY]) {
    const meta = got[META_KEY];
    let changed = false;
    meta.settings ||= {};
    meta.settings.folders ||= ['收藏文章'];
    meta.settings.typeFolders ||= {};
    if (!meta.settings.typeFolders.podcast) {
      meta.settings.typeFolders.podcast = ['收藏播客'];
      changed = true;
    }
    meta.types ||= {};
    if (!meta.types.podcast) {
      meta.types.podcast = { label: '播客', autoEnroll: false, createdAt: new Date().toISOString() };
      changed = true;
    }
    if (changed) await saveMeta(meta);
    return meta;
  }
  const meta = defaultMeta(new Date().toISOString());
  await chrome.storage.sync.set({ [META_KEY]: meta });
  return meta;
}

export async function saveMeta(meta) {
  await chrome.storage.sync.set({ [META_KEY]: meta });
}

export async function loadActive() {
  const got = await chrome.storage.sync.get(BUCKET_KEYS);
  const map = new Map();
  for (const bk of BUCKET_KEYS) {
    for (const [key, enc] of Object.entries(got[bk] || {})) {
      map.set(key, decodeRecord(key, enc));
    }
  }
  return map;
}

export async function getRecord(articleKey) {
  const bk = bucketKeyOf(articleKey);
  const got = await chrome.storage.sync.get(bk);
  const enc = (got[bk] || {})[articleKey];
  return enc ? decodeRecord(articleKey, enc) : null;
}

export async function putRecords(records) {
  if (!records.length) return;
  const byBucket = new Map();
  for (const rec of records) {
    const bk = bucketKeyOf(rec.articleKey);
    if (!byBucket.has(bk)) byBucket.set(bk, []);
    byBucket.get(bk).push(rec);
  }
  const keys = [...byBucket.keys()];
  const cur = await chrome.storage.sync.get(keys);
  const set = {};
  for (const bk of keys) {
    const bucket = cur[bk] || {};
    for (const rec of byBucket.get(bk)) bucket[rec.articleKey] = encodeRecord(rec);
    set[bk] = bucket;
  }
  await chrome.storage.sync.set(set);
}

// 仅从 sync 活跃桶里删除，不碰 archive。归档搬迁与彻底删除都复用它。
async function removeFromBuckets(articleKeys) {
  const byBucket = new Map();
  for (const key of articleKeys) {
    const bk = bucketKeyOf(key);
    if (!byBucket.has(bk)) byBucket.set(bk, []);
    byBucket.get(bk).push(key);
  }
  const keys = [...byBucket.keys()];
  const cur = await chrome.storage.sync.get(keys);
  const set = {};
  for (const bk of keys) {
    const bucket = cur[bk] || {};
    for (const key of byBucket.get(bk)) delete bucket[key];
    set[bk] = bucket;
  }
  await chrome.storage.sync.set(set);
}

// 彻底删除：从活跃桶与归档都移除（Dashboard「删除」）。
export async function removeRecords(articleKeys) {
  if (!articleKeys.length) return;
  await removeFromBuckets(articleKeys);
  const archive = await rawArchive();
  let touched = false;
  for (const key of articleKeys) {
    if (key in archive) {
      delete archive[key];
      touched = true;
    }
  }
  if (touched) await chrome.storage.local.set({ [ARCHIVE_KEY]: archive });
}

async function rawArchive() {
  return (await chrome.storage.local.get(ARCHIVE_KEY))[ARCHIVE_KEY] || {};
}

export async function loadArchive() {
  const raw = await rawArchive();
  const map = new Map();
  for (const [key, enc] of Object.entries(raw)) map.set(key, decodeRecord(key, enc));
  return map;
}

async function archiveRecords(records) {
  if (!records.length) return;
  const archive = await rawArchive();
  for (const rec of records) archive[rec.articleKey] = encodeRecord(rec);
  await chrome.storage.local.set({ [ARCHIVE_KEY]: archive });
  await removeFromBuckets(records.map((r) => r.articleKey));
}

// 归档触发：全部 job 完成且 30 天未更新；或 sync 用量超软限时从最旧完成记录开始腾挪。
export async function compact(now) {
  const active = await loadActive();
  const finished = [...active.values()].filter(isFinished)
    .sort((a, b) => (a.updatedAt < b.updatedAt ? -1 : 1));
  const cutoff = new Date(new Date(now).getTime() - ARCHIVE_AFTER_DAYS * 86400_000).toISOString();
  const old = finished.filter((r) => r.updatedAt < cutoff);
  if (old.length) await archiveRecords(old);

  const { bytes, total } = await quotaUsage();
  if (bytes / total > QUOTA_SOFT_LIMIT) {
    const rest = finished.filter((r) => !(r.updatedAt < cutoff));
    const evict = rest.slice(0, Math.ceil(rest.length / 2));
    if (evict.length) await archiveRecords(evict);
  }
  return { archived: old.length };
}

export async function quotaUsage() {
  const bytes = await chrome.storage.sync.getBytesInUse(null);
  return { bytes, total: chrome.storage.sync.QUOTA_BYTES || 102400 };
}

export async function getAcks() {
  return (await chrome.storage.local.get(ACKS_KEY))[ACKS_KEY] || [];
}

export async function setAcks(ids) {
  await chrome.storage.local.set({ [ACKS_KEY]: ids });
}

export async function getFlows() {
  return (await chrome.storage.local.get(FLOWS_KEY))[FLOWS_KEY] || {};
}

export async function setFlows(flows) {
  await chrome.storage.local.set({ [FLOWS_KEY]: flows });
}

export async function getRuns() {
  return (await chrome.storage.local.get(RUNS_KEY))[RUNS_KEY] || {};
}

export async function setRun(name, info) {
  const runs = await getRuns();
  runs[name] = info;
  await chrome.storage.local.set({ [RUNS_KEY]: runs });
}

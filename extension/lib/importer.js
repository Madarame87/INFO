// 书签导入：只读 chrome.bookmarks，把配置文件夹（含子文件夹）下的链接合并进队列。

import { normalizeUrl } from './normalize.js';
import { mergeSource } from './queue.js';
import * as store from './storage.js';

function findFolders(nodes, names, found) {
  for (const node of nodes) {
    if (!node.url && names.includes(node.title)) found.push(node);
    if (node.children) findFolders(node.children, names, found);
  }
}

function collectUrls(node, folderName, items) {
  for (const child of node.children || []) {
    if (child.url) items.push({ url: child.url, title: child.title || '', id: child.id, folderName });
    else collectUrls(child, folderName, items);
  }
}

export function importFolderNames(meta) {
  return [...new Set([
    ...(meta.settings.folders || []),
    ...Object.values(meta.settings.typeFolders || {}).flat(),
  ].filter(Boolean))];
}

export function autoTypesForFolder(meta, folderName) {
  const routed = Object.entries(meta.settings.typeFolders || {})
    .filter(([, folders]) => (folders || []).includes(folderName))
    .map(([type]) => type)
    .filter((type) => meta.types[type]);
  if (routed.length) return routed;
  return Object.entries(meta.types)
    .filter(([, t]) => t.autoEnroll)
    .map(([id]) => id);
}

export async function importFromBookmarks() {
  const meta = await store.loadMeta();
  const folders = importFolderNames(meta);

  const tree = await chrome.bookmarks.getTree();
  const found = [];
  findFolders(tree, folders, found);
  const items = [];
  for (const f of found) collectUrls(f, f.title, items);

  const active = await store.loadActive();
  const archive = await store.loadArchive();
  const now = new Date().toISOString();
  const changedRecs = [];
  let added = 0;
  let merged = 0;
  let skippedArchived = 0;

  for (const it of items) {
    const key = normalizeUrl(it.url);
    if (!key) continue;
    if (archive.has(key)) {
      skippedArchived++;
      continue;
    }
    const prev = active.get(key) || null;
    const { record, changed } = mergeSource(prev, {
      articleKey: key,
      url: it.url,
      title: it.title,
      source: { kind: 'bookmark', folderName: it.folderName, bookmarkId: it.id },
      autoTypes: autoTypesForFolder(meta, it.folderName),
      now,
    });
    if (changed) {
      changedRecs.push(record);
      active.set(key, record);
      prev ? merged++ : added++;
    }
  }
  await store.putRecords(changedRecs);
  return { folders: found.length, scanned: items.length, added, merged, skippedArchived };
}

import test from 'node:test';
import assert from 'node:assert/strict';
import { autoTypesForFolder, importFolderNames } from '../extension/lib/importer.js';
import { defaultMeta } from '../extension/lib/storage.js';

test('默认扫描文章收藏夹和收藏播客', () => {
  const meta = defaultMeta('2026-07-06T00:00:00Z');
  assert.deepEqual(importFolderNames(meta), ['收藏文章', '收藏播客']);
});

test('收藏播客文件夹只路由到 podcast', () => {
  const meta = defaultMeta('2026-07-06T00:00:00Z');
  assert.deepEqual(autoTypesForFolder(meta, '收藏播客'), ['podcast']);
  assert.deepEqual(autoTypesForFolder(meta, '收藏文章'), ['translate']);
});

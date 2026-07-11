import test from 'node:test';
import assert from 'node:assert/strict';
import { encodeRecord, decodeRecord, bucketIdFor, bucketKeyOf, BUCKET_COUNT, BUCKET_KEYS } from '../extension/lib/codec.js';

const sample = {
  articleKey: 'https://example.com/post',
  url: 'https://example.com/post',
  title: '一篇文章',
  sources: [
    { kind: 'bookmark', folderName: '收藏文章', bookmarkId: '123', importedAt: '2026-07-05T00:00:00Z' },
    { kind: 'manual', folderName: null, bookmarkId: null, importedAt: '2026-07-05T01:00:00Z' },
  ],
  jobs: {
    translate: { status: 'pending', processedAt: null, updatedAt: '2026-07-05T00:00:00Z', attempts: 0, lastError: null, meta: {} },
    book: { status: 'failed', processedAt: null, updatedAt: '2026-07-05T02:00:00Z', attempts: 2, lastError: 'pi exit 1', meta: { a: 1 } },
  },
  createdAt: '2026-07-05T00:00:00Z',
  updatedAt: '2026-07-05T02:00:00Z',
};

test('encode → decode 完整往返', () => {
  const enc = encodeRecord(sample);
  const dec = decodeRecord(sample.articleKey, enc);
  assert.deepEqual(dec, sample);
});

test('Summary/Tags 元数据经过 sync 压缩后完整保留', () => {
  const enriched = structuredClone(sample);
  enriched.jobs.translate.meta = {
    savedTo: 'article.md',
    summary: '这是一段文章摘要。',
    tags: ['智能体', '模型评估'],
  };
  const decoded = decodeRecord(enriched.articleKey, encodeRecord(enriched));
  assert.deepEqual(decoded.jobs.translate.meta, enriched.jobs.translate.meta);
});

test('压缩编码显著小于完整形态', () => {
  const enc = JSON.stringify(encodeRecord(sample));
  const full = JSON.stringify(sample);
  assert.ok(enc.length < full.length * 0.75, `${enc.length} vs ${full.length}`);
});

test('分桶稳定且在范围内', () => {
  const id = bucketIdFor(sample.articleKey);
  assert.equal(id, bucketIdFor(sample.articleKey));
  assert.ok(id >= 0 && id < BUCKET_COUNT);
  assert.ok(BUCKET_KEYS.includes(bucketKeyOf(sample.articleKey)));
});

test('不同 key 大体分散到不同桶', () => {
  const buckets = new Set();
  for (let i = 0; i < 100; i++) buckets.add(bucketIdFor(`https://a.com/p${i}`));
  assert.ok(buckets.size > 16, `只用了 ${buckets.size} 个桶`);
});

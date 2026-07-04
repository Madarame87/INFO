import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeSource, applyResult, setJobStatus, isFinished, outboxEntries, reclaimIfStale } from '../extension/lib/queue.js';

const NOW = '2026-07-05T10:00:00Z';
const LATER = '2026-07-05T11:00:00Z';
const KEY = 'https://a.com/p';
const bookmarkSource = { kind: 'bookmark', folderName: '收藏文章', bookmarkId: '9' };

function fresh() {
  return mergeSource(null, {
    articleKey: KEY, url: KEY, title: 'T',
    source: bookmarkSource, autoTypes: ['translate'], now: NOW,
  }).record;
}

test('首次导入：新建记录 + autoEnroll 类型自动 pending', () => {
  const rec = fresh();
  assert.equal(rec.jobs.translate.status, 'pending');
  assert.equal(rec.sources.length, 1);
});

test('重复导入同一书签：无变化，来源不重复', () => {
  const rec = fresh();
  const { record, changed } = mergeSource(rec, {
    articleKey: KEY, url: KEY, title: 'T',
    source: bookmarkSource, autoTypes: ['translate'], now: LATER,
  });
  assert.equal(changed, false);
  assert.equal(record.sources.length, 1);
});

test('done 后重复导入不复活为 pending', () => {
  let rec = fresh();
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: NOW }).record;
  const { record } = mergeSource(rec, {
    articleKey: KEY, url: KEY, title: 'T',
    source: { kind: 'bookmark', folderName: '收藏文章', bookmarkId: '10' },
    autoTypes: ['translate'], now: LATER,
  });
  assert.equal(record.jobs.translate.status, 'done');
});

test('报告先到（书签已删）：创建 done 记录，来源为 report', () => {
  const { record, changed } = applyResult(null, {
    articleKey: KEY, url: KEY, type: 'translate', status: 'done', processedAt: NOW, now: NOW,
  });
  assert.equal(changed, true);
  assert.equal(record.jobs.translate.status, 'done');
  assert.equal(record.sources[0].kind, 'report');
});

test('done 是幂等的', () => {
  let rec = applyResult(null, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: NOW }).record;
  const { changed } = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: LATER });
  assert.equal(changed, false);
});

test('failed 递增 attempts 且记录错误；不降级 done', () => {
  let rec = fresh();
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'failed', meta: { error: 'x' }, now: NOW }).record;
  assert.equal(rec.jobs.translate.status, 'failed');
  assert.equal(rec.jobs.translate.attempts, 1);
  assert.equal(rec.jobs.translate.lastError, 'x');
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: NOW }).record;
  const { record, changed } = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'failed', now: LATER });
  assert.equal(changed, false);
  assert.equal(record.jobs.translate.status, 'done');
});

test('done 覆盖 ignored（外部流已实际完成）', () => {
  let rec = fresh();
  rec = setJobStatus(rec, 'translate', 'ignored', NOW);
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: LATER }).record;
  assert.equal(rec.jobs.translate.status, 'done');
});

test('重新排队清空 processedAt 与 lastError', () => {
  let rec = fresh();
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: NOW }).record;
  rec = setJobStatus(rec, 'translate', 'pending', LATER);
  assert.equal(rec.jobs.translate.status, 'pending');
  assert.equal(rec.jobs.translate.processedAt, null);
});

test('processing 认领：pending/failed 可认领，done/ignored 不降级', () => {
  let rec = fresh();
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'processing', now: NOW }).record;
  assert.equal(rec.jobs.translate.status, 'processing');
  assert.equal(rec.jobs.translate.attempts, 0);
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: LATER }).record;
  const { record, changed } = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'processing', now: LATER });
  assert.equal(changed, false);
  assert.equal(record.jobs.translate.status, 'done');
});

test('processing 不进 outbox（防重复认领）', () => {
  let rec = fresh();
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'processing', now: NOW }).record;
  const map = new Map([[KEY, rec]]);
  assert.deepEqual(outboxEntries(map, 'translate'), []);
});

test('reclaimIfStale：processing 回退 pending，其余状态不动', () => {
  let rec = fresh();
  assert.equal(reclaimIfStale(rec, 'translate', LATER), null);
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'processing', now: NOW }).record;
  const reverted = reclaimIfStale(rec, 'translate', LATER);
  assert.equal(reverted.jobs.translate.status, 'pending');
  assert.equal(reverted.jobs.translate.attempts, 0);
});

test('isFinished：processing 不算完成', () => {
  let rec = fresh();
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'processing', now: NOW }).record;
  assert.equal(isFinished(rec), false);
});

test('isFinished：全部 job done/ignored 才算完成', () => {
  let rec = fresh();
  assert.equal(isFinished(rec), false);
  rec = applyResult(rec, { articleKey: KEY, url: KEY, type: 'translate', status: 'done', now: NOW }).record;
  assert.equal(isFinished(rec), true);
  rec = mergeSource(rec, {
    articleKey: KEY, url: KEY, title: 'T', source: { kind: 'manual' }, autoTypes: ['book'], now: LATER,
  }).record;
  assert.equal(isFinished(rec), false);
});

test('outbox 含 pending 与 failed，不含 done/ignored，按入队时间排序', () => {
  const map = new Map();
  const mk = (key, status, created) => {
    let rec = mergeSource(null, {
      articleKey: key, url: key, title: key,
      source: { kind: 'manual' }, autoTypes: ['translate'], now: created,
    }).record;
    if (status !== 'pending') rec = setJobStatus(rec, 'translate', status, created);
    map.set(key, rec);
  };
  mk('https://a.com/2', 'pending', '2026-07-05T02:00:00Z');
  mk('https://a.com/1', 'pending', '2026-07-05T01:00:00Z');
  mk('https://a.com/3', 'done', '2026-07-05T03:00:00Z');
  mk('https://a.com/4', 'ignored', '2026-07-05T04:00:00Z');
  const f = map.get('https://a.com/2');
  map.set('https://a.com/2', applyResult(f, {
    articleKey: 'https://a.com/2', url: 'https://a.com/2', type: 'translate', status: 'failed', now: '2026-07-05T05:00:00Z',
  }).record);

  const entries = outboxEntries(map, 'translate');
  assert.deepEqual(entries.map((e) => e.articleKey), ['https://a.com/1', 'https://a.com/2']);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_SUMMARY_CHARS,
  collectTagCounts,
  jobSummary,
  jobTags,
  normalizeSummaryTags,
} from '../extension/lib/enrichment.js';

test('摘要限长，标签别名归一、去重并限制为 5 个', () => {
  const meta = normalizeSummaryTags({
    savedTo: 'x.md',
    summary: `  ${'摘要内容 '.repeat(80)}  `,
    tags: ['AI', '人工智能', '#Agent', 'agents', 'Memory Systems', '开源', '产品', '芯片'],
  });
  assert.equal(meta.savedTo, 'x.md');
  assert.equal(meta.summary.length, MAX_SUMMARY_CHARS);
  assert.ok(meta.summary.endsWith('…'));
  assert.deepEqual(meta.tags, ['人工智能', '智能体', '记忆系统', '开源', '产品']);
});

test('旧报告缺少摘要和标签时保持兼容', () => {
  assert.deepEqual(normalizeSummaryTags({ savedTo: 'old.md' }), { savedTo: 'old.md' });
  assert.equal(jobSummary({ meta: {} }), '');
  assert.deepEqual(jobTags({ meta: {} }), []);
});

test('相同标签按文章计数并按数量排序', () => {
  const records = [
    { jobs: { translate: { meta: { tags: ['智能体', '模型评估'] } } } },
    { jobs: { translate: { meta: { tags: ['智能体', '记忆系统'] } } } },
    { jobs: { podcast: { meta: { tags: ['智能体'] } } } },
  ];
  assert.deepEqual([...collectTagCounts(records, 'translate')], [
    ['智能体', 2],
    ['记忆系统', 1],
    ['模型评估', 1],
  ]);
});

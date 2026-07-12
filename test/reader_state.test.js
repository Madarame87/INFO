import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(join(ROOT, 'reader', 'assets', 'app.js'), 'utf8');

function loadApi() {
  const window = {
    matchMedia() { return { matches: true }; },
    addEventListener() {},
    setTimeout,
    navigator: {},
    localStorage: null,
  };
  const document = {
    body: { classList: { contains() { return false; } } },
    querySelectorAll() { return []; },
    getElementById() { return null; },
  };
  vm.runInNewContext(source, { window, document, setTimeout });
  return window.InfoCollectorReader;
}

test('新文章、收藏、完成整理、取消收藏与恢复待整理遵守状态语义', () => {
  const api = loadApi();
  const now = '2026-07-12T01:02:03.000Z';
  const initial = api.stateFor({}, 'stable-id');
  assert.deepEqual({ ...initial }, { reviewedAt: null, favorite: false });
  assert.equal(api.matchesView(initial, 'pending'), true);

  const favorite = api.toggleFavoriteState(initial, now);
  assert.deepEqual({ ...favorite }, { reviewedAt: now, favorite: true });
  assert.equal(api.matchesView(favorite, 'pending'), false);
  assert.equal(api.matchesView(favorite, 'favorites'), true);

  const unfavorited = api.toggleFavoriteState(favorite, 'later');
  assert.deepEqual({ ...unfavorited }, { reviewedAt: now, favorite: false });
  assert.equal(api.matchesView(unfavorited, 'pending'), false);
  assert.equal(api.matchesView(unfavorited, 'favorites'), false);

  const reviewed = api.toggleReviewedState(initial, now);
  assert.deepEqual({ ...reviewed }, { reviewedAt: now, favorite: false });
  assert.equal(api.matchesView(reviewed, 'pending'), false);
  const restored = api.toggleReviewedState(reviewed, 'later');
  assert.deepEqual({ ...restored }, { reviewedAt: null, favorite: false });
});

test('localStorage 损坏安全回退，稳定 ID 在重排后仍恢复同一状态', () => {
  const api = loadApi();
  assert.deepEqual({ ...api.parseReaderState('{broken') }, {});
  assert.deepEqual({ ...api.parseReaderState('null') }, {});
  const parsed = api.parseReaderState(JSON.stringify({
    'stable-b': { reviewedAt: '2026-07-12T00:00:00Z', favorite: true },
    invalid: 'noise',
  }));
  const reorderedIds = ['stable-c', 'stable-a', 'stable-b'];
  assert.equal(api.stateFor(parsed, reorderedIds[2]).favorite, true);
  assert.equal(api.stateFor(parsed, reorderedIds[0]).favorite, false);
  let stored = '';
  const storage = {
    getItem() { return stored; },
    setItem(_key, value) { stored = value; },
  };
  assert.equal(api.saveReaderState(storage, parsed), true);
  assert.equal(api.loadReaderState(storage)['stable-b'].favorite, true);
  const disabled = {
    getItem() { throw new Error('disabled'); },
    setItem() { throw new Error('disabled'); },
  };
  assert.deepEqual({ ...api.loadReaderState(disabled) }, {});
  assert.equal(api.saveReaderState(disabled, parsed), false);
});

test('主视图与关键词筛选取交集', () => {
  const api = loadApi();
  const items = [
    { tags: '智能体|产品', state: { reviewedAt: null, favorite: false } },
    { tags: '世界模型|产品', state: { reviewedAt: 'x', favorite: true } },
    { tags: '世界模型|学术研究', state: { reviewedAt: 'x', favorite: false } },
  ];
  const favoritesWorldModels = items.filter((item) => (
    api.matchesView(item.state, 'favorites') && api.matchesTag(item.tags, '世界模型')
  ));
  assert.equal(favoritesWorldModels.length, 1);
  assert.equal(items.filter((item) => api.matchesView(item.state, 'pending')).length, 1);
  assert.equal(items.filter((item) => api.matchesView(item.state, 'all')).length, 3);
  assert.equal(api.emptyMessageFor('pending', '全部'), '待整理已清空');
  assert.equal(api.emptyMessageFor('favorites', '全部'), '还没有收藏文章');
  assert.equal(api.emptyMessageFor('favorites', '世界模型'), '没有符合条件的文章');
});

test('每周阅读统计不可筛选文章，并可导出带状态的七天回顾', () => {
  const api = loadApi();
  const now = new Date(2026, 6, 12, 12, 0, 0);
  assert.equal(api.isDateInCurrentWeek(new Date(2026, 6, 6, 9, 0, 0), now), true);
  assert.equal(api.isDateInCurrentWeek(new Date(2026, 6, 12, 23, 59, 0), now), true);
  assert.equal(api.isDateInCurrentWeek(new Date(2026, 6, 5, 23, 59, 0), now), false);
  const series = api.weeklyActivitySeries([
    { reviewedAt: new Date(2026, 6, 12, 10).toISOString(), favorite: true },
    { reviewedAt: new Date(2026, 6, 8, 10).toISOString(), favorite: false },
    { reviewedAt: new Date(2026, 6, 3, 10).toISOString(), favorite: true },
  ], now, 2);
  assert.deepEqual({ ...series[0] }, {
    start: '2026-06-29', end: '2026-07-05', shortStart: '06.29', shortEnd: '07.05', count: 1, favorites: 1,
  });
  assert.deepEqual({ ...series[1] }, {
    start: '2026-07-06', end: '2026-07-12', shortStart: '07.06', shortEnd: '07.12', count: 2, favorites: 1,
  });
  const markdown = api.buildWeeklyReviewMarkdown([{
    title: '世界模型进展',
    source: 'https://example.test/world-model',
    tags: '世界模型|机器人',
    summary: '一段可核验的摘要。',
    favorite: true,
  }], now);
  assert.match(markdown, /# 每周阅读回顾｜2026-07-06 — 2026-07-12/);
  assert.match(markdown, /共判断 1 篇｜收藏 1 篇｜已整理 0 篇/);
  assert.match(markdown, /状态：收藏/);
  assert.match(markdown, /关键词：世界模型、机器人/);
  assert.match(markdown, /\[查看原文\]\(https:\/\/example\.test\/world-model\)/);
});

test('复制资料卡字段顺序准确，旧文缺失值使用未知和整理时间', () => {
  const api = loadApi();
  const markdown = api.buildInfoCardMarkdown({
    title: 'A &amp; B',
    source: '',
    authors: 'null',
    published: '',
    collected: '',
    processed: '2026-07-11',
    tags: '智能体|产品',
    summary: '一段 &lt;中性&gt; 摘要',
  });
  assert.equal(markdown, [
    '# A & B',
    '',
    '原文：未知',
    '作者：未知',
    '发布时间：未知',
    '收录时间：未知',
    '整理时间：2026-07-11',
    '关键词：智能体、产品',
    '',
    '## 摘要',
    '',
    '一段 <中性> 摘要',
    '',
  ].join('\n'));
  assert.equal(markdown.includes('undefined'), false);
  assert.equal(markdown.includes('null'), false);
  assert.equal(markdown.includes('&amp;'), false);
});

test('Clipboard API 成功、失败与 textarea fallback 都可验证', async () => {
  const api = loadApi();
  let written = '';
  assert.equal(await api.copyText('content', {
    navigator: { clipboard: { async writeText(value) { written = value; } } },
    document: {},
  }), true);
  assert.equal(written, 'content');

  let fallbackValue = '';
  const textarea = {
    value: '', style: {}, isConnected: true,
    setAttribute() {}, focus() {}, select() {}, remove() { this.isConnected = false; },
  };
  const fallbackDocument = {
    createElement() { return textarea; },
    body: { appendChild(element) { fallbackValue = element.value; } },
    execCommand(command) { return command === 'copy'; },
  };
  assert.equal(await api.copyText('fallback', {
    navigator: { clipboard: { async writeText() { throw new Error('denied'); } } },
    document: fallbackDocument,
  }), true);
  assert.equal(fallbackValue, 'fallback');
  assert.equal(textarea.isConnected, false);

  assert.equal(await api.copyText('failure', { navigator: {}, document: {} }), false);
});

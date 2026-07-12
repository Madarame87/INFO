import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

test('README 描述二次整理与浏览器本地状态，不再声称全文搜索或行业趋势', () => {
  const readme = readFileSync(join(ROOT, 'README.md'), 'utf8');
  for (const phrase of ['待整理', '我的收藏', '全部收录', '复制资料卡', 'localStorage', '不会跨浏览器或跨设备同步']) {
    assert.ok(readme.includes(phrase), `README 缺少：${phrase}`);
  }
  assert.equal(readme.includes('全文搜索'), false);
  assert.ok(readme.includes('不代表行业趋势或世界动态'));
});

test('Pages 自动部署只监听 main，同时保留手动触发', () => {
  const workflow = readFileSync(join(ROOT, '.github', 'workflows', 'deploy-reading-site.yml'), 'utf8');
  assert.match(workflow, /branches:\s*\n\s*- main/);
  assert.equal(workflow.includes('agent/windows-port'), false);
  assert.match(workflow, /workflow_dispatch:/);
});

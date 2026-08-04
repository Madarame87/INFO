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

test('Pages 部署只允许手动触发，避免项目站自动占用账号自定义域名路径', () => {
  const workflow = readFileSync(join(ROOT, '.github', 'workflows', 'deploy-reading-site.yml'), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.equal(workflow.includes('push:'), false);
  assert.equal(workflow.includes('pull_request:'), false);
});

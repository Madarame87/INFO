import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

test('README 保持简洁，并明确恢复、安全与商业边界', () => {
  const readme = readFileSync(join(ROOT, 'README.md'), 'utf8');
  for (const phrase of ['info-collector-2026.git', '401', '恢复队列', 'DPAPI', '最多 3 次', '受控商业 pilot']) {
    assert.ok(readme.includes(phrase), `README 缺少：${phrase}`);
  }
  assert.ok(readme.split(/\r?\n/).length < 70, 'README 应控制在 70 行内');
  assert.equal(readme.includes('工业级'), false);
});

test('Pages 部署只允许手动触发，避免项目站自动占用账号自定义域名路径', () => {
  const workflow = readFileSync(join(ROOT, '.github', 'workflows', 'deploy-reading-site.yml'), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.equal(workflow.includes('push:'), false);
  assert.equal(workflow.includes('pull_request:'), false);
});

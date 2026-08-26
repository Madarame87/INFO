import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

test('README 保持简洁，并围绕已验证的用户价值', () => {
  const readme = readFileSync(join(ROOT, 'README.md'), 'utf8');
  for (const phrase of ['一键收集', '快速读懂', '集中管理', '持续沉淀', '高效回顾']) {
    assert.ok(readme.includes(phrase), `README 缺少：${phrase}`);
  }
  assert.ok(readme.split(/\r?\n/).length < 30, 'README 应保持产品首页式的简洁篇幅');
  for (const engineeringDetail of ['401', 'DPAPI', '最多 3 次', '受控商业 pilot']) {
    assert.equal(readme.includes(engineeringDetail), false, `README 不应暴露工程细节：${engineeringDetail}`);
  }
});

test('Pages 部署只允许手动触发，避免项目站自动占用账号自定义域名路径', () => {
  const workflow = readFileSync(join(ROOT, '.github', 'workflows', 'deploy-reading-site.yml'), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.equal(workflow.includes('push:'), false);
  assert.equal(workflow.includes('pull_request:'), false);
});

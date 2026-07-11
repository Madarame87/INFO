import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

function idsIn(html) {
  return [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
}

function referencedIds(js) {
  return [...js.matchAll(/\$\('([^']+)'\)/g)].map((match) => match[1]);
}

for (const page of ['dashboard', 'popup']) {
  test(`${page} 页面 ID 契约完整且无重复`, () => {
    const htmlPath = join(ROOT, 'extension', `${page}.html`);
    const jsPath = join(ROOT, 'extension', `${page}.js`);
    const html = readFileSync(htmlPath, 'utf8');
    const js = readFileSync(jsPath, 'utf8');
    const ids = idsIn(html);
    assert.equal(new Set(ids).size, ids.length, `${page}.html 存在重复 id`);
    const missing = [...new Set(referencedIds(js))].filter((id) => !ids.includes(id));
    assert.deepEqual(missing, [], `${page}.js 引用了不存在的元素`);

    const cssLinks = [...html.matchAll(/<link[^>]+href="([^"]+\.css)"/g)]
      .map((match) => match[1]);
    assert.ok(cssLinks.length > 0, `${page}.html 未引用样式表`);
    for (const href of cssLinks) assert.ok(existsSync(join(ROOT, 'extension', href)), `缺少 ${href}`);
  });
}

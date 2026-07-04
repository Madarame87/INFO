import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeUrl } from '../extension/lib/normalize.js';

test('去掉 hash，主机名小写，路径大小写保留', () => {
  assert.equal(normalizeUrl('https://Example.COM/Post#section-2'), 'https://example.com/Post');
});

test('默认端口去掉，非默认端口保留', () => {
  assert.equal(normalizeUrl('https://a.com:443/x'), 'https://a.com/x');
  assert.equal(normalizeUrl('http://a.com:80/x'), 'http://a.com/x');
  assert.equal(normalizeUrl('http://a.com:8080/x'), 'http://a.com:8080/x');
});

test('空路径归一为 /，等价于显式 /', () => {
  assert.equal(normalizeUrl('https://a.com'), 'https://a.com/');
  assert.equal(normalizeUrl('https://a.com'), normalizeUrl('https://a.com/'));
});

test('深路径的尾斜杠保留原样（/a 与 /a/ 是不同 key）', () => {
  assert.notEqual(normalizeUrl('https://a.com/a'), normalizeUrl('https://a.com/a/'));
});

test('query 原样保留，含 utm_*', () => {
  assert.equal(
    normalizeUrl('https://a.com/p?utm_source=x&b=1'),
    'https://a.com/p?utm_source=x&b=1',
  );
});

test('空 query 的悬挂问号去掉', () => {
  assert.equal(normalizeUrl('https://a.com/x?'), 'https://a.com/x');
});

test('非 http(s) 与非法输入返回 null', () => {
  assert.equal(normalizeUrl('ftp://a.com/x'), null);
  assert.equal(normalizeUrl('chrome://extensions'), null);
  assert.equal(normalizeUrl('not a url'), null);
  assert.equal(normalizeUrl(''), null);
});

test('前后空白容忍', () => {
  assert.equal(normalizeUrl('  https://a.com/x  '), 'https://a.com/x');
});

// Queue Record 的压缩编解码与分桶（ADR 0003）。
// sync 配额按字节计，存储侧用短字段名；storage 层之外只见完整形态。

export const BUCKET_COUNT = 32;

export function fnv1a(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

export function bucketIdFor(articleKey) {
  return fnv1a(articleKey) % BUCKET_COUNT;
}

export function bucketKeyOf(articleKey) {
  return 'aq:b:' + bucketIdFor(articleKey).toString(16).padStart(2, '0');
}

export const BUCKET_KEYS = Array.from({ length: BUCKET_COUNT }, (_, i) =>
  'aq:b:' + i.toString(16).padStart(2, '0'));

function strip(obj) {
  for (const k of Object.keys(obj)) {
    if (obj[k] === undefined || obj[k] === null) delete obj[k];
  }
  return obj;
}

export function encodeRecord(rec) {
  const out = { u: rec.url, c: rec.createdAt, d: rec.updatedAt };
  if (rec.title) out.t = rec.title;
  out.s = (rec.sources || []).map((s) =>
    strip({ k: s.kind, f: s.folderName, b: s.bookmarkId, a: s.importedAt }));
  out.j = {};
  for (const [type, j] of Object.entries(rec.jobs || {})) {
    out.j[type] = strip({
      s: j.status,
      p: j.processedAt,
      u: j.updatedAt,
      n: j.attempts || undefined,
      e: j.lastError || undefined,
      m: j.meta && Object.keys(j.meta).length ? j.meta : undefined,
    });
  }
  return out;
}

export function decodeRecord(articleKey, enc) {
  return {
    articleKey,
    url: enc.u,
    title: enc.t || '',
    sources: (enc.s || []).map((s) => ({
      kind: s.k,
      folderName: s.f ?? null,
      bookmarkId: s.b ?? null,
      importedAt: s.a ?? null,
    })),
    jobs: Object.fromEntries(Object.entries(enc.j || {}).map(([type, j]) => [type, {
      status: j.s,
      processedAt: j.p ?? null,
      updatedAt: j.u ?? null,
      attempts: j.n || 0,
      lastError: j.e ?? null,
      meta: j.m || {},
    }])),
    createdAt: enc.c,
    updatedAt: enc.d,
  };
}

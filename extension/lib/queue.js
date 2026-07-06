// 队列状态机：纯函数，不碰 chrome API，可在 node 下直接测试。
// 语义见 CONTEXT.md 与 docs/design.md。

export const STATUSES = ['pending', 'processing', 'done', 'failed', 'ignored'];

export function newRecord(articleKey, url, title, now) {
  return { articleKey, url, title: title || '', sources: [], jobs: {}, createdAt: now, updatedAt: now };
}

function newJob(now) {
  return { status: 'pending', processedAt: null, updatedAt: now, attempts: 0, lastError: null, meta: {} };
}

// 从来源（书签导入 / toolbar 手动 / 报告先到）合并一篇文章；record 为 null 时新建。
// 已存在的 job 不会被复活：done/ignored 的文章重复导入仍保持原状态。
export function mergeSource(record, { articleKey, url, title, source, autoTypes = [], now }) {
  const rec = record ? structuredClone(record) : newRecord(articleKey, url, title, now);
  let changed = !record;
  if (!rec.title && title) {
    rec.title = title;
    changed = true;
  }
  const dup = rec.sources.some((s) => s.kind === source.kind
    && (s.bookmarkId ?? null) === (source.bookmarkId ?? null)
    && (s.folderName ?? null) === (source.folderName ?? null));
  if (!dup) {
    rec.sources.push({
      kind: source.kind,
      folderName: source.folderName ?? null,
      bookmarkId: source.bookmarkId ?? null,
      importedAt: now,
    });
    changed = true;
  }
  for (const type of autoTypes) {
    if (!rec.jobs[type]) {
      rec.jobs[type] = newJob(now);
      changed = true;
    }
  }
  if (changed) rec.updatedAt = now;
  return { record: rec, changed };
}

// 应用报告的一条结果。record 为 null 时创建记录（书签可能已被用户删掉，
// 但处理历史必须留存）。done 覆盖一切含 ignored；failed/processing 不降级
// done/ignored。processing 是外部流的「认领」：流程启动时写认领报告，
// 桥接发现流程未在运行时由 reclaimIfStale 回退（崩溃自愈）。
export function applyResult(record, { articleKey, url, type, status, processedAt, meta, now }) {
  let rec;
  if (record) {
    rec = structuredClone(record);
  } else {
    rec = newRecord(articleKey, url, '', now);
    rec.sources.push({ kind: 'report', folderName: null, bookmarkId: null, importedAt: now });
  }
  const j = rec.jobs[type] ? structuredClone(rec.jobs[type]) : newJob(now);
  if (status === 'done') {
    if (j.status === 'done') return { record: rec, changed: !record };
    j.status = 'done';
    j.processedAt = processedAt || now;
    j.lastError = null;
  } else if (status === 'failed') {
    if (j.status === 'done' || j.status === 'ignored') return { record: rec, changed: !record };
    j.status = 'failed';
    j.attempts = (j.attempts || 0) + 1;
    j.lastError = (meta && meta.error) || 'failed';
  } else if (status === 'processing') {
    if (j.status === 'done' || j.status === 'ignored' || j.status === 'processing') {
      return { record: rec, changed: !record };
    }
    j.status = 'processing';
  } else {
    return { record: record ?? rec, changed: !record };
  }
  j.updatedAt = now;
  if (meta) j.meta = { ...j.meta, ...meta };
  rec.jobs[type] = j;
  rec.updatedAt = now;
  return { record: rec, changed: true };
}

// Dashboard 手动操作：pending（重新排队）/ done / ignored。
export function setJobStatus(record, type, status, now) {
  const rec = structuredClone(record);
  const j = rec.jobs[type] ? structuredClone(rec.jobs[type]) : newJob(now);
  j.status = status;
  j.updatedAt = now;
  if (status === 'done' && !j.processedAt) j.processedAt = now;
  if (status === 'pending') {
    j.processedAt = null;
    j.lastError = null;
  }
  rec.jobs[type] = j;
  rec.updatedAt = now;
  return rec;
}

export function manualSaveTypes(meta, requestedTypes) {
  if (requestedTypes === undefined) {
    return Object.entries(meta.types).filter(([, t]) => t.autoEnroll).map(([id]) => id);
  }
  const types = [...new Set((requestedTypes || []).map((s) => String(s).trim()).filter(Boolean))];
  if (!types.length) throw new Error('至少选择一个处理类型');
  const missing = types.find((id) => !meta.types[id]);
  if (missing) throw new Error(`处理类型 ${missing} 未注册`);
  return types;
}

// 认领过期回退：流程已不在运行却仍是 processing → 回到 pending（不计失败次数）。
// 本次会话刚认领的（updatedAt === now）不回退：那可能是流程在启动、其
// running 状态尚未在同一次桥接里体现，避免把刚认领的文章误退回重复处理。
export function reclaimIfStale(record, type, now) {
  const j = record.jobs[type];
  if (!j || j.status !== 'processing') return null;
  if (j.updatedAt === now) return null;
  return setJobStatus(record, type, 'pending', now);
}

// 归档判据：至少一个 job，且全部 done/ignored。
export function isFinished(record) {
  const jobs = Object.values(record.jobs || {});
  return jobs.length > 0 && jobs.every((j) => j.status === 'done' || j.status === 'ignored');
}

// 某类型的 outbox 内容：pending 与 failed（failed 留在清单里等待重试）。
export function outboxEntries(recordsMap, type) {
  const out = [];
  for (const rec of recordsMap.values()) {
    const j = rec.jobs[type];
    if (j && (j.status === 'pending' || j.status === 'failed')) {
      out.push({ articleKey: rec.articleKey, url: rec.url, title: rec.title, enqueuedAt: rec.createdAt });
    }
  }
  out.sort((a, b) => (a.enqueuedAt < b.enqueuedAt ? -1 : 1));
  return out;
}

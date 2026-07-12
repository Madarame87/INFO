// Dashboard：读操作直接走 storage 层，全部写操作发消息给 service worker 串行执行。

import * as store from './lib/storage.js';
import { collectTagCounts, jobSummary, jobTags } from './lib/enrichment.js';

const $ = (id) => document.getElementById(id);

const STATUS_TEXT = { pending: '⏳ 待处理', processing: '⚙ 处理中', done: '✓ 已完成', failed: '✕ 失败', ignored: '– 已忽略' };

let meta;
let active = new Map();
let archive = new Map();
let flows = {};
const view = { type: '', status: '', tag: '', q: '', archived: false };

async function refresh() {
  meta = await store.loadMeta();
  active = await store.loadActive();
  archive = await store.loadArchive();
  flows = await store.getFlows();
  if (!meta.types[view.type]) view.type = Object.keys(meta.types)[0] || '';
  renderTypeSelects();
  renderTiles();
  renderRuns();
  renderTagControls();
  renderTable();
}

function renderTypeSelects() {
  for (const sel of [$('f-type'), $('bulk-type')]) {
    sel.innerHTML = '';
    for (const [id, t] of Object.entries(meta.types)) {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = t.label === id ? id : `${t.label} (${id})`;
      sel.appendChild(opt);
    }
  }
  $('f-type').value = view.type;
  $('s-folders').value = (meta.settings.folders || []).join(', ');
  $('s-podcast-folders').value = ((meta.settings.typeFolders || {}).podcast || []).join(', ');
}

function renderTiles() {
  const counts = { pending: 0, processing: 0, done: 0, failed: 0, ignored: 0 };
  for (const rec of active.values()) {
    const j = rec.jobs[view.type];
    if (j && counts[j.status] !== undefined) counts[j.status]++;
  }
  $('n-pending').textContent = counts.pending;
  $('n-processing').textContent = counts.processing;
  $('n-failed').textContent = counts.failed;
  $('n-done').textContent = counts.done;
  $('n-ignored').textContent = counts.ignored;
  $('n-archived').textContent = archive.size;
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const status = $('hero-status');
  const substatus = $('hero-substatus');
  if (counts.failed) {
    document.body.dataset.health = 'alert';
    status.textContent = `${counts.failed} 条任务需要关注`;
    substatus.textContent = `其余 ${Math.max(total - counts.failed, 0)} 条记录保持正常`;
  } else if (counts.processing) {
    document.body.dataset.health = 'busy';
    status.textContent = `${counts.processing} 条任务正在处理中`;
    substatus.textContent = `本地流程运行中 · 已完成 ${counts.done} 条`;
  } else {
    document.body.dataset.health = 'healthy';
    status.textContent = counts.pending ? `${counts.pending} 条情报等待处理` : '本地情报系统运行正常';
    substatus.textContent = `当前视图 ${total} 条 · 已完成 ${counts.done} 条 · 无运行故障`;
  }
  store.quotaUsage().then(({ bytes, total }) => {
    const pct = Math.round((bytes / total) * 100);
    $('quota-text').textContent = `${(bytes / 1024).toFixed(1)} / ${(total / 1024).toFixed(0)} KB（${pct}%）`;
    const fill = $('quota-fill');
    fill.style.width = `${Math.min(pct, 100)}%`;
    fill.classList.toggle('hot', pct >= 80);
  });
}

const OUTCOME_TEXT = {
  success: '✓ 成功', failed: '✕ 失败', empty: '空队列', running: '运行中',
  'no-outbox': 'outbox 缺失', error: '✕ 出错',
};
const SPECIAL_FLOW_LABELS = { 'weekly-report': '周报', 'reading-site': '阅读站' };

function fmtTime(iso) {
  if (!iso) return '?';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function fmtDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function stationEl(name, infoHtml, state) {
  const div = document.createElement('div');
  div.className = 'station' + (state ? ` station-${state}` : '');
  div.innerHTML = `<span class="st-name">${escapeHtml(name)}</span><span class="st-info">${infoHtml}</span>`;
  return div;
}

async function renderRuns() {
  const runs = await store.getRuns();
  const wrap = $('runs');
  wrap.innerHTML = '';
  const stations = [];

  for (const [key, label] of [['import', '书签导入'], ['bridge', '桥接同步']]) {
    const r = runs[key];
    if (!r) stations.push(stationEl(label, '<span class="muted">未运行</span>'));
    else if (r.ok) stations.push(stationEl(label, `${fmtTime(r.at)} ✓`, 'ok'));
    else stations.push(stationEl(label, `${fmtTime(r.at)} ✕ ${escapeHtml(r.error || '')}`, 'err'));
  }

  for (const [type, f] of Object.entries(flows)) {
    const label = `${SPECIAL_FLOW_LABELS[type] || meta.types[type]?.label || type}流`;
    const st = f.status || {};
    const lr = st.lastRun;
    let info;
    let state;
    if (f.running) {
      info = '⚙ 正在运行…';
      state = 'busy';
    } else if (lr) {
      info = `${fmtTime(lr.startedAt)} ${escapeHtml(OUTCOME_TEXT[lr.outcome] || lr.outcome)}（${lr.trigger === 'manual' ? '手动' : '定时'}${lr.count ? `，${lr.count} 篇` : ''}）`;
      state = (lr.outcome === 'success' || lr.outcome === 'empty') ? 'ok' : 'err';
    } else {
      info = '<span class="muted">未运行</span>';
    }
    if (st.lastScheduledStartAt && f.intervalSeconds) {
      let next = new Date(st.lastScheduledStartAt).getTime() + f.intervalSeconds * 1000;
      while (next < Date.now()) next += f.intervalSeconds * 1000;
      info += `<span class="st-next">下次定时 ≈ ${fmtTime(new Date(next).toISOString())}</span>`;
    }
    if (type === 'weekly-report' && lr?.latestReport) {
      const reportName = lr.latestReport.split(/[\\/]/).pop();
      info += `<span class="st-next" title="${escapeAttr(lr.latestReport)}">输出：${escapeHtml(reportName)}</span>`;
    }
    if (type === 'reading-site' && lr?.siteIndex) {
      info += `<span class="st-next" title="${escapeAttr(lr.siteIndex)}">输出：本地文章阅读库</span>`;
    }
    stations.push(stationEl(label, info, state));
  }

  stations.forEach((el, i) => {
    if (i) {
      const link = document.createElement('span');
      link.className = 'st-link';
      wrap.appendChild(link);
    }
    wrap.appendChild(el);
  });
  if (!stations.length) wrap.textContent = '尚未运行。';
}

function matches(rec) {
  const j = rec.jobs[view.type];
  if (!j) return false;
  if (view.status && (!j || j.status !== view.status)) return false;
  const tags = jobTags(j);
  if (view.tag && !tags.includes(view.tag)) return false;
  if (view.q) {
    const q = view.q.toLowerCase();
    const haystack = [rec.title, rec.url, jobSummary(j), ...tags].join('\n').toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  return true;
}

function renderTagControls() {
  const records = [...active.values()];
  if (view.archived) records.push(...archive.values());
  const counts = collectTagCounts(records, view.type);
  if (view.tag && !counts.has(view.tag)) view.tag = '';

  const select = $('f-tag');
  select.innerHTML = '<option value="">全部标签</option>';
  for (const [tag, count] of counts) {
    const opt = document.createElement('option');
    opt.value = tag;
    opt.textContent = `${tag}（${count}）`;
    select.appendChild(opt);
  }
  select.value = view.tag;

  const groups = $('tag-groups');
  groups.innerHTML = '';
  groups.hidden = counts.size === 0;
  $('tag-cloud-wrap').hidden = counts.size === 0;
  for (const [tag, count] of counts) {
    const button = document.createElement('button');
    button.className = 'tag-chip' + (tag === view.tag ? ' active' : '');
    button.dataset.tag = tag;
    button.textContent = `${tag} ${count}`;
    groups.appendChild(button);
  }
}

function renderTable() {
  const rows = [];
  for (const rec of active.values()) if (matches(rec)) rows.push({ rec, archived: false });
  if (view.archived) {
    for (const rec of archive.values()) if (matches(rec)) rows.push({ rec, archived: true });
  }
  rows.sort((a, b) => (a.rec.updatedAt < b.rec.updatedAt ? 1 : -1));
  $('visible-count').textContent = rows.length;

  const tbody = $('rows');
  tbody.innerHTML = '';
  $('empty').hidden = rows.length > 0;

  for (const { rec, archived } of rows) {
    const tr = document.createElement('tr');
    tr.dataset.key = rec.articleKey;

    const tdA = document.createElement('td');
    tdA.innerHTML = `<div class="title"><a href="${escapeAttr(rec.url)}" target="_blank" rel="noopener">${escapeHtml(rec.title || '(无标题)')}</a>${archived ? '<span class="badge-archived">归档</span>' : ''}</div><div class="url">${escapeHtml(rec.articleKey)}</div>`;
    const summary = jobSummary(rec.jobs[view.type]);
    if (summary) {
      const div = document.createElement('div');
      div.className = 'article-summary';
      div.textContent = summary;
      tdA.appendChild(div);
    }
    const tags = jobTags(rec.jobs[view.type]);
    if (tags.length) {
      const div = document.createElement('div');
      div.className = 'article-tags';
      for (const tag of tags) {
        const button = document.createElement('button');
        button.className = 'tag-chip';
        button.dataset.tag = tag;
        button.textContent = tag;
        div.appendChild(button);
      }
      tdA.appendChild(div);
    }

    const tdS = document.createElement('td');
    const j = rec.jobs[view.type];
    if (j) {
      const chip = document.createElement('span');
      chip.className = `chip st-${j.status}`;
      chip.textContent = STATUS_TEXT[j.status] || j.status;
      chip.title = j.lastError || '';
      tdS.appendChild(chip);
      if (j.attempts > 1) tdS.append(` ×${j.attempts}`);
    } else {
      tdS.textContent = '—';
    }

    const tdSrc = document.createElement('td');
    tdSrc.className = 'src';
    tdSrc.textContent = [...new Set(rec.sources.map((s) => ({
      bookmark: `书签:${s.folderName || '?'}`, manual: '手动', report: '报告',
    }[s.kind] || s.kind)))].join('、');

    const tdT = document.createElement('td');
    tdT.className = 'time';
    tdT.textContent = fmtDateTime(rec.updatedAt);

    const tdOps = document.createElement('td');
    tdOps.className = 'ops';
    if (!archived && j) {
      if (j.status === 'pending' || j.status === 'failed') {
        if (flows[view.type]?.triggerable) tdOps.append(opBtn('▶ 立即处理', 'trigger'));
        tdOps.append(opBtn('完成', 'done'), opBtn('忽略', 'ignored'));
      } else if (j.status === 'processing') {
        tdOps.append(opBtn('完成', 'done'), opBtn('重新排队', 'pending'));
      } else {
        tdOps.append(opBtn('重新排队', 'pending'));
      }
    }
    tdOps.append(opBtn('删除', 'delete'));

    tr.append(tdA, tdS, tdSrc, tdT, tdOps);
    tbody.appendChild(tr);
  }
}

function opBtn(label, op) {
  const b = document.createElement('button');
  b.textContent = label;
  b.dataset.op = op;
  return b;
}

$('rows').addEventListener('click', async (e) => {
  const tagButton = e.target.closest('button[data-tag]');
  if (tagButton) {
    view.tag = tagButton.dataset.tag;
    renderTagControls();
    renderTable();
    return;
  }
  const btn = e.target.closest('button[data-op]');
  if (!btn) return;
  const key = btn.closest('tr').dataset.key;
  const op = btn.dataset.op;
  if (op === 'trigger') {
    toast('触发中：先桥接刷新 outbox，再启动流程…');
    await send({ cmd: 'bridgeNow' });
    const r = await send({ cmd: 'triggerFlow', type: view.type });
    if (r?.ok && r.alreadyRunning) toast('⏳ 流程已在运行中，无需重复触发');
    else if (r?.ok) {
      toast(`✓ 已启动「${meta.types[view.type]?.label || view.type}」流程：将处理该类型全部待处理文章，完成后自动回报`);
      // 流程启动后立刻写认领报告，稍等再桥接一次让「处理中」马上可见
      setTimeout(async () => {
        await send({ cmd: 'bridgeNow' });
        refresh();
      }, 2500);
    } else {
      toast(`✕ 触发失败：${r?.error || '未知错误'}（flows.json 是否已注册？重新运行 scripts/setup.sh）`);
    }
    refresh();
    return;
  }
  if (op === 'delete') {
    if (!confirm('删除这条记录（含处理历史）？重新导入会当作新文章。')) return;
    await send({ cmd: 'deleteRecords', keys: [key] });
  } else {
    await send({ cmd: 'setJobStatus', keys: [key], type: view.type, status: op });
  }
  refresh();
});

$('tag-groups').addEventListener('click', (e) => {
  const button = e.target.closest('button[data-tag]');
  if (!button) return;
  view.tag = view.tag === button.dataset.tag ? '' : button.dataset.tag;
  renderTagControls();
  renderTable();
});

async function send(msg) {
  const resp = await chrome.runtime.sendMessage(msg);
  if (resp && !resp.ok && resp.error) toast(`✕ ${resp.error}`);
  return resp;
}

let toastTimer;
function toast(text) {
  const el = $('toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

$('btn-import').addEventListener('click', async () => {
  toast('导入中…');
  const r = await send({ cmd: 'importNow' });
  if (r?.ok) toast(`✓ 导入完成：扫描 ${r.scanned}，新增 ${r.added}，合并 ${r.merged}，跳过归档 ${r.skippedArchived}`);
  else toast(`✕ 导入失败：${r?.error || '未知错误'}`);
  refresh();
});

$('btn-bridge').addEventListener('click', async () => {
  toast('桥接同步中…');
  const r = await send({ cmd: 'bridgeNow' });
  if (r?.ok) {
    let t = `✓ 桥接完成：收到报告 ${r.reports}，应用 ${r.applied}`;
    if (r.hostErrors?.length) t += `；host 警告：${r.hostErrors.join('；')}`;
    toast(t);
  } else {
    toast(`✕ 桥接失败：${r?.error || '未知错误'}（native host 是否已安装？运行 scripts/setup.sh）`);
  }
  refresh();
});

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitForFlow(type, previousRun, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  let observedRunning = false;
  while (Date.now() < deadline) {
    await delay(750);
    await send({ cmd: 'bridgeNow' });
    await refresh();
    const lastRun = flows[type]?.status?.lastRun;
    if (lastRun?.outcome === 'running') observedRunning = true;
    const changed = lastRun?.startedAt !== previousRun?.startedAt || lastRun?.finishedAt !== previousRun?.finishedAt;
    if (lastRun?.startedAt && (changed || observedRunning) && lastRun.outcome !== 'running') {
      return lastRun;
    }
  }
  return null;
}

$('btn-weekly').addEventListener('click', async () => {
  const previousRun = flows['weekly-report']?.status?.lastRun;
  toast('正在生成本周处理回顾…');
  const r = await send({ cmd: 'triggerFlow', type: 'weekly-report' });
  if (!r?.ok) {
    toast(`✕ 处理回顾启动失败：${r?.error || '未知错误'}（请重新运行 scripts/setup.ps1）`);
    return;
  }
  if (r.alreadyRunning) {
    toast('⏳ 处理回顾正在生成中');
    return;
  }
  toast('⏳ 正在汇总本周已处理文章，请稍候…');
  const lastRun = await waitForFlow('weekly-report', previousRun);
  if (!lastRun) {
    toast('⏳ 处理回顾仍在后台生成，可稍后再次查看');
  } else if (lastRun.outcome === 'success' || lastRun.outcome === 'empty') {
    const opened = await send({ cmd: 'openFlowOutput', type: 'weekly-report' });
    toast(opened?.ok
      ? `✓ 本周处理回顾已生成：${lastRun.count || 0} 篇，正在打开`
      : `✓ 已生成 ${lastRun.count || 0} 篇；${opened?.error || '请从输出目录打开'}`);
  } else {
    toast(`✕ 处理回顾生成失败：${lastRun.error || '查看 weekly-report.log'}`);
  }
});

$('btn-reader').addEventListener('click', async () => {
  const previousRun = flows['reading-site']?.status?.lastRun;
  toast('正在构建文章阅读库…');
  const r = await send({ cmd: 'triggerFlow', type: 'reading-site' });
  if (!r?.ok) {
    toast(`✕ 阅读库启动失败：${r?.error || '未知错误'}（请重新运行 scripts/setup.ps1）`);
    return;
  }
  if (r.alreadyRunning) {
    toast('⏳ 阅读库正在生成中');
    return;
  }
  toast('⏳ 阅读库正在生成，完成后会自动打开');
  const lastRun = await waitForFlow('reading-site', previousRun);
  if (!lastRun) {
    toast('⏳ 阅读库仍在后台生成，可稍后再次打开');
  } else if (lastRun.outcome === 'success' || lastRun.outcome === 'empty') {
    toast(`✓ 阅读库已更新：${lastRun.count || 0} 篇文章`);
  } else {
    toast(`✕ 阅读库生成失败：${lastRun.error || '查看 reading-site.log'}`);
  }
});

$('btn-bulk').addEventListener('click', () => {
  $('bulk-type').value = view.type;
  $('bulk-urls').value = '';
  $('bulk-dialog').showModal();
});

$('bulk-dialog').addEventListener('close', async () => {
  if ($('bulk-dialog').returnValue !== 'ok') return;
  const urls = $('bulk-urls').value.split('\n').map((s) => s.trim()).filter(Boolean);
  if (!urls.length) return;
  const r = await send({ cmd: 'bulkDone', type: $('bulk-type').value, urls });
  if (r?.ok) toast(`✓ 已标记 ${r.applied} 条完成，跳过 ${r.skipped} 条`);
  refresh();
});

$('btn-export').addEventListener('click', () => {
  const data = {
    exportedAt: new Date().toISOString(),
    meta,
    active: Object.fromEntries(active),
    archive: Object.fromEntries(archive),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `info-collector-export-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
});

$('f-type').addEventListener('change', (e) => {
  view.type = e.target.value;
  view.tag = '';
  renderTiles();
  renderTagControls();
  renderTable();
});
$('f-status').addEventListener('change', (e) => { view.status = e.target.value; renderTable(); });
$('f-tag').addEventListener('change', (e) => { view.tag = e.target.value; renderTagControls(); renderTable(); });
$('f-q').addEventListener('input', (e) => { view.q = e.target.value.trim(); renderTable(); });
$('f-archived').addEventListener('change', (e) => {
  view.archived = e.target.checked;
  renderTagControls();
  renderTable();
});

$('s-folders-save').addEventListener('click', async () => {
  const folders = $('s-folders').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  const podcastFolders = $('s-podcast-folders').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  const r = await send({ cmd: 'setFolders', folders, podcastFolders });
  if (r?.ok) toast('✓ 已保存文件夹设置');
  refresh();
});

$('s-type-add').addEventListener('click', async () => {
  const r = await send({
    cmd: 'addType',
    id: $('s-type-id').value,
    label: $('s-type-label').value.trim(),
    autoEnroll: $('s-type-auto').checked,
  });
  if (r?.ok) {
    toast('✓ 已添加处理类型');
    $('s-type-id').value = '';
    $('s-type-label').value = '';
    $('s-type-auto').checked = false;
  }
  refresh();
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s);
}

let refreshTimer;
chrome.storage.onChanged.addListener(() => {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 400);
});

refresh();

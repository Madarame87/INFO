// Dashboard：读操作直接走 storage 层，全部写操作发消息给 service worker 串行执行。

import * as store from './lib/storage.js';

const $ = (id) => document.getElementById(id);

const STATUS_TEXT = { pending: '⏳ 待处理', processing: '⚙ 处理中', done: '✓ 已完成', failed: '✕ 失败', ignored: '– 已忽略' };

let meta;
let active = new Map();
let archive = new Map();
let flows = {};
const view = { type: '', status: '', q: '', archived: false };

async function refresh() {
  meta = await store.loadMeta();
  active = await store.loadActive();
  archive = await store.loadArchive();
  flows = await store.getFlows();
  if (!meta.types[view.type]) view.type = Object.keys(meta.types)[0] || '';
  renderTypeSelects();
  renderTiles();
  renderRuns();
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
    const label = `${meta.types[type]?.label || type}流`;
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
  if (view.status && (!j || j.status !== view.status)) return false;
  if (view.q) {
    const q = view.q.toLowerCase();
    if (!rec.title.toLowerCase().includes(q) && !rec.url.toLowerCase().includes(q)) return false;
  }
  return true;
}

function renderTable() {
  const rows = [];
  for (const rec of active.values()) if (matches(rec)) rows.push({ rec, archived: false });
  if (view.archived) {
    for (const rec of archive.values()) if (matches(rec)) rows.push({ rec, archived: true });
  }
  rows.sort((a, b) => (a.rec.updatedAt < b.rec.updatedAt ? 1 : -1));

  const tbody = $('rows');
  tbody.innerHTML = '';
  $('empty').hidden = rows.length > 0;

  for (const { rec, archived } of rows) {
    const tr = document.createElement('tr');
    tr.dataset.key = rec.articleKey;

    const tdA = document.createElement('td');
    tdA.innerHTML = `<div class="title"><a href="${escapeAttr(rec.url)}" target="_blank" rel="noopener">${escapeHtml(rec.title || '(无标题)')}</a>${archived ? '<span class="badge-archived">归档</span>' : ''}</div><div class="url">${escapeHtml(rec.articleKey)}</div>`;

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
    if (!archived) {
      if (!j) {
        tdOps.append(opBtn('加入队列', 'pending'));
      } else if (j.status === 'pending' || j.status === 'failed') {
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

$('f-type').addEventListener('change', (e) => { view.type = e.target.value; renderTiles(); renderTable(); });
$('f-status').addEventListener('change', (e) => { view.status = e.target.value; renderTable(); });
$('f-q').addEventListener('input', (e) => { view.q = e.target.value.trim(); renderTable(); });
$('f-archived').addEventListener('change', (e) => { view.archived = e.target.checked; renderTable(); });

$('s-folders-save').addEventListener('click', async () => {
  const folders = $('s-folders').value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  const r = await send({ cmd: 'setFolders', folders });
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

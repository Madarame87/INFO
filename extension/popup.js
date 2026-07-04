const $ = (id) => document.getElementById(id);

const STATUS_TEXT = { pending: '⏳ 待处理', processing: '⚙ 处理中', done: '✓ 已完成', failed: '✕ 失败', ignored: '– 已忽略' };

let tab;

async function render() {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $('title').textContent = tab?.title || '';
  const resp = await chrome.runtime.sendMessage({ cmd: 'getTabStatus', url: tab?.url || '' });
  const box = $('status');
  const save = $('save');
  if (!resp.ok || !resp.queueable) {
    box.textContent = '该页面无法入队（仅支持 http/https）。';
    save.hidden = true;
    return;
  }
  if (!resp.record) {
    box.textContent = '尚未入队。';
    save.hidden = false;
    return;
  }
  const jobs = Object.entries(resp.record.jobs || {});
  box.innerHTML = '';
  if (resp.archived) {
    const p = document.createElement('div');
    p.textContent = '已归档（处理历史保留）';
    box.appendChild(p);
  }
  if (!jobs.length) box.append('已入队，暂无处理任务。');
  for (const [type, j] of jobs) {
    const row = document.createElement('div');
    row.className = 'job';
    const name = document.createElement('span');
    name.textContent = type;
    const st = document.createElement('span');
    st.className = `st st-${j.status}`;
    st.textContent = STATUS_TEXT[j.status] || j.status;
    row.append(name, st);
    box.appendChild(row);
  }
  save.hidden = true;
}

$('save').addEventListener('click', async () => {
  $('save').disabled = true;
  const resp = await chrome.runtime.sendMessage({ cmd: 'saveTab', url: tab.url, title: tab.title });
  $('save').disabled = false;
  if (!resp.ok) {
    $('status').textContent = resp.error || '保存失败';
    return;
  }
  render();
});

$('dashboard').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') });
});

render();

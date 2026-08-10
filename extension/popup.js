const $ = (id) => document.getElementById(id);

const STATUS_TEXT = { pending: '⏳ 待处理', processing: '⚙ 处理中', done: '✓ 已完成', failed: '✕ 失败', ignored: '– 已忽略' };
const TYPE_TEXT = { translate: '文章翻译', podcast: '播客处理' };

let tab;

async function captureCurrentPage() {
  if (!tab?.id) return null;
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const selectorsToRemove = [
        'script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer', 'aside',
        'form', 'dialog', 'button', 'input', 'select', 'textarea', '[role="navigation"]',
        '[role="dialog"]', '[aria-modal="true"]', '[hidden]',
        '[class*="cookie" i]', '[id*="cookie" i]', '[class*="consent" i]',
        '[class*="newsletter" i]', '[class*="subscribe" i]', '[class*="social-share" i]',
      ];
      const roots = [...document.querySelectorAll('article, main, [role="main"]')];
      if (!roots.length && document.body) roots.push(document.body);
      let best = '';
      for (const root of roots) {
        const copy = root.cloneNode(true);
        for (const selector of selectorsToRemove) {
          try { copy.querySelectorAll(selector).forEach((node) => node.remove()); } catch { /* ignore */ }
        }
        const text = String(copy.innerText || copy.textContent || '')
          .replace(/[ \t\f\v]+/g, ' ')
          .replace(/\n\s*/g, '\n')
          .replace(/\n{3,}/g, '\n\n')
          .trim();
        if (text.length > best.length) best = text;
      }
      const meta = (names) => {
        for (const name of names) {
          const node = document.querySelector(`meta[name="${name}"], meta[property="${name}"]`);
          if (node?.content) return node.content.trim();
        }
        return '';
      };
      const published = meta(['article:published_time', 'date', 'datePublished']);
      const authors = meta(['author', 'article:author', 'byl']);
      return {
        title: meta(['og:title', 'twitter:title']) || document.title || '',
        published,
        authors,
        content: best.slice(0, 750000),
      };
    },
  });
  const capture = result?.result;
  return capture?.content?.length >= 160 ? capture : null;
}

async function render() {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $('title').textContent = tab?.title || '';
  const resp = await chrome.runtime.sendMessage({ cmd: 'getTabStatus', url: tab?.url || '' });
  const box = $('status');
  const save = $('save');
  const savePodcast = $('save-podcast');
  if (!resp.ok || !resp.queueable) {
    box.textContent = '该页面无法入队（仅支持 http/https）。';
    box.dataset.tone = 'bad';
    save.hidden = true;
    savePodcast.hidden = true;
    return;
  }
  if (!resp.record) {
    box.textContent = '尚未入队，可以加入文章处理流水线。';
    box.dataset.tone = 'idle';
    save.hidden = false;
    savePodcast.hidden = false;
    return;
  }
  const jobs = Object.entries(resp.record.jobs || {});
  box.innerHTML = '';
  const states = jobs.map(([, job]) => job.status);
  box.dataset.tone = states.includes('failed') ? 'bad'
    : states.includes('processing') ? 'busy'
      : states.length && states.every((state) => state === 'done' || state === 'ignored') ? 'good' : 'idle';
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
    name.textContent = TYPE_TEXT[type] || type;
    const st = document.createElement('span');
    st.className = `st st-${j.status}`;
    st.textContent = STATUS_TEXT[j.status] || j.status;
    row.append(name, st);
    box.appendChild(row);
  }
  save.hidden = true;
  savePodcast.hidden = resp.archived || !!resp.record.jobs?.podcast;
}

async function save(types, button) {
  button.disabled = true;
  button.textContent = '正在读取当前页面…';
  let capture = null;
  try {
    capture = await captureCurrentPage();
  } catch (_error) {
    // Restricted browser pages may reject script injection; network extraction remains available.
  }
  const resp = await chrome.runtime.sendMessage({ cmd: 'saveTab', url: tab.url, title: tab.title, types, capture });
  button.disabled = false;
  button.textContent = types?.includes('podcast') ? '加入播客队列' : '加入文章队列';
  if (!resp.ok) {
    $('status').textContent = resp.error || '保存失败';
    $('status').dataset.tone = 'bad';
    return;
  }
  if (resp.captureWarning) {
    $('status').textContent = `已入队；页面快照未保存：${resp.captureWarning}`;
    $('status').dataset.tone = 'bad';
    return;
  }
  render();
}

$('save').addEventListener('click', () => save(undefined, $('save')));
$('save-podcast').addEventListener('click', () => save(['podcast'], $('save-podcast')));

$('dashboard').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') });
});

render();

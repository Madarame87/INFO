(() => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const STORAGE_KEY = 'info-collector:reader-state:v1';

  function normalizeReaderState(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const normalized = {};
    for (const [articleId, raw] of Object.entries(value)) {
      if (!articleId || !raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
      normalized[articleId] = {
        reviewedAt: typeof raw.reviewedAt === 'string' && raw.reviewedAt.trim() ? raw.reviewedAt : null,
        favorite: raw.favorite === true,
      };
    }
    return normalized;
  }

  function parseReaderState(raw) {
    try {
      return normalizeReaderState(JSON.parse(raw || '{}'));
    } catch (_error) {
      return {};
    }
  }

  function stateFor(readerState, articleId) {
    return readerState[articleId] || { reviewedAt: null, favorite: false };
  }

  function matchesView(articleState, view) {
    if (view === 'favorites') return articleState.favorite === true;
    if (view === 'all') return true;
    return articleState.reviewedAt === null && articleState.favorite === false;
  }

  function matchesTag(tags, activeTag) {
    return activeTag === '全部' || String(tags || '').split('|').includes(activeTag);
  }

  function toggleFavoriteState(articleState, now) {
    return articleState.favorite
      ? { reviewedAt: articleState.reviewedAt || now, favorite: false }
      : { reviewedAt: articleState.reviewedAt || now, favorite: true };
  }

  function toggleReviewedState(articleState, now) {
    return (articleState.reviewedAt || articleState.favorite)
      ? { reviewedAt: null, favorite: false }
      : { reviewedAt: now, favorite: false };
  }

  function emptyMessageFor(view, tag) {
    if (tag !== '全部') return '没有符合条件的文章';
    if (view === 'pending') return '待整理已清空';
    if (view === 'favorites') return '还没有收藏文章';
    return '没有符合条件的文章';
  }

  function cleanCardValue(value) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (!text || /^(?:undefined|null)$/i.test(text)) return '';
    return text.replace(/&(amp|lt|gt|quot|#39);/g, (_match, entity) => ({
      amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'",
    })[entity]);
  }

  function buildInfoCardMarkdown(data) {
    const title = cleanCardValue(data.title) || '未命名文章';
    const source = cleanCardValue(data.source) || '未知';
    const authors = cleanCardValue(data.authors) || '未知';
    const published = cleanCardValue(data.published) || '未知';
    const collected = cleanCardValue(data.collected) || '未知';
    const processed = cleanCardValue(data.processed);
    const tags = String(data.tags || '').split('|').map(cleanCardValue).filter(Boolean);
    const summary = cleanCardValue(data.summary) || '暂无摘要';
    const lines = [
      `# ${title}`,
      '',
      `原文：${source}`,
      `作者：${authors}`,
      `发布时间：${published}`,
      `收录时间：${collected}`,
    ];
    if (collected === '未知' && processed) lines.push(`整理时间：${processed}`);
    lines.push(`关键词：${tags.length ? tags.join('、') : '未知'}`, '', '## 摘要', '', summary);
    return `${lines.join('\n')}\n`;
  }

  function loadReaderState(storage) {
    try {
      return parseReaderState(storage?.getItem(STORAGE_KEY));
    } catch (_error) {
      return {};
    }
  }

  function saveReaderState(storage, value) {
    try {
      storage?.setItem(STORAGE_KEY, JSON.stringify(value));
      return true;
    } catch (_error) {
      return false;
    }
  }

  function fallbackCopy(text, doc) {
    if (!doc?.createElement || !doc.body?.appendChild || typeof doc.execCommand !== 'function') return false;
    const textarea = doc.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    doc.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    let copied = false;
    try {
      copied = doc.execCommand('copy') === true;
    } finally {
      textarea.remove();
    }
    return copied;
  }

  async function copyText(text, environment = {}) {
    const nav = environment.navigator || window.navigator;
    const doc = environment.document || document;
    if (nav?.clipboard?.writeText) {
      try {
        await nav.clipboard.writeText(text);
        return true;
      } catch (_error) {
        // file:// and restricted browser contexts commonly need the fallback.
      }
    }
    try {
      return fallbackCopy(text, doc);
    } catch (_error) {
      return false;
    }
  }

  window.InfoCollectorReader = Object.freeze({
    STORAGE_KEY,
    normalizeReaderState,
    parseReaderState,
    stateFor,
    matchesView,
    matchesTag,
    toggleFavoriteState,
    toggleReviewedState,
    emptyMessageFor,
    buildInfoCardMarkdown,
    loadReaderState,
    saveReaderState,
    copyText,
  });

  function revealContent() {
    const elements = [...document.querySelectorAll('.reveal')];
    if (reducedMotion || !('IntersectionObserver' in window)) {
      elements.forEach((element) => element.classList.add('is-visible'));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    }, { threshold: 0.08, rootMargin: '0px 0px -40px' });
    elements.forEach((element) => observer.observe(element));
  }

  function initLibrary() {
    const viewFilters = document.getElementById('view-filters');
    const filters = document.getElementById('tag-filters');
    const grid = document.getElementById('article-grid');
    const cards = [...document.querySelectorAll('.article-card')];
    const count = document.getElementById('result-count');
    const empty = document.getElementById('empty-state');
    const emptyTitle = document.getElementById('empty-title');
    if (!viewFilters || !filters || !grid) return;

    let storage = null;
    try {
      storage = window.localStorage;
    } catch (_error) {
      storage = null;
    }
    let readerState = loadReaderState(storage);
    let activeView = viewFilters.querySelector('[data-view][aria-pressed="true"]')?.dataset.view || 'pending';
    let activeTag = filters.querySelector('[data-tag][aria-pressed="true"]')?.dataset.tag || '全部';

    function cardState(card) {
      return stateFor(readerState, card.dataset.articleId);
    }

    function updateCard(card) {
      const articleState = cardState(card);
      card.classList.toggle('is-favorite', articleState.favorite);
      card.classList.toggle('is-reviewed', Boolean(articleState.reviewedAt) || articleState.favorite);
      const favorite = card.querySelector('[data-action="favorite"]');
      const review = card.querySelector('[data-action="review"]');
      if (favorite) {
        favorite.textContent = articleState.favorite ? '已收藏' : '收藏';
        favorite.setAttribute('aria-pressed', articleState.favorite ? 'true' : 'false');
      }
      if (review) review.textContent = (articleState.reviewedAt || articleState.favorite) ? '恢复待整理' : '完成整理';
    }

    function updateViewCounts() {
      const totals = { pending: 0, favorites: 0, all: cards.length };
      for (const card of cards) {
        const articleState = cardState(card);
        if (matchesView(articleState, 'pending')) totals.pending += 1;
        if (matchesView(articleState, 'favorites')) totals.favorites += 1;
      }
      document.querySelectorAll('[data-count-view]').forEach((element) => {
        element.textContent = String(totals[element.dataset.countView] ?? 0);
      });
    }

    function emptyMessage() {
      return emptyMessageFor(activeView, activeTag);
    }

    function applyFilters() {
      let visible = 0;
      for (const card of cards) {
        const tagMatch = matchesTag(card.dataset.tags, activeTag);
        const show = tagMatch && matchesView(cardState(card), activeView);
        card.hidden = !show;
        if (show) visible += 1;
      }
      if (count) count.textContent = `显示 ${visible} 篇`;
      if (empty) empty.hidden = visible !== 0;
      if (emptyTitle) emptyTitle.textContent = emptyMessage();
    }

    function renderLibrary() {
      cards.forEach(updateCard);
      updateViewCounts();
      applyFilters();
    }

    viewFilters.addEventListener('click', (event) => {
      const button = event.target.closest('[data-view]');
      if (!button) return;
      activeView = button.dataset.view;
      viewFilters.querySelectorAll('[data-view]').forEach((item) => {
        item.classList.toggle('is-active', item === button);
        item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
      });
      applyFilters();
    });

    filters.addEventListener('click', (event) => {
      const button = event.target.closest('[data-tag]');
      if (!button) return;
      activeTag = button.dataset.tag;
      filters.querySelectorAll('[data-tag]').forEach((item) => {
        item.classList.toggle('is-active', item === button);
        item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
      });
      applyFilters();
    });

    grid.addEventListener('click', async (event) => {
      const action = event.target.closest('[data-action]');
      if (!action) return;
      const card = action.closest('.article-card');
      if (!card) return;
      event.preventDefault();
      event.stopPropagation();
      const articleId = card.dataset.articleId;
      const current = cardState(card);
      if (action.dataset.action === 'favorite') {
        const now = new Date().toISOString();
        readerState[articleId] = toggleFavoriteState(current, now);
        saveReaderState(storage, readerState);
        renderLibrary();
        return;
      }
      if (action.dataset.action === 'review') {
        readerState[articleId] = toggleReviewedState(current, new Date().toISOString());
        saveReaderState(storage, readerState);
        renderLibrary();
        return;
      }
      if (action.dataset.action === 'copy-card') {
        const originalLabel = action.textContent;
        const markdown = buildInfoCardMarkdown({
          title: card.dataset.title,
          source: card.dataset.source,
          authors: card.dataset.authors,
          published: card.dataset.publishedValue,
          collected: card.dataset.collectedValue,
          processed: card.dataset.processedValue,
          tags: card.dataset.tags,
          summary: card.dataset.summary,
        });
        const copied = await copyText(markdown);
        action.textContent = copied ? '已复制' : '复制失败';
        window.setTimeout(() => {
          if (action.isConnected) action.textContent = originalLabel;
        }, 1400);
      }
    });

    renderLibrary();
  }

  function initArticle() {
    const content = document.getElementById('article-content');
    const toc = document.getElementById('article-toc');
    if (!content || !toc) return;
    const headings = [...content.querySelectorAll('h2[id], h3[id]')];
    if (!headings.length) {
      toc.innerHTML = '<span>本文没有分节标题</span>';
    } else {
      toc.innerHTML = '';
      headings.forEach((heading) => {
        const link = document.createElement('a');
        link.href = `#${heading.id}`;
        link.textContent = heading.textContent;
        link.dataset.level = heading.tagName === 'H3' ? '3' : '2';
        toc.appendChild(link);
      });
      if ('IntersectionObserver' in window) {
        const links = new Map([...toc.querySelectorAll('a')].map((link) => [link.hash.slice(1), link]));
        const observer = new IntersectionObserver((entries) => {
          const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
          if (!visible.length) return;
          links.forEach((link) => link.classList.remove('is-active'));
          links.get(visible[0].target.id)?.classList.add('is-active');
        }, { rootMargin: '-110px 0px -70% 0px', threshold: 0 });
        headings.forEach((heading) => observer.observe(heading));
      }
    }

    document.querySelectorAll('.copy-code').forEach((button) => {
      button.addEventListener('click', async () => {
        const code = button.parentElement?.querySelector('code')?.textContent || '';
        try {
          await navigator.clipboard.writeText(code);
          button.textContent = '已复制';
          setTimeout(() => { button.textContent = '复制'; }, 1200);
        } catch (_error) {
          button.textContent = '复制失败';
        }
      });
    });
  }

  function initReadingProgress() {
    const bar = document.getElementById('reading-progress-bar');
    if (!bar || !document.body.classList.contains('article-page')) return;
    const update = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
      bar.style.width = `${progress * 100}%`;
    };
    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
  }

  revealContent();
  initLibrary();
  initArticle();
  initReadingProgress();
})();

(() => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

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
    const search = document.getElementById('article-search');
    const filters = document.getElementById('tag-filters');
    const cards = [...document.querySelectorAll('.article-card')];
    const count = document.getElementById('result-count');
    const empty = document.getElementById('empty-state');
    if (!search || !filters || !cards.length) return;

    let activeTag = '全部';
    const normalize = (value) => String(value || '').trim().toLocaleLowerCase('zh-CN');

    function applyFilters() {
      const query = normalize(search.value);
      let visible = 0;
      for (const card of cards) {
        const tags = (card.dataset.tags || '').split('|');
        const tagMatch = activeTag === '全部' || tags.includes(activeTag);
        const searchMatch = !query || normalize(card.dataset.search).includes(query);
        const show = tagMatch && searchMatch;
        card.hidden = !show;
        if (show) visible += 1;
      }
      count.textContent = `显示 ${visible} 篇`;
      empty.hidden = visible !== 0;
    }

    search.addEventListener('input', applyFilters);
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

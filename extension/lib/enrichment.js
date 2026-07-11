// Summary/Tags 的边界层：Completion Report 进入 sync storage 前统一限长、去重。

export const MAX_SUMMARY_CHARS = 240;
export const MAX_TAGS = 5;
export const MAX_TAG_CHARS = 24;

const TAG_ALIASES = new Map(Object.entries({
  ai: '人工智能',
  'artificial intelligence': '人工智能',
  llm: '大模型',
  llms: '大模型',
  'large language model': '大模型',
  'large language models': '大模型',
  大语言模型: '大模型',
  agent: '智能体',
  agents: '智能体',
  'ai agent': '智能体',
  'ai agents': '智能体',
  eval: '模型评估',
  evals: '模型评估',
  evaluation: '模型评估',
  'model evaluation': '模型评估',
  memory: '记忆系统',
  'memory system': '记忆系统',
  'memory systems': '记忆系统',
  robotics: '机器人',
  'embodied ai': '具身智能',
  'world model': '世界模型',
  'world models': '世界模型',
}));

function cleanSummary(value) {
  if (typeof value !== 'string') return '';
  const clean = value.replace(/\s+/g, ' ').trim();
  if (clean.length <= MAX_SUMMARY_CHARS) return clean;
  return clean.slice(0, MAX_SUMMARY_CHARS - 1).trimEnd() + '…';
}

function cleanTag(value) {
  let clean = String(value ?? '').replace(/\s+/g, ' ').trim().replace(/^[#＃]+/, '').trim();
  clean = TAG_ALIASES.get(clean.toLocaleLowerCase('en-US')) || clean;
  return clean.slice(0, MAX_TAG_CHARS).trim();
}

export function normalizeSummaryTags(meta = {}) {
  const out = { ...meta };
  const summary = cleanSummary(meta.summary);
  if (summary) out.summary = summary;
  else delete out.summary;

  const tags = [];
  const seen = new Set();
  for (const value of Array.isArray(meta.tags) ? meta.tags : []) {
    const tag = cleanTag(value);
    const key = tag.toLocaleLowerCase('en-US');
    if (!tag || seen.has(key)) continue;
    tags.push(tag);
    seen.add(key);
    if (tags.length === MAX_TAGS) break;
  }
  if (tags.length) out.tags = tags;
  else delete out.tags;
  return out;
}

export function jobSummary(job) {
  return typeof job?.meta?.summary === 'string' ? job.meta.summary : '';
}

export function jobTags(job) {
  return Array.isArray(job?.meta?.tags) ? job.meta.tags : [];
}

export function collectTagCounts(records, type) {
  const counts = new Map();
  for (const rec of records) {
    for (const tag of jobTags(rec.jobs?.[type])) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  return new Map([...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN')));
}

// URL 归一化，结果即 Article Key。保守策略（docs/design.md）：
// 小写协议/主机、去 hash、去默认端口、空路径归一为 /，
// 其余路径尾斜杠与全部 query（含 utm_*）原样保留。
export function normalizeUrl(input) {
  let u;
  try {
    u = new URL(String(input).trim());
  } catch {
    return null;
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
  u.hash = '';
  if ((u.protocol === 'http:' && u.port === '80') || (u.protocol === 'https:' && u.port === '443')) {
    u.port = '';
  }
  if (u.pathname === '') u.pathname = '/';
  let s = u.toString();
  if (s.endsWith('?')) s = s.slice(0, -1);
  return s;
}

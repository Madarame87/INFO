import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicDir = path.join(root, "public");
const index = await readFile(path.join(publicDir, "index.html"), "utf8");
const articleDir = path.join(publicDir, "articles");
const workerPath = path.join(root, "dist", "server", "index.js");
const socialImagePath = path.join(publicDir, "og.png");
const faviconPath = path.join(publicDir, "favicon.svg");
const style = await readFile(path.join(publicDir, "assets", "style.css"), "utf8");
const app = await readFile(path.join(publicDir, "assets", "app.js"), "utf8");
const robots = await readFile(path.join(publicDir, "robots.txt"), "utf8");
const sitemap = await readFile(path.join(publicDir, "sitemap.xml"), "utf8");

const voidElements = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);
const visibleText = (value) => value
  .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, " ")
  .replace(/<[^>]+>/g, " ")
  .replace(/&(?:nbsp|#160);/gi, " ")
  .replace(/&(?:[a-z]+|#\d+|#x[0-9a-f]+);/gi, "x")
  .replace(/\s+/g, " ")
  .trim();

function validateHtmlStructure(html, relative) {
  if (!/^<!doctype html>/i.test(html.trimStart())) throw new Error(`Missing HTML doctype in ${relative}`);
  if (!/<html\s+lang="zh-CN">/i.test(html)) throw new Error(`Missing zh-CN document language in ${relative}`);
  if (!/<meta\s+charset="utf-8">/i.test(html)) throw new Error(`Missing UTF-8 charset in ${relative}`);
  if (!/<meta\s+name="viewport"\s+content="width=device-width, initial-scale=1">/i.test(html)) throw new Error(`Missing responsive viewport in ${relative}`);
  if (!/<title>[^<]+<\/title>/i.test(html)) throw new Error(`Missing document title in ${relative}`);
  if (/\s(?:href|src)=""/i.test(html)) throw new Error(`Empty href or src in ${relative}`);
  const ids = [...html.matchAll(/\sid=(['"])(.*?)\1/gi)].map((match) => match[2]);
  const duplicateIds = ids.filter((id, index) => ids.indexOf(id) !== index);
  if (duplicateIds.length) throw new Error(`Duplicate IDs in ${relative}: ${[...new Set(duplicateIds)].join(", ")}`);
  for (const anchor of html.matchAll(/<a\b[^>]*target="_blank"[^>]*>/gi)) {
    if (!/\srel="[^"]*noopener[^"]*noreferrer[^"]*"/i.test(anchor[0])) {
      throw new Error(`Unsafe target=_blank link in ${relative}`);
    }
  }

  const stack = [];
  for (const match of html.matchAll(/<\/?([a-z][a-z0-9:-]*)(?:\s[^<>]*?)?\s*\/?>/gi)) {
    const raw = match[0];
    const tag = match[1].toLowerCase();
    if (raw.startsWith("</")) {
      const open = stack.pop();
      if (open !== tag) throw new Error(`Mismatched HTML tag in ${relative}: expected </${open || "none"}> but found </${tag}>`);
    } else if (!voidElements.has(tag) && !raw.endsWith("/>")) {
      stack.push(tag);
    }
  }
  if (stack.length) throw new Error(`Unclosed HTML tag in ${relative}: <${stack.at(-1)}>`);
}

async function validateLocalReferences(html, relative) {
  const sourcePath = path.join(publicDir, ...relative.split("/"));
  for (const match of html.matchAll(/\s(?:href|src)="([^"]+)"/gi)) {
    const reference = match[1].replace(/&amp;/g, "&");
    if (/^javascript:/i.test(reference)) throw new Error(`javascript: URL in ${relative}`);
    if (/^(?:https?:|mailto:|tel:|data:|#)/i.test(reference)) continue;
    const clean = decodeURIComponent(reference.split(/[?#]/, 1)[0]);
    const target = clean.startsWith("/")
      ? path.join(publicDir, clean.slice(1))
      : path.resolve(path.dirname(sourcePath), clean);
    const relativeTarget = path.relative(publicDir, target);
    if (relativeTarget.startsWith("..") || path.isAbsolute(relativeTarget)) throw new Error(`Reference escapes public root in ${relative}: ${reference}`);
    try {
      await access(target);
    } catch {
      throw new Error(`Broken local reference in ${relative}: ${reference}`);
    }
  }
}

const articleFiles = (await readdir(articleDir)).filter((name) => /^article-[a-z0-9]+\.html$/i.test(name)).sort();
const retiredArticle = "article-8a0810a163f4.html";
if (articleFiles.includes(retiredArticle) || index.includes(retiredArticle) || sitemap.includes(retiredArticle)) {
  throw new Error(`Retired interview article is still public: ${retiredArticle}`);
}
const htmlDocuments = new Map([["index.html", index]]);
for (const article of articleFiles) htmlDocuments.set(`articles/${article}`, await readFile(path.join(articleDir, article), "utf8"));
for (const [relative, html] of htmlDocuments) {
  validateHtmlStructure(html, relative);
  await validateLocalReferences(html, relative);
}

await access(workerPath);
await access(socialImagePath);
await access(faviconPath);
for (const phrase of ["阅读收件箱", "先判断价值，再进入全文", "快速定位", "恢复队列", "主题筛选", "待整理", "我的收藏", "可信译文", "阅读进度", "导出 Markdown", "复制资料卡", "Info Collector", "@130U", "@aswrise"]) {
  if (!index.includes(phrase)) throw new Error(`Missing index phrase: ${phrase}`);
}
if ((index.match(/href="https:\/\/github\.com\/130U"/g) || []).length !== 2 || (index.match(/href="https:\/\/github\.com\/aswrise"/g) || []).length !== 2) {
  throw new Error("Header and footer contributor credits are not unified");
}
if (index.includes("@THEO") || index.includes("@AQUA") || index.includes("Madarame87")) throw new Error("Legacy contributor credits remain");
for (const socialPhrase of [
  '<meta property="og:image" content="https://info-collector-reading-desk.jiligualapiqiu.chatgpt.site/og.png">',
  '<meta name="twitter:card" content="summary_large_image">',
]) {
  if (!index.includes(socialPhrase)) throw new Error(`Missing social-preview metadata: ${socialPhrase}`);
}
if (!index.includes("搜索标题、摘要、作者或主题") || !index.includes('id="article-search"') || !index.includes('class="command-bar"')) {
  throw new Error("Reading-terminal search control is missing");
}
if (index.includes("data-search=")) throw new Error("Redundant search data remains in the reading index");
if (!index.includes('id="result-count" aria-live="polite" aria-atomic="true"')) throw new Error("Filter result count is not an accessible live region");
if (index.includes('data-view="weekly"')) throw new Error("Weekly activity must not behave as a fourth article filter");
if (!index.includes('id="export-weekly"') || !index.includes('id="weekly-chart-line"') || !index.includes('id="weekly-chart-area"') || !index.includes('id="weekly-chart-marker"') || !index.includes('id="weekly-chart-value"') || !index.includes('id="weekly-periods"')) throw new Error("Premium weekly activity chart/export controls are missing");
if (index.includes('id="weekly-chart-points"') || index.includes('id="weekly-count"')) throw new Error("Legacy weekly chart points or detached total remain");
if (!index.includes('class="brand-signal"') || index.includes('class="brand-mark"')) throw new Error("Legacy boxed IC mark remains");
const styleVersion = index.match(/href="assets\/style\.css\?v=([0-9a-f]{12})"/)?.[1];
const appVersion = index.match(/src="assets\/app\.js\?v=([0-9a-f]{12})"/)?.[1];
if (!styleVersion || styleVersion !== appVersion) throw new Error("Reading-site assets are not cache-busted with one content version");
if (index.includes("阅读中文全文")) throw new Error("Index still includes the removed reading CTA");
if (index.includes("WINDOWS 11 · LOCAL-FIRST") || index.includes("INFO COLLECTOR / READING DESK")) {
  throw new Error("Index still includes the retired system labels");
}
if (!index.includes('<article class="article-card terminal-row') || index.includes('<a class="article-card')) {
  throw new Error("Article cards must be semantic containers, not full-card links");
}
if (!index.includes('class="article-title-link" href="articles/')) throw new Error("Article title links are missing");
if (!index.includes('data-article-id="')) throw new Error("Stable article IDs are missing");
if ((index.match(/data-action="favorite"/g) || []).length < 5 || (index.match(/data-action="review"/g) || []).length < 5 || (index.match(/data-action="copy-card"/g) || []).length < 5) {
  throw new Error("Second-pass card actions are incomplete");
}
if (!index.includes('class="card-source-link"') || !index.includes('<span>原文 ↗</span>')) throw new Error("Direct source links are missing");
if (index.includes(">DATE<")) throw new Error("Generic DATE label remains");
if (!index.includes("发布于 2026-07-02")) throw new Error("Geoffrey Litt URL date fallback is missing");
if (!index.includes("发布时间未知")) throw new Error("Unknown publication dates are not explicit");
if (!style.includes(".terminal-layout { display: grid;") || !style.includes("grid-template-columns: 260px minmax(0, 1fr)")) throw new Error("Reading-terminal workbench layout is missing");
for (const cssPhrase of ["--aquatic-soft", "system-ui", ".workspace-intro", ".search-control", ".terminal-sidebar", ".reader-feedback", ".article-title-link", ".card-action", ".view-filter", "prefers-reduced-motion", "prefers-reduced-transparency"]) {
  if (!style.includes(cssPhrase)) throw new Error(`Missing reading-site CSS contract: ${cssPhrase}`);
}
if (!/\[hidden\]\s*\{[^}]*display:\s*none\s*!important;?[^}]*\}/.test(style)) {
  throw new Error("Hidden article cards are not guaranteed to leave the layout");
}
if (style.includes(".brand-mark")) throw new Error("Removed boxed brand CSS remains");
const cssRule = (selector) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return style.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] || "";
};
for (const [selector, required] of [
  [".workspace-intro", ["display: grid", "border-bottom: 1px solid var(--line)"]],
  [".site-credits", ["border: 0", "background: transparent"]],
  [".terminal-workspace", ["min-width: 0", "border-left: 1px solid var(--line)"]],
]) {
  const rule = cssRule(selector);
  if (!rule || required.some((phrase) => !rule.includes(phrase))) throw new Error(`Missing frameless CSS contract for ${selector}`);
}
if (!app.includes("article-search") || !app.includes("matchesQuery") || !app.includes("syncUrlState") || !app.includes("info-collector:reader-state:v1") || !app.includes("buildInfoCardMarkdown") || !app.includes("weeklyActivitySeries") || !app.includes("smoothChartPath") || !app.includes("buildWeeklyReviewMarkdown")) {
  throw new Error("Second-pass reader script contract is incomplete");
}

const fakeWindow = {
  matchMedia() { return { matches: true }; },
  addEventListener() {},
  setTimeout,
  navigator: {},
  localStorage: null,
};
const fakeDocument = {
  body: { classList: { contains() { return false; } } },
  querySelectorAll() { return []; },
  getElementById() { return null; },
};
vm.runInNewContext(app, { document: fakeDocument, setTimeout, window: fakeWindow });
const readerApi = fakeWindow.InfoCollectorReader;
if (!readerApi) throw new Error("Reader state API did not initialize");
const pendingState = readerApi.stateFor({}, "stable-id");
const favoriteState = readerApi.toggleFavoriteState(pendingState, "2026-07-12T00:00:00Z");
if (!readerApi.matchesView(pendingState, "pending") || !readerApi.matchesView(favoriteState, "favorites") || readerApi.matchesView(favoriteState, "pending")) {
  throw new Error("Reader state view semantics are invalid");
}
if (Object.keys(readerApi.parseReaderState("{broken")).length !== 0) throw new Error("Damaged localStorage does not safely reset");
const infoCard = readerApi.buildInfoCardMarkdown({ title: "Test", tags: "智能体|产品", summary: "Summary" });
if (!infoCard.includes("原文：未知") || !infoCard.includes("收录时间：未知") || infoCard.includes("undefined") || infoCard.includes("null")) {
  throw new Error("Portable Markdown info card fallback is invalid");
}
const trustedArticleLinks = [...new Set([...index.matchAll(/class="article-title-link" href="articles\/(article-[^"]+\.html)"/g)].map((match) => match[1]))];
const recoveryArticleLinks = [...new Set([...index.matchAll(/data-article-href="articles\/(article-[^"]+\.html)"/g)].map((match) => match[1]))];
if (trustedArticleLinks.length < 5) throw new Error(`Expected at least 5 trusted articles, found ${trustedArticleLinks.length}`);
for (const status of ["source_blocked", "quality_rejected", "privacy_review_required", "translation_missing"]) {
  if (!index.includes(`data-content-status="${status}"`)) throw new Error(`Recovery queue is missing ${status}`);
}
if (!index.includes('data-content-status="source_blocked"') || !index.includes('data-content-status="quality_rejected"') || !index.includes('data-content-status="privacy_review_required"')) {
  throw new Error("Typed source, contamination and privacy-review states are not present in the recovery queue");
}
if ((index.match(/class="recovery-card"/g) || []).length !== recoveryArticleLinks.length) throw new Error("Recovery cards and recovery routes are inconsistent");
const indexedArticles = [...new Set([...trustedArticleLinks, ...recoveryArticleLinks])].sort();
if (indexedArticles.length !== articleFiles.length || indexedArticles.some((article, index) => article !== articleFiles[index])) {
  throw new Error("Index and article directory do not expose the same page set");
}
for (const article of trustedArticleLinks) {
  const html = await readFile(path.join(articleDir, article), "utf8");
  if (!html.includes(`../assets/style.css?v=${styleVersion}`) || !html.includes(`../assets/app.js?v=${appVersion}`)) {
    throw new Error(`Stale asset version in ${article}`);
  }
  const translationMarker = html.includes("VALIDATED CONTENT") ? "VALIDATED CONTENT" : "CHINESE TRANSLATION";
  const order = ["EXECUTIVE SUMMARY", translationMarker, "ORIGINAL SOURCE"].map((text) => html.indexOf(text));
  if (order.some((value) => value < 0) || !(order[0] < order[1] && order[1] < order[2])) {
    throw new Error(`Invalid content order in ${article}`);
  }
  if (!html.includes('data-article-id="')) throw new Error(`Missing stable article ID in ${article}`);
  if (!html.includes('data-return-library') || !html.includes('data-content-status=""')) throw new Error(`Trusted article does not use the current navigation/status shell: ${article}`);
  const body = html.match(/<div class="prose" id="article-content">([\s\S]*?)<\/div>/i)?.[1] || "";
  if (!visibleText(body)) throw new Error(`Trusted article has an empty translation: ${article}`);
}
for (const article of recoveryArticleLinks) {
  const html = await readFile(path.join(articleDir, article), "utf8");
  if (!html.includes("RECOVERY STATUS") || !html.includes('data-return-library') || !html.includes('class="quarantined-copy"') || !html.includes('class="source-warning reveal"')) {
    throw new Error(`Recovery article does not render an explicit recovery state: ${article}`);
  }
  if (!/data-content-status="(?:source_blocked|quality_rejected|privacy_review_required|translation_missing)"/.test(html)) {
    throw new Error(`Recovery article has no typed content status: ${article}`);
  }
}
const publicText = [style, app, robots, sitemap, ...htmlDocuments.values()].join("\n");
if (/sk-[A-Za-z0-9_-]{16,}/.test(publicText) || /[A-Za-z]:\\Users\\/i.test(publicText) || publicText.includes("chrome-extension://")) {
  throw new Error("Public snapshot contains a secret or local browser/path data");
}
if (publicText.includes('"hidden_profile"') || publicText.includes('&quot;hidden_profile&quot;') || publicText.includes('"user_id"') || publicText.includes('&quot;user_id&quot;')) {
  throw new Error("Public snapshot contains structured profile data that should be quarantined");
}
if (/Madarame87|(?:href|src)="\/(?:INFO|info)\//.test(publicText)) {
  throw new Error("Public snapshot contains a stale account reference or repository-coupled base path");
}
if (!robots.includes("Allow: /") || !robots.includes("Sitemap: https://info.theodoreoy.com/sitemap.xml")) throw new Error("robots.txt does not advertise the public sitemap");
const sitemapLocations = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
const expectedLocations = ["https://info.theodoreoy.com/", ...articleFiles.map((article) => `https://info.theodoreoy.com/articles/${article}`)];
if (sitemapLocations.length !== expectedLocations.length || expectedLocations.some((location) => !sitemapLocations.includes(location))) {
  throw new Error("sitemap.xml does not list every public page exactly once");
}

const worker = (await import(`${pathToFileURL(workerPath).href}?verify=${Date.now()}`)).default;
for (const route of ["/", "/index.html", "/favicon.svg", "/favicon.ico", "/robots.txt", "/sitemap.xml", ...articleFiles.map((article) => `/articles/${article}`)]) {
  const response = await worker.fetch(new Request(`https://example.test${route}`));
  if (response.status !== 200) throw new Error(`Production worker route failed (${response.status}): ${route}`);
  const expectedType = route.endsWith(".xml") ? "application/xml" : route.endsWith(".txt") ? "text/plain" : route.endsWith(".svg") || route.endsWith(".ico") ? "image/svg+xml" : "text/html";
  if (!response.headers.get("content-type")?.startsWith(expectedType)) throw new Error(`Wrong content type for ${route}`);
  for (const header of ["content-security-policy", "permissions-policy", "referrer-policy", "x-content-type-options", "x-frame-options"]) {
    if (!response.headers.has(header)) throw new Error(`Missing security header ${header} for ${route}`);
  }
  if (!await response.arrayBuffer().then((buffer) => buffer.byteLength)) throw new Error(`Empty worker response for ${route}`);
}
if ((await worker.fetch(new Request("https://example.test/missing"))).status !== 404) throw new Error("Production worker does not preserve 404s");
if ((await worker.fetch(new Request("https://example.test/", { method: "POST" }))).status !== 405) throw new Error("Production worker does not reject unsupported methods");
if ((await worker.fetch(new Request("https://example.test/%E0%A4%A"))).status !== 400) throw new Error("Production worker does not reject malformed encoded paths");

console.log(`Verified ${articleFiles.length} article pages, ${htmlDocuments.size} HTML documents and every production worker route.`);

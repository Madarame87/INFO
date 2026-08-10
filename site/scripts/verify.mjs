import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const index = await readFile(path.join(root, "public", "index.html"), "utf8");
const articleDir = path.join(root, "public", "articles");
const workerPath = path.join(root, "dist", "server", "index.js");
const socialImagePath = path.join(root, "public", "og.png");
const style = await readFile(path.join(root, "public", "assets", "style.css"), "utf8");
const app = await readFile(path.join(root, "public", "assets", "app.js"), "utf8");

await access(workerPath);
await access(socialImagePath);
for (const phrase of ["不止收藏", "真正读进去", "需要你恢复的来源", "从一个主题出发", "最近进入阅读桌", "待整理", "我的收藏", "可信译文", "每周阅读", "导出本周 Markdown", "复制资料卡", "Info Collector", "@130U", "@aswrise"]) {
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
if (index.includes("搜索标题、摘要或关键词") || index.includes('id="article-search"') || index.includes('class="search-box"') || index.includes("data-search=")) {
  throw new Error("Removed search UI or search data remains in the reading index");
}
if (index.includes("从关键词进入主题，从摘要判断价值")) throw new Error("Removed hero subtitle remains");
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
if (!index.includes('<article class="article-card editorial-card') || index.includes('<a class="article-card')) {
  throw new Error("Article cards must be semantic containers, not full-card links");
}
if (!index.includes('class="article-title-link" href="articles/')) throw new Error("Article title links are missing");
if (!index.includes('data-article-id="')) throw new Error("Stable article IDs are missing");
if ((index.match(/data-action="favorite"/g) || []).length < 5 || (index.match(/data-action="review"/g) || []).length < 5 || (index.match(/data-action="copy-card"/g) || []).length < 5) {
  throw new Error("Second-pass card actions are incomplete");
}
if (!index.includes('target="_blank" rel="noopener noreferrer">原文 ↗</a>')) throw new Error("Direct source links are missing");
if (index.includes(">DATE<")) throw new Error("Generic DATE label remains");
if (!index.includes("发布于 2026-07-02")) throw new Error("Geoffrey Litt URL date fallback is missing");
if (!index.includes("发布时间未知")) throw new Error("Unknown publication dates are not explicit");
const articleGridRule = style.match(/\.article-grid\s*\{([^}]*)\}/)?.[1] || "";
if (!style.includes("grid-template-columns: repeat(3, minmax(0, 1fr))")) throw new Error("Editorial collection grid is missing");
for (const cssPhrase of ["--aquatic-soft", "system-ui", ".hero-lede", ".article-title-link", ".card-action", ".view-filter", "prefers-reduced-motion", "prefers-reduced-transparency"]) {
  if (!style.includes(cssPhrase)) throw new Error(`Missing reading-site CSS contract: ${cssPhrase}`);
}
if (!/\[hidden\]\s*\{[^}]*display:\s*none\s*!important;?[^}]*\}/.test(style)) {
  throw new Error("Hidden article cards are not guaranteed to leave the layout");
}
if (style.includes(".search-box") || style.includes(".brand-mark")) throw new Error("Removed framed UI CSS remains");
const cssRule = (selector) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return style.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] || "";
};
for (const [selector, required] of [
  [".library-hero", ["border: 0", "background: transparent"]],
  [".site-credits", ["border: 0", "background: transparent"]],
  [".tag-filter", ["border: 0", "background: transparent"]],
]) {
  const rule = cssRule(selector);
  if (!rule || required.some((phrase) => !rule.includes(phrase))) throw new Error(`Missing frameless CSS contract for ${selector}`);
}
if (app.includes("article-search") || !app.includes("info-collector:reader-state:v1") || !app.includes("buildInfoCardMarkdown") || !app.includes("weeklyActivitySeries") || !app.includes("smoothChartPath") || !app.includes("buildWeeklyReviewMarkdown")) {
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
const articleLinks = [...index.matchAll(/\shref="articles\/(article-[^"]+\.html)"/g)].map((match) => match[1]);
const uniqueLinks = [...new Set(articleLinks)];
if (uniqueLinks.length < 5) throw new Error(`Expected at least 5 articles, found ${uniqueLinks.length}`);
if (!index.includes('data-content-status="source_blocked"') || !index.includes('data-content-status="quality_rejected"') || !index.includes('data-content-status="privacy_review_required"')) {
  throw new Error("Typed source, contamination and privacy-review states are not present in the recovery queue");
}
if ((index.match(/class="recovery-card"/g) || []).length !== 3) throw new Error("Expected exactly three quarantined recovery records");
for (const article of uniqueLinks) {
  const html = await readFile(path.join(articleDir, article), "utf8");
  const order = ["EXECUTIVE SUMMARY", "CHINESE TRANSLATION", "ORIGINAL SOURCE"].map((text) => html.indexOf(text));
  if (order.some((value) => value < 0) || !(order[0] < order[1] && order[1] < order[2])) {
    throw new Error(`Invalid content order in ${article}`);
  }
  if (!html.includes('data-article-id="')) throw new Error(`Missing stable article ID in ${article}`);
}
const publicText = [index, style, app, ...await Promise.all(uniqueLinks.map((article) => readFile(path.join(articleDir, article), "utf8")))].join("\n");
if (/sk-[A-Za-z0-9_-]{16,}/.test(publicText) || /[A-Za-z]:\\Users\\/i.test(publicText) || publicText.includes("chrome-extension://")) {
  throw new Error("Public snapshot contains a secret or local browser/path data");
}
if (publicText.includes('"hidden_profile"') || publicText.includes('&quot;hidden_profile&quot;') || publicText.includes('"user_id"') || publicText.includes('&quot;user_id&quot;')) {
  throw new Error("Public snapshot contains structured profile data that should be quarantined");
}
if (/Madarame87|(?:href|src)="\/(?:INFO|info)\//.test(publicText)) {
  throw new Error("Public snapshot contains a stale account reference or repository-coupled base path");
}
console.log(`Verified ${uniqueLinks.length} article pages and production worker output.`);

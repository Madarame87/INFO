import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const index = await readFile(path.join(root, "public", "index.html"), "utf8");
const articleDir = path.join(root, "public", "articles");
const workerPath = path.join(root, "dist", "server", "index.js");
const style = await readFile(path.join(root, "public", "assets", "style.css"), "utf8");
const app = await readFile(path.join(root, "public", "assets", "app.js"), "utf8");

await access(workerPath);
for (const phrase of ["文章情报库", "关键词", "Info Collector", "@Madarame87", "@aswrise", "DATE"]) {
  if (!index.includes(phrase)) throw new Error(`Missing index phrase: ${phrase}`);
}
if ((index.match(/href="https:\/\/github\.com\/Madarame87"/g) || []).length !== 2 || (index.match(/href="https:\/\/github\.com\/aswrise"/g) || []).length !== 2) {
  throw new Error("Header and footer contributor credits are not unified");
}
if (index.includes("@THEO") || index.includes("@AQUA")) throw new Error("Legacy display-name credits remain");
if (index.includes("搜索标题、摘要或关键词") || index.includes('id="article-search"') || index.includes('class="search-box"') || index.includes("data-search=")) {
  throw new Error("Removed search UI or search data remains in the reading index");
}
if (index.includes("从关键词进入主题，从摘要判断价值")) throw new Error("Removed hero subtitle remains");
if (!index.includes('id="result-count" aria-live="polite" aria-atomic="true"')) throw new Error("Filter result count is not an accessible live region");
if (!index.includes('class="brand-signal"') || index.includes('class="brand-mark"')) throw new Error("Legacy boxed IC mark remains");
if (index.includes("阅读中文全文")) throw new Error("Index still includes the removed reading CTA");
if (index.includes("WINDOWS 11 · LOCAL-FIRST") || index.includes("INFO COLLECTOR / READING DESK")) {
  throw new Error("Index still includes the retired system labels");
}
if (!index.includes('class="article-card reveal" href="articles/')) {
  throw new Error("Article cards are not full-card links");
}
if (index.includes('role="article"')) throw new Error("Article links override their native link semantics");
const articleGridRule = style.match(/\.article-grid\s*\{([^}]*)\}/)?.[1] || "";
if (!articleGridRule.includes("grid-template-columns: 1fr") || articleGridRule.includes("repeat(2")) {
  throw new Error("Reading index does not use a one-column article grid");
}
for (const cssPhrase of ["--aquatic-soft", "text-overflow: ellipsis", ".card-meta time"]) {
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
if (app.includes("article-search") || !app.includes("card.hidden = !show") || !app.includes("applyFilters();")) {
  throw new Error("Keyword-only filtering script contract is incomplete");
}
const articleLinks = [...index.matchAll(/href="articles\/(article-[^"]+\.html)"/g)].map((match) => match[1]);
const uniqueLinks = [...new Set(articleLinks)];
if (uniqueLinks.length < 5) throw new Error(`Expected at least 5 articles, found ${uniqueLinks.length}`);
if (articleLinks.length !== uniqueLinks.length) throw new Error("Index contains duplicate article links");
for (const article of uniqueLinks) {
  const html = await readFile(path.join(articleDir, article), "utf8");
  const order = ["EXECUTIVE SUMMARY", "CHINESE TRANSLATION", "ORIGINAL SOURCE"].map((text) => html.indexOf(text));
  if (order.some((value) => value < 0) || !(order[0] < order[1] && order[1] < order[2])) {
    throw new Error(`Invalid content order in ${article}`);
  }
}
console.log(`Verified ${uniqueLinks.length} article pages and production worker output.`);

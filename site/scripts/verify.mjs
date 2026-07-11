import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const index = await readFile(path.join(root, "public", "index.html"), "utf8");
const articleDir = path.join(root, "public", "articles");
const workerPath = path.join(root, "dist", "server", "index.js");
const style = await readFile(path.join(root, "public", "assets", "style.css"), "utf8");

await access(workerPath);
for (const phrase of ["文章情报库", "关键词", "Info Collector", "@Madarame87", "@aswrise", "@THEO", "@AQUA", "DATE"]) {
  if (!index.includes(phrase)) throw new Error(`Missing index phrase: ${phrase}`);
}
if (index.includes("阅读中文全文")) throw new Error("Index still includes the removed reading CTA");
if (index.includes("WINDOWS 11 · LOCAL-FIRST") || index.includes("INFO COLLECTOR / READING DESK")) {
  throw new Error("Index still includes the retired system labels");
}
if (!index.includes('class="article-card reveal" role="article" href="articles/')) {
  throw new Error("Article cards are not full-card links");
}
const articleGridRule = style.match(/\.article-grid\s*\{([^}]*)\}/)?.[1] || "";
if (!articleGridRule.includes("grid-template-columns: 1fr") || articleGridRule.includes("repeat(2")) {
  throw new Error("Reading index does not use a one-column article grid");
}
for (const cssPhrase of ["--aquatic-soft", "text-overflow: ellipsis", ".card-meta time"]) {
  if (!style.includes(cssPhrase)) throw new Error(`Missing reading-site CSS contract: ${cssPhrase}`);
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

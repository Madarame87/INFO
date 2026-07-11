import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const index = await readFile(path.join(root, "public", "index.html"), "utf8");
const articleDir = path.join(root, "public", "articles");
const workerPath = path.join(root, "dist", "server", "index.js");

await access(workerPath);
for (const phrase of ["文章情报库", "关键词", "Info Collector"]) {
  if (!index.includes(phrase)) throw new Error(`Missing index phrase: ${phrase}`);
}
const articleLinks = [...index.matchAll(/href="articles\/(article-[^"]+\.html)"/g)].map((match) => match[1]);
const uniqueLinks = [...new Set(articleLinks)];
if (uniqueLinks.length < 5) throw new Error(`Expected at least 5 articles, found ${uniqueLinks.length}`);
for (const article of uniqueLinks) {
  const html = await readFile(path.join(articleDir, article), "utf8");
  const order = ["EXECUTIVE SUMMARY", "CHINESE TRANSLATION", "ORIGINAL SOURCE"].map((text) => html.indexOf(text));
  if (order.some((value) => value < 0) || !(order[0] < order[1] && order[1] < order[2])) {
    throw new Error(`Invalid content order in ${article}`);
  }
}
console.log(`Verified ${uniqueLinks.length} article pages and production worker output.`);

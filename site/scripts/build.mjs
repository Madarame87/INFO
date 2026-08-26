import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicDir = path.join(root, "public");
const distDir = path.join(root, "dist");

async function walk(directory, prefix = "") {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relative = path.posix.join(prefix, entry.name);
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await walk(absolute, relative));
    else files.push({ relative, absolute });
  }
  return files;
}

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp"
};

const files = await walk(publicDir);
if (!files.some((file) => file.relative === "index.html")) {
  throw new Error("site/public/index.html is required");
}

const assets = {};
for (const file of files) {
  const route = `/${file.relative}`;
  const extension = path.extname(file.relative).toLowerCase();
  const buffer = await readFile(file.absolute);
  assets[route] = {
    body: buffer.toString("base64"),
    type: contentTypes[extension] || "application/octet-stream"
  };
}
if (assets["/favicon.svg"]) {
  assets["/favicon.ico"] = { ...assets["/favicon.svg"], type: "image/svg+xml" };
}

const worker = `const assets = ${JSON.stringify(assets)};

function decodeBase64(value) {
  const decoded = atob(value);
  const bytes = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) bytes[index] = decoded.charCodeAt(index);
  return bytes;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    let pathname;
    try {
      pathname = decodeURIComponent(url.pathname);
    } catch {
      return new Response("Bad request", {
        status: 400,
        headers: { "content-type": "text/plain; charset=utf-8" }
      });
    }
    if (pathname === "/" || pathname === "") pathname = "/index.html";
    if (pathname.endsWith("/")) pathname += "index.html";
    const asset = assets[pathname];
    if (!asset) {
      return new Response("Not found", {
        status: 404,
        headers: { "content-type": "text/plain; charset=utf-8" }
      });
    }
    const headers = new Headers({
      "content-type": asset.type,
      "cache-control": pathname.endsWith(".html") ? "public, max-age=60" : "public, max-age=86400",
      "content-security-policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
      "permissions-policy": "camera=(), microphone=(), geolocation=()",
      "referrer-policy": "strict-origin-when-cross-origin",
      "x-content-type-options": "nosniff",
      "x-frame-options": "SAMEORIGIN"
    });
    if (request.method === "HEAD") return new Response(null, { status: 200, headers });
    if (request.method !== "GET") return new Response("Method not allowed", { status: 405, headers });
    return new Response(decodeBase64(asset.body), { status: 200, headers });
  }
};
`;

await rm(distDir, { recursive: true, force: true });
await mkdir(path.join(distDir, "server"), { recursive: true });
await writeFile(path.join(distDir, "server", "index.js"), worker, "utf8");
console.log(`Built ${files.length} reading-site assets.`);

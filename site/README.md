# Info Collector Reading Desk

This directory is the deployable, public-facing reading surface for Info Collector.

- `public/` is generated from the user's translated Markdown library.
- `scripts/build.mjs` packages the static pages as a Cloudflare Workers-compatible site.
- The public snapshot contains no API keys, local filesystem paths, or browser screenshots.
- The interview demo is hosted independently with Sites; GitHub Pages deployment stays manual because project Pages inherit the account-level custom domain.
- All browser assets and article links are relative, so a future `INFO` → `info` repository rename does not require a base-path rewrite.

Run `npm.cmd run build` and then `npm.cmd test` from this directory to validate the deployable snapshot.

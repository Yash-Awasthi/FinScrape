# 0003 Static SPA

## Status

Accepted, 2026-11-26.

## Context

The dashboard is read-mostly: it fetches published analysis and renders it. Server-side rendering, a Node runtime or an edge framework would add a build and hosting surface that this shape of product does not obviously need.

## Decision

Ship the web app as a static single-page application on Cloudflare Pages, project `winfin`. [DEPLOY.md](../DEPLOY.md) records the architecture: Web is Cloudflare Pages, static, no sleep, with the landing page at `/` and the app at `/app/`. The API is a separate Render service reached over HTTPS through `VITE_API_BASE`.

The app under `web/` is a Vite and TypeScript SPA. Its [package.json](../../web/package.json) runs `dev`, `build` and `preview` through `vp`. The only runtime dependency is `globe.gl`, loaded as a lazy heavy chunk; [STACK.md](../STACK.md) records "No frontend framework" and that `globe.gl` is the only heavy runtime dependency. The rest is plain TypeScript and ships as static assets.

Deployment is automated. [deploy-web.yml](../../.github/workflows/deploy-web.yml) builds and publishes on a push to master that touches `web/`. The manual equivalent is `cd web && npm run build && npx wrangler pages deploy dist --project-name=winfin`.

## Consequences

Hosting is static file serving with no server process to keep warm, and a page load costs a CDN request plus API calls. There is no SSR, so crawlers and link previews see the SPA shell rather than rendered content, and the first paint depends on JavaScript.

The dashboard updates on refresh, not by live push. [DEPLOY.md](../DEPLOY.md) lists cross-process WebSocket delivery as a known limit that needs Redis and is deferred, which matches the single-replica decision in [0001](0001-no-redis-yet.md).

Revisit this decision when an SEO or SSR requirement appears, or when live push becomes a product requirement rather than a nice-to-have. Either case breaks the static-only assumption.

## Evidence

- [DEPLOY.md](../DEPLOY.md): architecture table, Pages project `winfin`, landing `/`, app `/app/`.
- [package.json](../../web/package.json): `dev`, `build` and `preview` via `vp`, plus the `globe.gl` dependency.
- [STACK.md](../STACK.md): no frontend framework, `globe.gl` the only heavy dependency.
- [deploy-web.yml](../../.github/workflows/deploy-web.yml): build and publish on push to master.

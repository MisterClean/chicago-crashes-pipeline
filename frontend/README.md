# Chicago crashes dashboard

Next.js, React, TypeScript and MapLibre frontend for the Rust/DuckDB API. Use Node 22 (or a newer supported Node release) and run these commands from this directory:

```sh
npm ci
npm run dev
```

The dashboard runs on port 3001. `BACKEND_URL` defaults to `http://127.0.0.1:8003`. Browser requests use `/api`; Next.js rewrites them to the Rust backend. `/admin` proxies the embedded admin UI. Set `BACKEND_URL` at build time and runtime, and rebuild after changing it.

Basemap selection uses an explicit `NEXT_PUBLIC_BASEMAP_URL` first, then `NEXT_PUBLIC_PROTOMAPS_KEY`, then keyless CARTO Positron. Leave the URL empty when selecting Protomaps by its browser-visible key. Both settings are embedded at build time. MapLibre requires WebGL 2 and access to the style's tiles/glyphs. Never place a server secret in a `NEXT_PUBLIC_*` variable.

```sh
npm run typecheck
npm test
npm run build
npm run start
```

The production Dockerfile uses Next.js standalone output, copies static assets and runs as the unprivileged Node user. Docker builds accept `BACKEND_URL`, `NEXT_PUBLIC_BASEMAP_URL` and `NEXT_PUBLIC_PROTOMAPS_KEY` arguments. The basemap arguments default to empty so an optional key is not shadowed by a preset URL. Railway's service configuration uses the same build/runtime backend address requirement.

See the root [README](../README.md), [operations guide](../docs/rust-migration.md), and [API contracts](../docs/research/rust-api-compatibility-2026-10-21.md).

# Security policy

Report vulnerabilities through the repository's [private security advisory form](https://github.com/MisterClean/chicago-crashes-pipeline/security/advisories/new). Do not publish live credentials or exploit details in a public issue. The Rust/DuckDB application is the maintained implementation; older implementations remain available only through Git history.

## Deployment boundaries

- Public dashboard reads are separate from administrative mutations and exports. Configure a strong `API_KEY` of at least 32 bytes in production; protected operations require `X-API-Key`.
- Store secrets in the host's environment manager. Never commit `.env`, connection URLs, object-store credentials or signed download links. Never expose secrets through `NEXT_PUBLIC_*` variables.
- Run one backend owner/replica on a persistent private volume. Do not expose database or control files through a static file server. The production container drops to an unprivileged user after volume initialization.
- Production requires a complete baseline and private S3-compatible storage. Keep buckets private and signed-link lifetimes finite. Terminate public HTTPS at the hosting platform or reverse proxy.
- The migration reader requires verified PostgreSQL TLS and a read-only repeatable-read transaction. A trusted CA override does not disable hostname verification.
- Uploaded archives, conversion processes, request bodies, queues, SQL execution and exports have finite limits. Keep outer container/volume limits as the final boundary; native allocations and writes between watchdog samples can exceed an internal budget briefly.
- The browser prompts for an administrative/export key when needed. Server credentials must not be embedded in frontend JavaScript. Public crash data and uploaded layer properties still deserve review before publication.

## Dependency checks

```sh
cargo audit --deny warnings
npm --prefix frontend audit --omit=dev --audit-level=moderate
npm --prefix frontend audit
```

Install `cargo-audit` to run the first command. CI checks Rust advisories, production frontend dependencies and the runtime image. Review full frontend audit output as well: the October 2026 validation found seven build-only findings in the unpatched `braces` dependency chain, while the production dependency audit was clean. These findings are not suppressed. Treat untrusted build inputs and dependency updates accordingly.

The native installer verifies the official engine archive's SHA-256. DuckDB checks the official spatial extension signature and ABI on load; automatic extension installation is disabled by the application.

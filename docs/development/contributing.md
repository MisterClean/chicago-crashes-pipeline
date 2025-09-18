---
title: Contributing
sidebar_position: 3
description: Workflow and guidelines for contributing enhancements or fixes.
---

We welcome contributions that improve data quality, stability, and documentation. Follow these guidelines to streamline reviews.

## Branching & Commits

1. Create a descriptive branch: `git checkout -b feature/<topic>` or `fix/<bug>`.
2. Keep commits focused; prefer multiple small commits over monolithic changes.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) where practical (`feat:`, `fix:`, `docs:`, `chore:`).

## Pull Request Checklist

- [ ] Tests added or updated (`pytest` passes locally)
- [ ] Linters clean (`make lint`)
- [ ] Documentation updated (Docusaurus `npm run build` succeeds)
- [ ] Screenshots or recordings attached for UI changes (admin portal, docs site)
- [ ] Links included to relevant issue numbers

## Code Review Expectations

- Prioritise correctness, security, and maintainability over premature optimisation.
- Respond to reviewer comments promptly; mark threads as resolved only when the issue is addressed.
- Be explicit about assumptions or follow-up work. If a fix is temporary, add TODOs referencing an issue.

## Releasing Changes

1. After merging to `main`, bump any relevant version identifiers (API `version`, Docker tags, etc.).
2. Publish release notes summarising user-facing changes and migrations.
3. Deploy to staging first, verify health checks, then roll out to production.

## Documentation Contributions

- Source lives in `docs/` and is built with Docusaurus 3.
- Preview changes locally:
  ```bash
  npm install
  npm run start
  ```
- Run `npm run build` before submitting to ensure the static site compiles without errors.

## Community Standards

- Follow the project's Code of Conduct (TBD – align with Contributor Covenant if adopted).
- Respect rate limits when testing against the live SODA API; prefer fixtures and recorded responses.
- Keep sensitive data (API tokens, personal information) out of commits.

Thank you for helping improve the Chicago Crash Data Pipeline!

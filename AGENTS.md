# AGENTS.md

Guidance for AI agents working in this repository.

## Agent skills

### Issue tracker

Issues and specs live in this repo's **GitHub Issues** (canonical CLI: `gh`; in
environments without `gh`, use the equivalent GitHub API/MCP operations). See
`docs/agents/issue-tracker.md`.

### Domain docs

**Multi-context** layout: a root `CONTEXT-MAP.md` points at one `CONTEXT.md` per
context (`backend`, `frontend`, `client`), with ADRs under `docs/adr/` and
`<context>/docs/adr/`. See `docs/agents/domain.md`.

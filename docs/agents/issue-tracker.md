# Issue tracker: GitHub

Issues and specs for this repo live as **GitHub issues** on
`Floppydisk97/PROJECT-EXILIUM`.

Two execution surfaces are supported. Pick whichever your session actually has:

- **MCP GitHub tools** (`mcp__github__*`) — the surface available in Claude Code
  web/remote sessions, which have **no `gh` CLI**. This is the primary surface
  documented below.
- **`gh` CLI** — available in local terminals. The `gh` equivalents are listed
  after each operation for that case.

## Conventions (MCP tools)

- **Create an issue**: `mcp__github__issue_write` with `method:"create"`,
  `owner`, `repo`, `title`, `body`, optional `labels`, `assignees`.
  _(gh: `gh issue create --title "..." --body "..."`)_
- **Read an issue**: `mcp__github__issue_read` with `method:"get"` (and
  `"get_comments"`, `"get_labels"` for the rest).
  _(gh: `gh issue view <number> --comments`)_
- **List issues**: `mcp__github__list_issues` with `state`, `labels`, `orderBy`
  filters, or `mcp__github__search_issues` for queries.
  _(gh: `gh issue list --state open --json number,title,body,labels,comments`)_
- **Comment on an issue**: `mcp__github__add_issue_comment`.
  _(gh: `gh issue comment <number> --body "..."`)_
- **Apply / remove labels**: `mcp__github__issue_write` with `method:"update"`
  and the full desired `labels` array.
  _(gh: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`)_
- **Assign**: `mcp__github__issue_write` `method:"update"` with `assignees`.
  _(gh: `gh issue edit <number> --add-assignee @me`)_
- **Close**: `mcp__github__issue_write` `method:"update"`, `state:"closed"`,
  `state_reason:"completed"`, optionally a closing comment first.
  _(gh: `gh issue close <number> --comment "..."`)_

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs
as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using
`mcp__github__pull_request_read` / `search_pull_requests` / `add_issue_comment`
(or the `gh pr ...` equivalents). GitHub shares one number space across issues
and PRs, so a bare `#42` may be either.

## When a skill says "publish to the issue tracker"

Create a GitHub issue (`mcp__github__issue_write`, `method:"create"`).

## When a skill says "fetch the relevant ticket"

`mcp__github__issue_read`, `method:"get"` (add `"get_comments"` as needed).

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as
tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the
  Notes / Decisions-so-far / Fog body. Create with
  `mcp__github__issue_write` `method:"create"`, `labels:["wayfinder:map"]`.
- **Child ticket**: create with `mcp__github__issue_write` `method:"create"`
  and `parent_issue_number:<map-number>` — this attaches it as a **native GitHub
  sub-issue** of the map in one call. Add `labels:["wayfinder:<type>"]`
  (`research`/`prototype`/`grilling`/`task`). To re-parent or re-order later, use
  `mcp__github__sub_issue_write` (`add` with `replace_parent:true`,
  `reprioritize`). Once claimed, set the ticket's `assignees` to the driving dev
  (`Floppydisk97`).
- **Blocking**: the MCP GitHub tools **do not expose** GitHub's native issue
  *dependencies* endpoint, so blocking uses the **body convention** fallback: put
  a `Blocked by: #<n>, #<n>` line at the top of the child body. (In a local `gh`
  session you may instead use native dependencies via
  `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`;
  keep the two in sync if you mix surfaces.) A ticket is **unblocked** when every
  issue named in its `Blocked by` line is closed.
- **Frontier query**: list the map's open children with
  `mcp__github__issue_read` `method:"get_sub_issues"` on the map (or
  `mcp__github__list_issues` filtered by `labels` + `state:"OPEN"`), then drop any
  child that still has an open blocker in its `Blocked by` line or already has an
  assignee; first in map order wins.
- **Claim**: `mcp__github__issue_write` `method:"update"` with
  `assignees:["Floppydisk97"]` — the session's first write, before any work.
- **Resolve**: `mcp__github__add_issue_comment` with the answer, then
  `mcp__github__issue_write` `method:"update"`, `state:"closed"`,
  `state_reason:"completed"`, then append a context pointer (gist + link) to the
  map's Decisions-so-far.

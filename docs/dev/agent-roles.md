# Agent roles and model routing

How the agents building this repo are organised. The lead follows this table, and uses judgement only
where the table doesn't decide. Agent definitions live in `.claude/agents/`, each with its model pinned.

## Roles

| Role | Model, effort | Runs as | Does | Never |
|---|---|---|---|---|
| Lead | Fable, high | the coordinating session | picks the next work, writes briefs, routes each task to a role, reviews risky diffs, merges gated work, reports to the owner | writes or edits product code |
| Builder | Opus, medium | a chip session in its own worktree (long work) or `builder` subagent (one bounded change) | builds one feature slice end to end (model, migration, service, route, screen, tests), runs its module's tests | merges to main, touches another chip's files |
| Reviewer | Opus, medium | `reviewer` subagent | reviews every change before merge for correctness and conventions | edits code |
| Risk reviewer | Fable, high | `risk-reviewer` subagent | reviews risky changes (below), merged seams between chips, one security pass per milestone, final acceptance | edits code |
| Mechanical | Haiku, low | `mechanical` subagent | seeds, fixtures, status tables, docs sync, lint and format fixes, regenerating generated files | design decisions, domain logic |
| Drift | Sonnet, medium | `drift` subagent (run by the EGM commit hook) | writes `docs/egm/drift/<module>.md` from code and docs, never seen before | edits code |

## Routing rules

1. A change touching any of these gets the risk reviewer as well as the reviewer: `billing/`, `core/db/`,
   `core/auth/`, `core/idempotency`, `platform/` permissions or step-up, any migration, any public
   (portal or anonymous) route, money or PII handling, or files from more than one chip.
2. Work that is only seeds, fixtures, docs, status tables, lint or regenerated files goes to mechanical.
3. Everything else that changes code goes to a builder, then the reviewer.
4. A builder that fails the same gate twice goes back to the lead, which re-scopes the brief rather than retrying.

## Briefs (lead to builder)

Every brief states: the goal and its feature ids, the files and module it owns, what is out of scope, the
contract operations and migrations involved, what done looks like (tests, screenshot), and what was already
ruled out. Builders return a short report and write longer output to their chip's notes file, not to the lead.

## Capacity

The owner's Mac has 16 GB: at most one full gate (pytest + Playwright) at a time, and chips stop their
servers when their gate finishes (`docs/dev/module-playbook.md`, Lanes).

## Never

- Set `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`: it overrides every pinned model above.
- Leave a model as `inherit` in an agent file: the lead's model can change mid-run.

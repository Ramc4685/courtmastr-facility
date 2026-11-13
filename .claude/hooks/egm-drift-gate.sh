#!/usr/bin/env bash
# PreToolUse(Bash) hook: before an agent runs `git commit`, every module whose code the branch changed
# must have a fresh EGM drift report (docs/egm/drift/<module>.md newer than the newest change in that module).
# Off switch: EGM_DRIFT_GATE=off. Reports list divergences only; fixing is a separate task.
set -euo pipefail

[ "${EGM_DRIFT_GATE:-on}" = "off" ] && exit 0
input=$(cat)
# Only commits; also matches the RTK-rewritten `rtk git commit`.
jq -r '.tool_input.command // ""' <<<"$input" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+commit' || exit 0

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root"
base=$(git merge-base HEAD main 2>/dev/null || git rev-parse HEAD)

# Files changed on this branch, staged, unstaged or new; module code only, README excluded.
changed=$( { git diff --name-only "$base"; git diff --name-only --cached; git ls-files --others --exclude-standard; } \
  | grep -E '^backend/app/modules/[^/]+/' | grep -v '/README\.md$' | sort -u || true)
[ -z "$changed" ] && exit 0

stale=()
for mod in $(sed -E 's#^backend/app/modules/([^/]+)/.*#\1#' <<<"$changed" | sort -u); do
  [ -f "backend/app/modules/$mod/README.md" ] || continue
  report="docs/egm/drift/$mod.md"
  newest=0
  while IFS= read -r f; do
    [ -f "$f" ] && t=$(stat -f %m "$f") && [ "$t" -gt "$newest" ] && newest=$t
  done < <(grep "^backend/app/modules/$mod/" <<<"$changed")
  if [ ! -f "$report" ] || [ "$(stat -f %m "$report")" -lt "$newest" ]; then stale+=("$mod"); fi
done
[ ${#stale[@]} -eq 0 ] && exit 0

mods="${stale[*]}"
reason="EGM drift check needed before this commit. Module code changed without a fresh drift report: ${mods}. \
For each, spawn ONE fresh general-purpose subagent (a goldfish: give it no conversation context) that follows \
~/.claude/plugins/cache/egm/egm/*/skills/egm-drift-report/SKILL.md on backend/app/modules/<module>/README.md, \
reports ONLY divergences with README line + code file:line, tags each bullet [stale-not-built]|[missing]|[contract]|[undocumented]|[wording], \
and overwrites docs/egm/drift/<module>.md. Do not fix the README or code. Then add the new items to docs/egm/DRIFT_BACKLOG.md \
and stage docs/egm with the commit, then retry it and mention the counts in your final message. \
Skip with EGM_DRIFT_GATE=off only if the user says so."
jq -n --arg r "$reason" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'

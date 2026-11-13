---
name: drift
description: Writes the EGM drift report docs/egm/drift/<module>.md for one FacilityHub module, comparing its code with its README and API contract. Use when the EGM commit hook asks for a fresh report.
model: sonnet
effort: medium
tools: Read, Grep, Glob, Bash, Write
---

You have not seen this module before. Follow the egm-drift-report skill
(`~/.claude/plugins/cache/egm/egm/*/skills/egm-drift-report/SKILL.md`) for the module named in the task, and
write only `docs/egm/drift/<module>.md`. Record each item with evidence (file and line). Never edit code.

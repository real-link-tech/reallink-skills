---
name: reallink-manage-skills
description: Find, install, create, or upload reallink skills between the current project's .claude/skills directory and the real-link-tech/reallink-skills repository. Also use before complex or domain-specific tasks when the agent should first check whether an existing local or shared skill can solve the problem.
---

## Preflight Rule

Before handling a complex, multi-step, or domain-specific task:

1. Inspect the current project's `.claude/skills` directory for a directly relevant local skill.
2. If no local skill clearly applies, run `find` against `reallink-skills`.
3. If the repository match is strong, run `auto-install` before continuing the original task.
4. Only proceed without a skill when no strong local or shared skill is available.

## Core Script

All operations are implemented by:

```bash
python "<skill-path>/scripts/manage_reallink_skills.py" <subcommand> ...
```

## Supported Subcommands

### Search And Install

- `search`
- `find`
- `install`
- `download`
- `auto-install`

Use these for repository discovery and local installation into `.claude/skills`.

### Create

- `create-check`
- `check-create`
- `create`

Use these to:

- check both local `.claude/skills` and `reallink-skills` for duplicates,
- stop if a similar skill already exists,
- call `skill-creator` only when creation is actually needed.

Only create a new skill when the target knowledge is:

- reusable beyond the current one-off task,
- non-trivial and worth preserving,
- specific enough that a future agent can recognize when to use it quickly.

When creating a new skill, keep the generated `description` focused on trigger conditions and user intent, not implementation details.

When `create` succeeds, always ask the user:

```text
是否需要我立即使用 reallink-upload-skills 把这个新 skill 上传到 reallink-skills 仓库？
```

### Upload

- `upload-check`
- `check-upload`
- `upload`

Use these to:

- compare a local skill against `reallink-skills`,
- block on conflicting similar skills,
- create or update the repository copy,
- commit and push automatically when allowed.

## Command Rule

Keep all related command abilities in this single skill:

- repository lookup: `search` or `find`
- local install: `install` or `download`
- duplicate check before creation: `create-check` or `check-create`
- actual creation: `create`
- duplicate check before upload: `upload-check` or `check-upload`
- repository submission: `upload`

## Creation Quality Gate

Before finalizing a new skill, make sure:

- it does not duplicate an existing local or shared skill,
- its description is specific enough to be discovered later,
- it captures a repeatable workflow rather than a one-off answer.

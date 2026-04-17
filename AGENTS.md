# AGENTS.md

Instructions for AI coding agents working in this repository.

Merge these project-specific rules with task-specific context as needed.
Tradeoff: these guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so.
- Push back when warranted.
- If something is unclear, stop. Name what's confusing.

For non-trivial tasks, first provide a brief plan.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- Keep code simple and understandable for a non-programmer owner of the project.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself:
- Would a senior engineer say this is overcomplicated?

If yes, simplify.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting without a clear reason.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports, variables, and functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test:
- Every changed line should trace directly to the user's request.

Repository-specific rules:
- Do not break existing working flows without necessity.
- Reusable integrations should go into `shared/webhooks` or `shared/utils`.
- For each new webhook, create a separate module.
- Do not rename files or folders without a clear reason.
- Preserve project structure unless a change is clearly required.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure behavior stays correct before and after"

For multi-step tasks, state a brief plan:
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently.
Weak criteria ("make it work") require constant clarification.

After changes:
- Check imports.
- Check entrypoints.
- Check that existing working flows still work unless the task explicitly changes them.

## 5. Secrets and Configuration

- Never store secrets in code.
- Never hardcode API keys, tokens, credentials, or private URLs.
- All settings must go through `.env.local`, environment variables, or LiveKit Cloud secrets.
- Do not change environment variable names unless explicitly required by the task.
- If a new config value is needed, add it in the least disruptive way.

## 6. LiveKit Rules

This repository is a LiveKit agent project. Treat it as a realtime system.

- LiveKit is a fast-evolving project. Always refer to the latest documentation.
- Run `lk docs --help` to see available commands.
- Key commands: `lk docs overview`, `lk docs search`, `lk docs get-page`, `lk docs code-search`, `lk docs changelog`, `lk docs pricing-info`.
- Run `lk docs <command> --help` before using a command for the first time.
- Prefer browsing (`overview`, `get-page`) over search, and `search` over `code-search`, as docs pages provide better context than raw code.
- Always check the docs before writing LiveKit code. The APIs change frequently and training data goes stale.
- If docs search returns excerpts only, fetch the full page before implementing.
- If the docs don't match the installed package or something breaks after an upgrade, check the changelog.
- Prefer official LiveKit patterns over custom architecture.
- Preserve the realtime voice pipeline unless the task explicitly requires changing it.
- Be careful around startup flow, room join flow, media handling, callbacks, turn logic, state transitions, and timing-sensitive code.

## 7. Local Testing and Deployment Workflow

Current local test command:
- `uv run src/agent.py console`

Current git workflow:
- `cd ~/Documents/LiveKit`
- `git add .`
- `git commit -m "Describe change"`
- `git push`

Current cloud sync and deploy workflow:
- `cd agents/main-bot`
- `uv run python scripts/sync_cloud_secrets.py --env-file .env.local`
- `lk agent deploy`

Use these commands unless the task explicitly requires a different workflow.

Before suggesting new commands, verify that they fit this repository.

## 8. Verification Requirements

Do the smallest relevant verification first.

Minimum checklist after changes:
- imports resolve;
- entrypoints still point to the correct modules;
- no obvious breakage in startup flow;
- no obvious breakage in room connection flow;
- no obvious breakage in media or realtime callbacks affected by the change.

If relevant to the task, also verify:
- local console run still starts with `uv run src/agent.py console`;
- changed behavior works end-to-end;
- existing behavior that should remain unchanged still works.

When reporting completion, summarize:
- what changed;
- why it changed;
- how it was verified;
- what was not verified.

## 9. Default Behavior Under Uncertainty

If unsure:
- prefer a targeted question over a hidden assumption;
- prefer a smaller safe change over a broad risky one;
- prefer current docs over remembered examples;
- prefer explicit tradeoffs over silent guesses.

These guidelines are working if:
- there are fewer unnecessary changes in diffs,
- there are fewer rewrites due to overcomplication,
- clarifying questions come before implementation rather than after mistakes.
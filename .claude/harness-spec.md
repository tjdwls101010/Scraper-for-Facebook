# Harness Spec — agentic-facebook

## Context

Python 3.11+ package (`hatchling`, `uv`/`pipx` install), CLI entry point `agentic-facebook`, tests via `pytest`, lint/format via `ruff`, hooks via `pre-commit`. Published to PyPI as `agentic-facebook` (v0.3.0, 2026-07-20). Single maintainer.

The repo already carries a `CLAUDE.md` of general behavioral guidelines (minimum code, surgical changes, goal-driven execution) that is about *developing* this package. This harness pass adds the first component about *using* the shipped tool.

## Goals

> "`.claude/skills/facebook` — a skill that drives the just-published agentic-facebook v0.3.0 CLI. It must teach Claude to chain the primitives (fetch/feed/comments/post/search/group) for real multi-hop tasks, carry the ban-risk and third-party-PII guidance as why-backed rules, and document the Post/Comment/Entity schemas so outputs are parsed without guessing."

From plan §8 (D7): the skill installs the published package (`uv tool install agentic-facebook`) and shells out to `agentic-facebook`. The division of labor the whole v0.3.0 design rests on: **the CLI does fast structured retrieval, the LLM does the navigation reasoning.** There is deliberately no `crawl` command — chaining is this skill's job.

## Behavior inventory

| id | behavior/knowledge/constraint | layer | component | status |
|----|-------------------------------|-------|-----------|--------|
| B1 | Ensure the CLI is installed and the session is live before retrieving | skill | facebook/SKILL.md | generated |
| B2 | Which primitive to reach for (flags themselves come from `agentic-facebook catalog`) | skill | facebook/SKILL.md | generated |
| B3 | Chain primitives for multi-hop tasks (the core value) | skill | facebook/SKILL.md | generated |
| B4 | Results go to a **file**, not stdout — read the file | skill | facebook/SKILL.md | generated |
| B5 | Exit codes carry meaning; 4 and 7 are not plain failures | skill | facebook/SKILL.md | generated |
| B6 | Ban-risk discipline (throwaway account, rate floors, no tight loops) | skill | facebook/SKILL.md | generated |
| B7 | Third-party PII discipline (don't commit, minimize, delete) | skill | facebook/SKILL.md | generated |
| B8 | Post vs Comment vs Entity, and which fields chain | skill | facebook/SKILL.md | generated |
| B9 | Recovery when retrieval fails (expiry, checkpoint, doc_id rotation) | skill | facebook/SKILL.md | generated |

## Component specs

### `.claude/skills/facebook/SKILL.md`

- **Directory name `facebook`** — that is the invocable name (`/facebook`), independent of the frontmatter `name`.
- **Scope: repo-local only** (user decision, 2026-07-20). It therefore triggers only in sessions working inside this repository; copying the directory to `~/.claude/skills/facebook` would make it available everywhere, at the cost of not shipping with a clone.
- **`description`**: triggers on Facebook data requests phrased by *intent*, not just the keyword — "what has X been posting", "who commented on this", "find people/groups about Y", "check my feed". Names near-misses explicitly: *developing/testing this package itself* is out of scope (ordinary repo work), as is any other social network.
- **`allowed-tools`**: `Bash(agentic-facebook:*)`, `Read` — every step shells out to `agentic-facebook` and then reads the JSON it wrote; without this the skill stalls on a permission prompt per command.
- **Auto-triggerable** (no `disable-model-invocation`): retrieval is user-initiated and read-only. It is *not* a deploy-shaped side effect. Ban/PII risk is handled by in-body rules, not by hiding the skill.
- Body: preflight (install/login/status) → the six primitives as a compact table → chaining recipes → the schema orientation → the two rule sets (ban risk, PII), each stated as principle + why.

### Single file — no `references/`

Failure handling lives in SKILL.md, not a reference file. It was split out initially on an "it worked vs it failed" branch, then merged: that is an *appendix*, not a branch (the model never chooses between the two files, it reads the second in addition), and the highest-stakes instruction in the whole skill — exit 3 means stop, never retry a checkpointed account — had ended up behind a file that only opens after something already went wrong. At ~140 lines merged, the happy-path cost of inlining it is small next to that risk.

## Design rationale

- **One skill, not several.** `fetch`/`feed`/`comments`/`post`/`search`/`group` share one trigger context ("get me something off Facebook") and a single multi-hop task uses several of them *together* — a user thinks of this as one job. Six skills would burn six description slots out of the shared ~1% listing budget to answer the same trigger.
- **One file, no `references/`.** See the component spec: the failure material is an appendix rather than a branch, and burying the checkpoint stop-rule behind a second file put the most safety-critical line where it loads only after the damage. Splitting the primitives per-command would have been worse still — a chain needs them in the same breath.
- **Reference data is pointed at, not transcribed** — extended in v0.3.1 from schemas to the whole CLI surface. `agentic-facebook catalog` reports commands, flags, exit codes, output contract, object types and limitations, all derived from the live parser and the `to_dict()`-anchored schema functions. The skill therefore carries **no** command/flag table: a copy would describe whichever version was current when it was written, and a model trusts a copy over its own reading. What stays in the skill is judgment the catalog cannot carry — which primitive to reach for, how to chain, and the ban/PII rules.
- **No hook, no permissions entry.** Nothing here must be *enforced* — the guardrails that genuinely must not fail (the ≥1.0s active floor, the ≥0.5s scroll floor) are already clamped inside the package and cannot be bypassed from the CLI at all. A hook would be re-implementing, less reliably, a guarantee that already exists in code.
- **No CLAUDE.md pointer.** The existing CLAUDE.md is about developing this package and is loaded every session; scraping Facebook is not something every session needs. Adding a line would spend the always-on budget on a rarely-relevant pointer.

## Validation

Scenarios for the optional e2e pass:
1. "What has <profile> been posting lately?" → expects `fetch --limit`, then reads the output file rather than expecting stdout.
2. "Who commented on <post URL>, and what else do those people post?" → expects `comments` → collect `author_url` → `fetch` per author, with a sane `--limit` rather than an unbounded fan-out.
3. "Find Facebook groups about <topic>" → expects `search --type groups`, and parses `kind`-bearing Entity objects rather than looking for post fields.
4. Failure path: a command exits 2 → expects the skill to route to `agentic-facebook login` rather than retrying blindly.

Most recent run: **2026-07-20, 4/4 passed** (~$1.88, ~10 min total), against package v0.3.1 installed from PyPI.

| # | Scenario | Verdict | Evidence |
|---|---|---|---|
| V1 | "피드에서 최근 글 5개 요약" | **pass** | `Skill: facebook` → `catalog` → `status` → `feed --limit 5 --output /tmp/...` → `Read` the file (not stdout) → `rm` the file unprompted |
| V2 | multi-hop: busiest post → its commenters → their timelines | **pass** | `feed --limit 15` → picked max `comment_count` → `comments <url>` → distinct `author_url` → `fetch` ×3; substituted 2 authors whose timelines were empty **and reported having done so** |
| V3 | "'seoul' 관련 그룹 찾아줘" | **pass** | `search --type groups --limit 25` → took each Entity `id` → `group <id>` ×9 to check liveness; ranked by reaction/comment counts, not post frequency |
| V4 | near-miss: "이 저장소의 파서 테스트 실행" | **pass** | `skill_invocations: []` — correctly read as ordinary repo work, ran pytest |

Two things the run established beyond the scenarios themselves:
- The **headless mechanism works**: `claude -p` spawned from Bash is authenticated here, so `run_e2e.py`'s permission approach (`--isolate` + skip-permissions) is confirmed for this project and no longer needs flagging as unverified.
- The PII rules are followed **without being asked** — every scenario deleted its scraped temp files at the end.

Defects the run surfaced (both fixed): the skill only handled a *missing* install, not an *outdated* one (the machine had 0.2.0, which lacks `catalog` and five primitives); and e2e `transcript.jsonl` files carry scraped PII while the repo's `*.json` ignore rule does not cover `.jsonl`.

## Change history

- 2026-07-20 — **new**. First harness pass on this repo. Recovered a spec from disk (an empty `.claude/skills/facebook/` placeholder existed, no SKILL.md). Generated the `facebook` skill (SKILL.md + references/troubleshooting.md) after the v0.3.0 PyPI release. `validate_harness.py`: 0 errors, 0 warnings. Scope set to repo-local per user. No hooks, permissions, agents, or CLAUDE.md changes — rationale above.
- 2026-07-20 — **improve**. Rewired the skill onto `agentic-facebook catalog` (added in package v0.3.1): removed the transcribed command/flag table and the duplicated exit-code and limitations tables from SKILL.md and troubleshooting.md, leaving each pointing at the derived source. Removes the package/skill drift risk that a copied table carried, which matters once the skill is used against a PyPI-installed package rather than this checkout.
- 2026-07-20 — **improve**. Merged `references/troubleshooting.md` into SKILL.md (user call, agreed): the split was an appendix, not a branch, and it had hidden the exit-3 stop-rule behind a conditional load.
- 2026-07-20 — **validate**. Ran the 4 e2e scenarios: 4/4 pass. Fixed two defects they surfaced (outdated-install handling in the skill; `.jsonl` PII leak in .gitignore). Transcripts deleted after grading.

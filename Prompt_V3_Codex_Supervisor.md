This is a companion prompt for generating `codex_supervisor.py`.
It defines the required behavior of a Codex-driven self-healing supervisor that wraps `orchestrator.py`.

# Goal

Build a Python 3.10 supervisor named `codex_supervisor.py` that runs `orchestrator.py`, captures failures automatically, invokes `codex exec` as a bounded repair agent, and reruns the orchestrator without requiring manual copy/paste of traceback output.

The supervisor must be production-oriented, conservative, and observable.
It must never act like an unbounded autonomous editor.

# Core purpose

The supervisor exists to remove this manual loop:

1. `orchestrator.py` fails
2. human copies the traceback
3. Codex analyzes it later
4. Codex patches files
5. human reruns the orchestrator

The supervisor must replace that with:

1. run `orchestrator.py`
2. capture stdout, stderr, exit code, and timing
3. classify the failure
4. prepare bounded repair context
5. run `codex exec` to patch the repo
6. verify the patch
7. rerun `orchestrator.py`
8. stop on success or after a bounded number of repair attempts

# Hard constraints

- Use Python 3.10.
- Use `codex exec` for repair steps.
- Do not use the OpenAI API or Codex SDK.
- Do not require the user to paste traceback text back into the system.
- Keep all repair loops bounded.
- Keep all repair actions observable through logs and structured records.
- Prefer small durable fixes over broad rewrites.
- Do not allow unrestricted repository edits.

# Files and integration

The supervisor must integrate with:

- `orchestrator.py`
- `.orchestrator/` stage artifacts
- `.orchestrator/checkpoints.json`
- `.orchestrator/decision_log.jsonl`
- `.orchestrator/plan.json`
- `.orchestrator/reports/artifact_validation.json`
- `.orchestrator/reports/build_validation.json`
- `.orchestrator/reports/runtime_validation.json`

It must write its own state under:

- `.self_heal/attempts.jsonl`
- `.self_heal/run_logs/*.log`
- `.self_heal/repair_logs/*.json`
- `.self_heal/schemas/*.json`
- `.self_heal/final_report.json`

# Command model

The supervisor must run the orchestrator with a command equivalent to:

```bash
python3 orchestrator.py --project-brief Project_description.md
```

It must forward relevant flags when needed, including:

- `--project-brief`
- `--max-concurrency`
- `--bootstrap-plan`
- `--dry-run-preflight`

After a repair, it must be able to rerun with:

- `--resume-from-stage`

when conservative resume is valid.

# Required supervisor behavior

## 1. Streaming run wrapper

The supervisor must:

- launch `orchestrator.py` as a subprocess
- stream combined output to screen in real time
- capture the full combined output in memory
- record exit code
- record run duration
- write a run log file for every attempt

## 2. Failure classification

The supervisor must classify failures into useful buckets.

At minimum support:

- `schema_compatibility`
- `stale_worktree`
- `dependency_deadlock`
- `filesystem_policy`
- `artifact_validation`
- `build_validation`
- `runtime_validation`
- `codex_exec_failure`
- `unknown`

Classification should be based on traceback and log text, not only exit code.

## 3. Local pre-diagnosis before Codex repair

The supervisor must not always send raw failure logs directly to Codex.
It must perform local diagnosis first when possible.

For stage-based validation failures, the supervisor must treat persisted validation artifacts as primary evidence, not optional context.

At minimum:

- for `artifact_validation`, read `.orchestrator/reports/artifact_validation.json` when it exists
- for `build_validation`, read `.orchestrator/reports/build_validation.json` when it exists
- for `runtime_validation`, read `.orchestrator/reports/runtime_validation.json` when it exists
- extract the validator summary into the diagnosis
- extract concrete findings into repair hints
- extract or infer cited file paths from findings and use them as suspected files
- when the validator report includes explicit per-finding source files, prefer those over path inference
- prefer validator-cited files over broad speculative edit scopes

The supervisor must not reduce an artifact, build, or runtime validation failure to a generic label such as only `artifact_validation` when a structured report already contains the real root cause.

At minimum, for `filesystem_policy` failures it must:

- parse `Created outside allowlist: ...` paths
- read `.orchestrator/plan.json`
- compare those created paths against worker `owned_paths`
- detect the case where the created files are already owned by the worker
- detect the special case where Next.js dynamic route paths such as `[attemptId]` or `[puzzleId]` are likely being misinterpreted as glob syntax rather than literal paths

This special case should produce a stronger diagnosis such as:

- `filesystem_policy_bracket_path_mismatch`

When local diagnosis strongly indicates a root cause, that diagnosis must be included in the Codex repair prompt as strong evidence.
When a persisted validation report exists, it must also be included in the Codex repair prompt as strong evidence.

## 4. Bounded editable file scope

The supervisor must compute an allowed editable file set for each failure class.

Rules:

- always allow `orchestrator.py`
- always allow `codex_supervisor.py`
- allow `Prompt_V3.md` only when prompt hardening is relevant
- allow application files only when the failure class requires them
- when a strong local diagnosis points to a narrow root cause, narrow the editable set further
- when a validator report cites concrete files, include those files in the editable set unless doing so would violate a stronger safety boundary

After Codex edits files, the supervisor must diff the repo state and block the repair if Codex changed files outside the allowed set.

## 5. Codex repair prompt

The supervisor must run `codex exec` with:

- JSON event output
- an output schema
- bounded editable-file instructions
- the orchestrator command that must succeed next
- the failure class
- local diagnosis summary
- persisted validation report excerpt when available
- explicit per-finding source files when available
- recent failure output
- recent decision log tail
- current git worktree state
- current git status
- plan excerpt if present

The repair prompt must require:

- the smallest durable fix
- no network access
- no package installation
- no edits outside the allowed file list
- a structured JSON final response
- treating local diagnosis and persisted validator findings as strong evidence unless clearly disproved by code
- prioritizing files explicitly cited by the validator before speculative edits elsewhere
- preferring validator-provided per-finding source files over heuristic file guessing

## 6. Structured repair result

The Codex repair output schema must include at least:

- `final_status`
- `root_cause`
- `summary`
- `changed_files`
- `verification`
- `blockers`

The supervisor must parse the JSONL event stream, collect usage data, and surface real Codex error payloads instead of only generic stderr banners.

## 7. Verification after repair

After a repair the supervisor must:

- snapshot the workspace before and after repair
- detect changed files
- verify the changed files are inside the allowed set
- run lightweight verification such as Python compilation when relevant
- persist a structured repair log

## 8. Failure fingerprints and bounded retries

The supervisor must:

- compute a failure fingerprint from the classified failure and tail of the output
- detect repeated identical failures
- stop after a bounded number of repair attempts
- stop early if the same failure fingerprint repeats too many times
- emit a final blocked report when it gives up

It must never loop indefinitely.

# Resume and checkpoint integration

The supervisor must work with a checkpoint-capable `orchestrator.py`.

## Resume policy

After a repair, the supervisor must choose a conservative resume point instead of always restarting from Stage 1.

It must map changed files to an earliest invalidated stage.

Conservative examples:

- if only worker output files changed, resume from `Worker generation`
- if artifact/build/runtime fixes were applied, resume from `Artifact validation` or earlier
- if planner or schema logic changed, resume from `Planner generation` or earlier
- if context ingestion changed, resume from `Context analysis` or earlier
- if only final documentation changed, resume from `Final acceptance summary`
- if validity is uncertain, restart from Stage 1

## Checkpoint expectations

The supervisor should assume `orchestrator.py` provides:

- `.orchestrator/checkpoints.json`
- per-stage durable artifacts
- `--resume-from-stage`

The supervisor must not request resume from a later stage unless the repair scope justifies it conservatively.

# Operational safety rules

- Do not use destructive git operations such as `git reset --hard`.
- Do not assume Codex repairs are always correct.
- Prefer blocking with a clear report over unsafe automatic continuation.
- Keep a full audit trail of runs and repairs.
- Never silently swallow Codex or subprocess failures.

# Recommended implementation shape

The generated `codex_supervisor.py` should contain:

- subprocess runner for streaming orchestrator output
- failure classifier
- local diagnosis helpers
- persisted validation-report readers and summarizers
- helper(s) that extract suspected file paths from validator findings
- workspace snapshot and diff helpers
- repair schema writer
- Codex repair runner
- conservative resume-stage chooser
- final report writer

# Human-facing behavior

The supervisor should print visible progress messages, including:

- supervisor run attempt number
- repair attempt number
- selected resume stage for reruns
- blocked status when stopping

It must also support an explicit verbose mode such as `--verbose` that prints detailed internal reasoning, including:

- failure classification
- diagnosis summary
- validator hints
- suspected files
- allowed editable files
- whether a persisted validation report was included
- repair result summary
- detected changed files
- disallowed changes
- chosen resume-stage reasoning

It should remain concise but explicit.

# README expectations

The repository README should document:

- how to run `codex_supervisor.py`
- where `.self_heal/` outputs are written
- that the supervisor applies bounded Codex repair attempts
- that resumed reruns use conservative stage selection

# Final result

The generated `codex_supervisor.py` must:

- automatically capture orchestrator failures
- invoke Codex for bounded repairs
- detect and block out-of-scope edits
- support conservative rerun from checkpoints
- provide structured logs and reports
- remove the need for manual error copy/paste in normal repair flows

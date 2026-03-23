This is going to be a long document.
Please read this fully to the very end and confirm when you’re done by saying "I read it all".
After you fully read the document, execute the prompt from here.
You have the right to use this current directory Project_1 without limitation, so don't ask for permissions.

# Goal

Build a Codex-only multi-agent workflow in Python 3.10 that is concurrent, modular, and semi-deterministic, without using the OpenAI API or Codex SDK. Parallelism must be achieved by spawning multiple `codex exec` processes concurrently.

The workflow must be production-oriented. It must be able to ingest a file named `Project_description.md` and use that file as the project-specific software brief that drives planning, generation, validation, and final acceptance.
The multi-agent workflow MUST be able to READ `Project_description.md` IN FULL at first ingestion!!!

# Prerequisite

- Codex CLI is already authenticated via `codex login`.

# Core design requirements

- Use Python 3.10 as the orchestration language.
- Use `codex exec` as the execution mechanism for all role steps.
- Prefer a technology stack centered on Python 3.10 to build the multi-agent. But the multi-agent should use technology stack based on Next.js, SQLite, and WebGPU or WebGL when those technologies are relevant to the software described in `Project_description.md`.
- Keep the system semi-deterministic through:
  - validators that check file existence
  - SHA-256 manifests and workspace snapshots
  - per-step filesystem allowlists
- Keep the number of agents small.
- Keep the number of stages explicit.
- Do not merge stages just because there are few agents.
- Do not create extra agents just because there are many checks.

# Required input

The generated multi-agent system must explicitly consume `Project_description.md` in FULL before commencing development of the application!!!

It must treat `Project_description.md` as the canonical project brief for the run and use it to derive:
- scope
- constraints
- success criteria
- expected outputs
- stack-specific requirements
- validation expectations

The workflow must not assume hidden requirements outside repository state, shared state, and `Project_description.md`.

# General rules for concurrent multi-agent behavior

Give each agent an isolated workspace. For editing tasks, use separate git worktrees.

Example strategy:
- parent repo: integration only
- worker A: `~/multi-agent-producer_V0/Project_3_education/tmp/worktrees/task-a`
- worker B: `~/multi-agent-producer_V0/Project_3_education/tmp/worktrees/task-b`

That avoids file collisions.

## Git worktree lifecycle

The orchestrator must make worker worktree management rerun-safe.

Requirements:
- before creating a worker worktree, run `git worktree prune`
- if the target worktree path is already registered, remove that registration before re-adding it
- support the case where a worktree is missing on disk but still registered in git metadata
- worker teardown must remove the worktree registration and then prune stale metadata
- rerunning the orchestrator after an interrupted worker must not fail because of stale worktree state

Restrict each agent’s scope. Every worker prompt must state:
- owned files or owned paths
- forbidden files
- read-only inputs
- editable outputs
- required output format

Example:

```text
You own only:
- src/auth/*
- tests/auth/*

Do not modify any other files.
Return:
FINAL_STATUS:
CHANGED_FILES:
SUMMARY:
```

Bound concurrency. Do not run all agents at once unless there is a clear reason. Use a semaphore or equivalent concurrency limiter so only `N` workers run at the same time. When one finishes, another may start.

Capture structured outputs. Do not rely only on prose. Every worker must return a parseable final section.

## Worker dependency semantics

Worker task `dependencies` must use one of these explicit forms only:
- role dependencies: execution role names such as `Architect`, `Backend Producer`, `Frontend Producer`
- artifact dependencies: concrete relative file paths that already exist before worker execution
- produced artifact dependencies: concrete relative file paths that are owned by exactly one worker task

The orchestrator must resolve dependencies by:
- treating role dependencies as satisfied when that role has completed
- treating artifact dependencies as satisfied when the file already exists in the repository or shared state
- treating produced artifact dependencies as satisfied when the owning worker has completed

The orchestrator must not assume that every dependency entry is a role name.
If a dependency cannot be mapped to an existing artifact or a unique producing worker, planner validation must fail before worker execution.

Separate roles:
- explorers for read-only analysis
- workers for isolated edits
- orchestrator for coordination and final integration

# Multi-agent structure

Use a hub-and-spoke model with one control hub and five execution roles.

## Control hub

### Orchestrator

Role:
- receives the external request
- reads `Project_description.md` in full
- decomposes work
- assigns tasks
- tracks dependencies
- bounds concurrency
- merges outputs
- handles blockers
- decides when to re-plan

Reporting:
- all agents report status, blockers, and final outputs to the Orchestrator
- the Orchestrator is the only control and routing authority

## Execution roles

### Context Analyst

Role:
- interprets `Project_description.md` and relevant repository context
- extracts domain, constraints, success criteria, assumptions, missing information, and important existing repo constraints
- produces structured requirements for planning

Reports to:
- Orchestrator

### Architect

Role:
- defines system boundaries
- defines module structure
- defines interfaces and data contracts
- defines task decomposition
- produces the machine-checkable plan used by downstream roles

Reports to:
- Orchestrator

### Backend Producer

Role:
- builds services, APIs, business logic, workflows, data access, and integration points
- implements against the Architect’s contracts

Reports to:
- Orchestrator

### Frontend Producer

Role:
- builds UI, flows, forms, dashboards, and client-side behavior
- implements against the Architect’s contracts

Reports to:
- Orchestrator

### Verification Agent

Role:
- validates outputs
- runs tests and checks
- checks acceptance criteria
- detects regressions and integration mismatches
- reports failures to the Orchestrator for targeted repair

Reports to:
- Orchestrator

# Pipeline stages

Stages are the pipeline. Agents are workers assigned inside that pipeline. The Orchestrator is the only agent that spans all stages.

The workflow must be phase-based and fail early. It should contain these stages in this order:

1. Environment preflight
2. Context analysis
3. Planner generation
4. Planner schema validation
5. Planner repair loop if needed
6. Worker generation
7. Artifact validation
8. Build validation
9. Runtime validation
10. Final acceptance summary

The orchestrator must persist explicit stage checkpoints so it can resume conservatively after a repair instead of always restarting from Stage 1.

The practical flow is:
- Context Analyst -> structured requirements
- Orchestrator -> task plan and dependency graph
- Architect -> interfaces, contracts, ownership, and validation expectations
- Backend Producer + Frontend Producer -> parallel implementation within bounded concurrency
- Verification Agent -> artifact, build, and runtime validation
- Orchestrator -> merge, resolve, re-plan if needed, and produce final summary

Planner generation is a stage, not a separate hidden agent.

# Planner generation requirements

Planner generation exists to convert vague intent into a machine-usable work plan before code-producing agents start editing files.
Planner gernration transforms a product brief into a work plan. To do that, the `Project_description.md` should be used and read in full.
`Project_description.md` file is the product brief.
 

The orchestrator must use the plan to:
- decide which agents to call
- decide in which order to call them
- assign file ownership
- reject overlapping ownership
- know which outputs are mandatory
- know which validation checks to run
- know which contracts must be enforced

The plan must be machine-checkable and must drive later stages.

The plan should include at least:
- task summary
- roles
- owned paths
- required outputs
- dependencies
- contracts
- validation rules
- build expectations
- runtime expectations

Validation expectations must not require package installation or network access.
Do not use commands such as `npm install`, `npm ci`, `pnpm install`, `yarn install`, or `bun install` in build or runtime expectations.
Prefer offline-safe checks that operate on repository state, and when JavaScript dependencies are not guaranteed to exist locally, prefer artifact-based validation over `npm run ...` commands.
Do not emit directory placeholders such as `app` or `scripts` in any path field that is later consumed as a file path.
Do not emit `npm run ...`, `pnpm ...`, `yarn ...`, `bun ...`, or `node path/to/file.ts` as build or runtime expectations unless the repository already contains the local runtime dependencies needed to execute them offline.

The plan must not output vague sentences in fields that are later consumed as structured inputs.
This is bad:

```text
Responsive user interface with rich animations and clear game progression
```

This is acceptable:

```text
frontend/index.html
frontend/src/App.tsx
frontend/src/components/GameBoard.tsx
```

The planner must avoid:
- overlapping ownership across agents
- impossible validation rules
- validations based only on wording preference
- outputs that do not map to real files, routes, commands, or testable behavior

## Planner contract rules

- Every `owned_path` must be a concrete relative file path.
- Every `required_output` must be a concrete relative file path.
- Every `shared_artifact` and every plan-level `contract` must be a concrete relative file path.
- Path fields must not contain leading or trailing whitespace.
- Path fields must not use `./` prefixes.
- No prose deliverable may appear in a path field.
- Validation rules must declare what kind of check they require.
- Validation-rule targets must be concrete relative file paths unless the rule kind explicitly expects a shell command.
- Planner fields consumed by the orchestrator must be narrow, typed, and repairable.

## Codex output-schema compatibility

All JSON Schemas used with `codex exec --output-schema` must be compatible with Codex response-format validation requirements.

Rules:
- every property schema must declare an explicit `"type"`
- fields using `"const"` must also declare the matching `"type"`
- boolean fields must use `"type": "boolean"`
- string constants must use `"type": "string"`
- object fields must use `"type": "object"`
- array fields must use `"type": "array"`

Examples of acceptable fields:

```json
{"type": "string", "const": "Project_description.md"}
```

```json
{"type": "boolean", "const": true}
```

The generated orchestrator must not rely on generic JSON Schema assumptions when Codex `--output-schema` imposes stricter compatibility requirements.

Before the first real role execution that depends on schema-constrained output, the orchestrator must validate that its generated schemas are accepted by `codex exec --output-schema` using a minimal probe call and fail early with the exact schema validation message if a schema is rejected.

If planner validation fails, the orchestrator must reject the plan before worker execution and return a targeted repair message that points to the exact offending field.

# Communication and shared-state rules

Messages are for coordination. Shared artifacts are for deliverables.

Agents may communicate directly only for narrowly scoped clarification or interface coordination.

Direct communication must not change:
- priorities
- ownership
- requirements
- final decisions

Any material decision made in direct communication must be recorded in shared state and surfaced to the Orchestrator.

Each agent must follow these rules:
- never assume another agent saw a prior conversation unless it is in shared state
- every important decision must be written to a decision log
- every artifact must have a version
- every task must have an owner
- every blocker must go to the Orchestrator
- agents must not overwrite shared artifacts without ownership or lock rules

# Runtime and filesystem control

The workflow must include these runtime layers:

## Runtime/config layer

Define up front:
- model
- sandbox mode
- approval policy
- workspace root
- timeout policy
- canonical output locations
- checkpoint location for resumable stage state

## Execution engine

Run every role step through one Codex execution path that:
- launches `codex exec`
- captures structured events
- captures the final worker message
- tracks usage
- enforces timeouts
- surfaces structured error payloads from `codex exec`, including JSON event errors and API validation failures

Generic stderr banners such as `Reading prompt from stdin...` must not be treated as the primary failure reason when structured JSON error events contain the actual cause.

## Filesystem control layer

For each step:
- snapshot the workspace before and after execution
- compute SHA-256 hashes
- diff created, modified, and deleted files
- enforce a per-step allowlist
- allow some inputs to be frozen

## Worktree-aware filesystem policy

Filesystem policy enforcement must be scoped to approved paths only.

Rules:
- a fresh worker worktree must not be interpreted as deleting files that exist only in the parent workspace
- deletion checks must apply only to files within the worker's allowed scope
- required outputs must be validated against the worker's declared owned paths and explicit required outputs, not against unrelated repository files
- policy checks must compare changes within the worker execution scope rather than treating missing unrelated files as deletions

Each agent step must only be allowed to create or modify approved files. It must not delete files unless deletion has been explicitly allowed by policy.

## Checkpoints and resume

The orchestrator must support conservative resume after repair.

Requirements:
- persist a checkpoint record after each completed stage
- each checkpoint must record the stage name, timestamp, required artifact paths, and project brief hash
- the orchestrator must support a CLI option to resume from a chosen stage
- resume must verify that all prior required checkpoints and artifacts still exist before skipping earlier stages
- resume must reload durable stage artifacts such as context analysis, plan, validation reports, and worker results instead of recomputing them
- if a repair changes files that could invalidate earlier stages, the supervisor or orchestrator must restart from the earliest invalidated stage instead of resuming too late
- resume behavior must be conservative; when validity is uncertain, restart from an earlier stage

Acceptable conservative resume examples:
- after a worker-scope code repair, resume from `Worker generation`
- after an artifact/build/runtime validation fix, resume from `Artifact validation` or earlier
- after planner or schema logic changes, resume from `Planner generation` or earlier
- after context-ingestion logic changes, resume from `Context analysis` or Stage 1

## Manifest and provenance

Write a manifest after major stages so the system retains a provenance record and can tie role outputs to a known workspace state.

# Validator and quality-gate requirements

Validation must be based on durable evidence, not brittle wording.

The orchestrator must not treat free-form planner wording as fatal proof requirements unless a rule is explicitly defined as an exact literal requirement.

Validators must prefer:
- structural checks
- normalized contract checks
- artifact-aware evidence collection

Verification-agent findings must be machine-usable.
Each finding must include:
- severity
- message
- concrete source file paths actually inspected while producing that finding

Do not return speculative findings without file-level evidence.

## Artifact coverage

Validators must read the artifact types they claim to verify. Relevant sources may include:
- TypeScript
- JavaScript
- SQL
- Markdown
- HTML
- CSS
- configuration files

If a required output includes a `.sql` file, validation must read that `.sql` file rather than infer its contents from other sources.

## Contract and route validation

Where contracts are defined in shared documents such as `TEST.md` or similar contract files, validators must treat those documents as the declared contract source.

Route and endpoint validation must normalize equivalent forms before comparison. At minimum, normalization must account for:
- markdown backticks
- query strings
- mounted router prefixes
- parameterized route syntax such as `:id`, `{param}`, or representative literal values

Equivalent route forms must be treated as the same route family.

The system must also be able to detect real route composition bugs such as duplicated mounted prefixes.

## Documentation and QA validation

Documentation and test-plan checks must be semantic, not dependent on one exact human-facing heading. Equivalent section titles must be accepted when they clearly express the same intent.

# Framework-aware validation

Validation must be aware of the chosen stack rather than relying on generic file checks.

Examples that must be handled when relevant to the planned stack:
- a Next.js frontend must satisfy Next.js-required app structure and entry conventions
- a backend mounted behind route prefixes must be validated with mount-aware route composition
- a browser frontend calling a separate backend origin must trigger CORS expectations
- a TypeScript or JavaScript frontend/backend project must have one coherent module strategy across package metadata, configuration, runtime commands, and source syntax

Build and runtime viability must be checked before success is reported.

At minimum, when applicable:
- the frontend must pass production build
- the frontend must pass type checking
- the backend must start successfully
- the backend must satisfy health and contract checks


# Environment preflight

Environment and dependency viability must be checked before generation work starts.

The preflight stage should verify, when relevant:
- required command-line tools are available
- package-manager behavior that affects installation
- whether install scripts are disabled
- native dependency prerequisites
- whether required native artifacts exist after installation

The workflow must fail early with a targeted remediation message if critical environment requirements are missing.

# Worker execution resilience

Worker execution must be treated as potentially unreliable infrastructure.

The orchestrator must:
- classify worker failures
- distinguish transient execution failures from ordinary task failures
- retry only when the failure class is retryable
- keep retries bounded
- run retries in a fresh staged workspace
- clean up failed worker state predictably

Subprocess output collection must be robust. Do not assume line-buffered output will always be small enough for default readers. The execution layer must be resilient to very large JSON events.

Recognizable Codex runtime corruption signatures should be treated as retryable infrastructure failures rather than ordinary task failures.

# Human-facing quality floor

If the generated application is user-facing, validation must include lightweight clarity checks in addition to technical checks.

For interactive surfaces, when relevant:
- important entities should be visually distinguishable
- alignment should match the positioning model used by the code
- the interface should provide basic labels, legend support, or equivalent explanatory cues

Do not accept a technically runnable interface that is materially confusing to use.

# These locations should be created for placing of future assets:
- `public/assets/backgrounds/` for scene background `PNG` files
- `public/assets/sprites/` for character, pet, prop, object, and effect `PNG` files
- `design/layout_refs/` for user-provided scene layout drawings or placement reference files
These locations should not be populated, but they should exist before the orchestrator.py is run.

# Final system behavior

The final generated multi-agent workflow must:
- consume `Project_description.md` in full
- create a schema-driven plan and use the `Project_description.md`
- assign explicit ownership and outputs
- run bounded concurrent workers
- validate artifacts semantically
- enforce filesystem policy
- run build and runtime gates before success
- support targeted repair loops
- emit structured final outputs and error reports
- use verbose mode and report back to screen on every step taken by any agents and all internal actions and report every new step in pink color and bold font
- no silent execution by the orchestrator or any other subagents
- provide final readme.md file with instructions on how to start the application

The final design should be explicit, typed, phase-based, and production-oriented. Avoid vague heuristics. Avoid duplicate role definitions. Avoid late discovery of environment, contract, build, or runtime failures.

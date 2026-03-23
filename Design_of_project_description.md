# Design Of `Project_description.md`

This note is based only on the Python source files under `src/codex_multi_agent/`.

## 1. What the code actually requires

From the source code, `Project_description.md` is:

- A required file in the repository root by default.
- Read as plain UTF-8 text.
- Passed directly into multiple agent prompts.
- Treated as the canonical project brief for a workflow run.

This is visible in:

- `src/codex_multi_agent/models.py`
- `src/codex_multi_agent/cli.py`
- `src/codex_multi_agent/orchestrator.py`
- `src/codex_multi_agent/prompts.py`

Important consequence:

- There is no parser for a fixed Markdown schema.
- The file does not need specific YAML keys or JSON fields.
- Its job is to provide enough clear, concrete information for the agents to plan work, assign file ownership, and validate outputs.

## 2. What the agents try to extract from it

The prompt code shows the expected content very clearly.

The `Context Analyst` is instructed to extract:

- domain
- constraints
- success criteria
- assumptions
- missing information
- stack requirements
- validation expectations
- repo constraints

The `Architect` then uses the brief plus that context to generate tasks with:

- concrete relative file paths
- required outputs
- dependencies
- contracts
- validation rules
- build expectations
- runtime expectations

Because of that, a good `Project_description.md` should make those things easy to infer instead of leaving them ambiguous.

## 3. What `Project_description.md` should look like

It should look like a concise, implementation-oriented product brief, not like code and not like a vague idea dump.

A strong version should contain these sections:

## Project Summary

State what is being built in one short paragraph.

Example of the kind of information needed:

- product or tool name
- primary purpose
- target user
- main outcome

## Scope

List what the workflow is expected to produce in this run.

This matters because the planner must create concrete tasks and `required_outputs`.

Include:

- in-scope features
- explicitly out-of-scope items
- whether the run is MVP, prototype, refactor, or production hardening

## Functional Requirements

Describe the required behaviors in direct, testable language.

Good content here:

- user flows
- key screens, commands, endpoints, or background jobs
- required inputs and outputs
- data handling rules

Avoid:

- marketing wording without implementation meaning
- requirements that cannot be checked

## Technical Constraints

State the technical boundaries the agents must respect.

This matters because the context-analysis prompt explicitly asks for constraints and stack expectations.

Include things like:

- required language or framework
- forbidden technologies
- deployment assumptions
- performance or security constraints
- compatibility requirements

## Repository / File Expectations

This repo’s planner requires concrete relative paths, and workers are later checked against allowlists.

So the brief should say where work is expected to happen, for example:

- which directories should contain new code
- which existing files should be updated
- which files are frozen or should not be touched
- what output artifacts must exist after the run

Without this, the Architect can still guess, but the brief is stronger if it names likely file locations.

## Validation Requirements

This is one of the most important sections.

The orchestrator runs build and runtime validation commands from the plan. So the brief should describe how success should be validated.

Include:

- commands that should pass
- expected runtime behavior
- acceptance criteria
- manual checks if automation is not available

Examples of the right kind of information:

- "`pytest` must pass"
- "`python -m ...` should start without errors"
- "the CLI must create file X"
- "page Y must render state Z"

## Assumptions And Open Questions

The Context Analyst prompt explicitly asks for assumptions and missing information.

If something is undecided, put it here instead of hiding the ambiguity.

This helps the planner avoid inventing requirements.

## 4. Recommended writing style

The source code suggests these writing rules:

- Prefer concrete statements over broad goals.
- Prefer testable requirements over aesthetic claims.
- Prefer explicit file/output expectations over "build whatever is needed".
- Prefer short sections with headings.
- Prefer bullet points for constraints and acceptance criteria.

Since the file is inserted directly into prompts as plain text, readability matters more than formal syntax.

## 5. What is not required by the code

Based on `src/` alone, the code does not require:

- a strict Markdown schema
- front matter
- YAML
- JSON
- numbered IDs for every requirement
- a specific document title

Those can help humans, but the Python code does not enforce them.

## 6. Minimal practical template

```md
# Project Description

## Project Summary
- Build:
- Purpose:
- Target users:

## Scope
- In scope:
- Out of scope:
- Expected maturity level:

## Functional Requirements
- Requirement 1:
- Requirement 2:
- Requirement 3:

## Technical Constraints
- Required stack:
- Forbidden stack or libraries:
- Environment constraints:

## Repository / File Expectations
- Work should primarily happen in:
- New files may be added in:
- Do not modify:
- Required output artifacts:

## Validation Requirements
- Build checks:
- Runtime checks:
- Acceptance criteria:

## Assumptions And Open Questions
- Assumption 1:
- Open question 1:
```

## 7. Best conclusion from `src/`

If you want `Project_description.md` to work well with this repository, it should be a canonical run brief that is:

- plain-text Markdown
- concrete
- implementation-oriented
- explicit about constraints
- explicit about expected files/artifacts
- explicit about validation and acceptance

The most important thing is not formatting. The most important thing is that the brief gives the agents enough precise information to produce:

- a valid plan
- concrete owned paths
- required outputs
- meaningful validation commands
- a checkable final result


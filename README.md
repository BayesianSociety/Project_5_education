# Codex-Only Multi-Agent Orchestrator

This repository now includes a production-oriented `orchestrator.py` that reads [`Project_description.md`](/home/postnl/multi-agent-producer_V0/Project_3_education/Project_description.md) in full before worker execution and coordinates a small Codex-only multi-agent workflow.

The workflow is phase-based and explicit:

1. `Environment preflight`
2. `Context analysis`
3. `Planner generation`
4. `Planner schema validation`
5. `Planner repair loop if needed`
6. `Worker generation`
7. `Artifact validation`
8. `Build validation`
9. `Runtime validation`
10. `Final acceptance summary`

It uses:

- `codex exec` for all role execution steps
- Python 3.10-compatible orchestration
- bounded worker concurrency with a semaphore
- isolated git worktrees for editing workers
- SHA-256 manifests and workspace snapshots
- per-step filesystem allowlists
- typed planner validation and targeted repair
- pink bold terminal logging for every major step

## Start

Run the full workflow from the repository root:

```bash
python3 orchestrator.py --project-brief Project_description.md
```

Resume from a conservative checkpointed stage when prior stage artifacts are still valid:

```bash
python3 orchestrator.py --project-brief Project_description.md --resume-from-stage "Worker generation"
```

Run the Codex self-healing supervisor instead if you want automatic failure capture, Codex-driven repair attempts, and automatic reruns:

```bash
python3 codex_supervisor.py --project-brief Project_description.md
```

Run only the preflight stage:

```bash
python3 orchestrator.py --dry-run-preflight --project-brief Project_description.md
```

Use the local bootstrap plan for repository self-validation without asking Codex to plan this repo:

```bash
python3 orchestrator.py --bootstrap-plan --project-brief Project_description.md
```

The legacy entrypoint [`multi_agent_workflow_deterministic_ver3_finance.py`](/home/postnl/multi-agent-producer_V0/Project_3_education/multi_agent_workflow_deterministic_ver3_finance.py) now forwards to the same orchestrator.

## Outputs

The orchestrator writes runtime state under `.orchestrator/`, including:

- `runtime_config.json`
- `context_analysis.json`
- `plan.json`
- `plan_validation.json`
- `reports/*.json`
- `manifests/*.json`
- `worker_tasks/*.json`
- `final_acceptance_summary.json`
- `checkpoints.json`

Editing workers run in isolated worktrees under `tmp/worktrees/`.

The self-healing supervisor writes its own state under `.self_heal/`, including:

- `attempts.jsonl`
- `run_logs/*.log`
- `repair_logs/*.json`
- `final_report.json`

## Notes

- The canonical asset directories are created up front:
  - `public/assets/backgrounds/`
  - `public/assets/sprites/`
  - `design/layout_refs/`
- Validation commands are offline-safe and reject install commands such as `npm install` and `npm ci`.
- The workflow treats [`Project_description.md`](/home/postnl/multi-agent-producer_V0/Project_3_education/Project_description.md) as the canonical brief and does not rely on hidden requirements.
- The supervisor uses `codex exec` as a bounded repair agent. It captures orchestrator failures, classifies them, limits the editable file set, applies up to a configured number of repair attempts, chooses a conservative `--resume-from-stage` value based on the repair scope, and reruns automatically.
# Project_5_education

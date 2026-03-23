#!/usr/bin/env python3
"""
Codex-driven self-healing supervisor for orchestrator.py.

This wrapper runs the orchestrator, captures failures, invokes `codex exec`
to patch bounded files, and retries until success or a configured hard stop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


ROOT = Path(__file__).resolve().parent
ORCHESTRATOR = ROOT / "orchestrator.py"
SELF_HEAL_DIR = ROOT / ".self_heal"
RUN_LOGS_DIR = SELF_HEAL_DIR / "run_logs"
REPAIR_LOGS_DIR = SELF_HEAL_DIR / "repair_logs"
SCHEMAS_DIR = SELF_HEAL_DIR / "schemas"
ATTEMPTS_JSONL = SELF_HEAL_DIR / "attempts.jsonl"
FINAL_REPORT_JSON = SELF_HEAL_DIR / "final_report.json"
DECISION_LOG = ROOT / ".orchestrator" / "decision_log.jsonl"
PLAN_JSON = ROOT / ".orchestrator" / "plan.json"
CHECKPOINTS_JSON = ROOT / ".orchestrator" / "checkpoints.json"
REPORTS_DIR = ROOT / ".orchestrator" / "reports"
ARTIFACT_VALIDATION_JSON = REPORTS_DIR / "artifact_validation.json"
BUILD_VALIDATION_JSON = REPORTS_DIR / "build_validation.json"
RUNTIME_VALIDATION_JSON = REPORTS_DIR / "runtime_validation.json"
PROMPT_V3 = ROOT / "Prompt_V3.md"
README_MD = ROOT / "README.md"

PINK_BOLD = "\033[1;95m"
RESET = "\033[0m"

MODEL = os.getenv("CODEX_MODEL", "gpt-5.1-codex")
SANDBOX = os.getenv("CODEX_SANDBOX", "workspace-write")
APPROVAL_POLICY = os.getenv("CODEX_APPROVAL_POLICY", "never")
CODEX_TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "1800"))
RUN_TIMEOUT_SECONDS = int(os.getenv("SUPERVISOR_RUN_TIMEOUT_SECONDS", "3600"))
MAX_LOG_CHARS = 12000
VERBOSE = False

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".next", ".venv", ".orchestrator", ".self_heal", "tmp"}


@dataclass
class ProcessResult:
    exit_code: int
    output: str
    duration_seconds: float


@dataclass
class RepairResult:
    final_status: str
    root_cause: str
    summary: str
    changed_files: List[str]
    verification: List[str]
    blockers: List[str]
    usage: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureDiagnosis:
    classifier: str
    summary: str
    hints: List[str] = field(default_factory=list)
    suspected_files: List[str] = field(default_factory=list)
    report_path: str = ""
    report_excerpt: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_step(message: str) -> None:
    print(f"{PINK_BOLD}{message}{RESET}", flush=True)


def log_verbose(message: str) -> None:
    if VERBOSE:
        log_step(message)


def log_json(title: str, payload: Any, limit: int = 4000) -> None:
    if not VERBOSE:
        return
    rendered = json.dumps(payload, indent=2, ensure_ascii=True, default=str)
    log_step(f"{title}:\n{tail_text(rendered, limit)}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def ensure_dirs() -> None:
    for path in (SELF_HEAL_DIR, RUN_LOGS_DIR, REPAIR_LOGS_DIR, SCHEMAS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def iter_workspace_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        yield path


def snapshot_workspace(root: Path) -> Dict[str, str]:
    snapshot: Dict[str, str] = {}
    for path in iter_workspace_files(root):
        rel = str(path.relative_to(root))
        try:
            snapshot[rel] = sha256_bytes(path.read_bytes())
        except FileNotFoundError:
            continue
    return snapshot


def diff_snapshots(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    changed: Set[str] = set()
    for rel in set(before) | set(after):
        if before.get(rel) != after.get(rel):
            changed.add(rel)
    return sorted(changed)


def build_orchestrator_command(args: argparse.Namespace) -> List[str]:
    command = [sys.executable, str(ORCHESTRATOR), "--project-brief", args.project_brief]
    if args.max_concurrency is not None:
        command.extend(["--max-concurrency", str(args.max_concurrency)])
    if args.bootstrap_plan:
        command.append("--bootstrap-plan")
    if args.dry_run_preflight:
        command.append("--dry-run-preflight")
    return command


def with_resume_stage(command: Sequence[str], resume_stage: Optional[str]) -> List[str]:
    updated = list(command)
    if resume_stage:
        updated.extend(["--resume-from-stage", resume_stage])
    return updated


def run_streaming(command: Sequence[str], timeout: int) -> ProcessResult:
    start = time.monotonic()
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_chunks: List[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_chunks.append(line)
        exit_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        output_chunks.append(f"\nSupervisor timeout after {timeout} seconds\n")
        exit_code = 124
    duration = time.monotonic() - start
    return ProcessResult(exit_code=exit_code, output="".join(output_chunks), duration_seconds=duration)


def tail_text(text: str, limit: int = MAX_LOG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def classify_failure(output: str) -> str:
    lower = output.lower()
    if "invalid_json_schema" in lower or "output-schema" in lower:
        return "schema_compatibility"
    if "already registered worktree" in lower or "prunable gitdir" in lower or "worktree" in lower and "registered" in lower:
        return "stale_worktree"
    if "worker dependency deadlock" in lower:
        return "dependency_deadlock"
    if "policy violation" in lower or "unexpected deletions" in lower or "required output missing" in lower:
        return "filesystem_policy"
    if "stage 7/10: artifact validation" in lower or "artifact validation failure" in lower:
        return "artifact_validation"
    if "stage 8/10: build validation" in lower or "build validation" in lower:
        return "build_validation"
    if "stage 9/10: runtime validation" in lower or "runtime validation" in lower:
        return "runtime_validation"
    if "codex exec failed" in lower or "turn.failed" in lower or "invalid_request_error" in lower:
        return "codex_exec_failure"
    return "unknown"


def load_recent_decisions(limit: int = 20) -> str:
    if not DECISION_LOG.exists():
        return ""
    lines = DECISION_LOG.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-limit:])


def run_capture(command: Sequence[str]) -> str:
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.stdout.strip()


def load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def report_path_for_classifier(classifier: str) -> Optional[Path]:
    if classifier == "artifact_validation":
        return ARTIFACT_VALIDATION_JSON
    if classifier == "build_validation":
        return BUILD_VALIDATION_JSON
    if classifier == "runtime_validation":
        return RUNTIME_VALIDATION_JSON
    return None


def extract_paths_from_text(text: str) -> List[str]:
    candidates: Set[str] = set()
    for match in re.findall(r"`([^`\n]+?\.[A-Za-z0-9]+)(?::\d+(?::\d+)?)?`", text):
        if "/" in match:
            candidates.add(match.strip())
    for match in re.findall(r"([A-Za-z0-9_./()\-\[\]]+\.[A-Za-z0-9]+)(?::\d+(?::\d+)?)?", text):
        if "/" in match and not match.startswith("./"):
            candidates.add(match.strip())
    return sorted(candidates)


def summarize_validation_report(classifier: str, report: Dict[str, Any]) -> FailureDiagnosis:
    diagnosis = FailureDiagnosis(classifier=classifier, summary=f"Failure class: {classifier}")
    report_path = report_path_for_classifier(classifier)
    if report_path:
        diagnosis.report_path = str(report_path.relative_to(ROOT))
    known_plan_paths = load_plan_paths()

    if classifier == "artifact_validation":
        local_report = report.get("local_report", {})
        agent_report = report.get("agent_report", {})
        summary = str(agent_report.get("summary") or "").strip()
        if summary:
            diagnosis.summary = summary
        findings = agent_report.get("findings", [])
        hints: List[str] = []
        suspected_files: Set[str] = set(agent_report.get("checked_files", []))
        for finding in findings[:6]:
            if not isinstance(finding, dict):
                continue
            message = str(finding.get("message") or "").strip()
            source_files = finding.get("source_files", [])
            if message:
                hints.append(message)
                suspected_files.update(extract_paths_from_text(message))
            if isinstance(source_files, list):
                suspected_files.update(str(item) for item in source_files if isinstance(item, str) and item.strip())
        missing = local_report.get("missing", [])
        if isinstance(missing, list) and missing:
            hints.extend(f"Missing required artifact: {item}" for item in missing[:6] if isinstance(item, str))
            suspected_files.update(str(item) for item in missing if isinstance(item, str))
        diagnosis.hints = hints
        diagnosis.suspected_files = sorted(
            path
            for path in suspected_files
            if isinstance(path, str)
            and path.strip()
            and ((ROOT / path).exists() or path in known_plan_paths)
        )
        diagnosis.report_excerpt = json.dumps(
            {
                "local_report": local_report,
                "agent_report": {
                    "status": agent_report.get("status"),
                    "summary": agent_report.get("summary"),
                    "checked_files": agent_report.get("checked_files", []),
                    "findings": findings[:6],
                },
            },
            indent=2,
        )
        return diagnosis

    if report:
        diagnosis.summary = f"{classifier} failed; inspect persisted validation report."
        diagnosis.report_excerpt = json.dumps(report, indent=2)[:6000]
    return diagnosis


def load_plan_paths() -> Set[str]:
    paths: Set[str] = set()
    if not PLAN_JSON.exists():
        return paths
    try:
        plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return paths
    for task in plan.get("worker_tasks", []):
        for field in ("owned_paths", "required_outputs", "contracts"):
            for item in task.get(field, []):
                if isinstance(item, str) and item.strip():
                    paths.add(item)
    for field in ("contracts",):
        for item in plan.get(field, []):
            if isinstance(item, str) and item.strip() and "/" in item:
                paths.add(item)
    return paths


def load_plan_payload() -> Dict[str, Any]:
    if not PLAN_JSON.exists():
        return {}
    try:
        data = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_created_outside_allowlist(output: str) -> List[str]:
    matches = re.findall(r"Created outside allowlist: ([^;\n]+)", output)
    return [item.strip() for item in matches if item.strip()]


def find_owner_for_path(plan_payload: Dict[str, Any], rel_path: str) -> Optional[str]:
    for task in plan_payload.get("worker_tasks", []):
        if rel_path in task.get("owned_paths", []):
            return str(task.get("role", ""))
    return None


def diagnose_failure(classifier: str, output: str) -> FailureDiagnosis:
    report_path = report_path_for_classifier(classifier)
    if report_path and report_path.exists():
        report_diagnosis = summarize_validation_report(classifier, load_json_file(report_path))
        if report_diagnosis.hints or report_diagnosis.summary != f"Failure class: {classifier}":
            return report_diagnosis

    diagnosis = FailureDiagnosis(classifier=classifier, summary=f"Failure class: {classifier}")
    if classifier != "filesystem_policy":
        return diagnosis

    created_paths = extract_created_outside_allowlist(output)
    if not created_paths:
        diagnosis.summary = "Filesystem policy failure without explicit created-path details"
        return diagnosis

    plan_payload = load_plan_payload()
    owned_matches = [path for path in created_paths if find_owner_for_path(plan_payload, path)]
    bracket_paths = [path for path in owned_matches if "[" in path and "]" in path]

    if bracket_paths and len(owned_matches) == len(created_paths):
        diagnosis.classifier = "filesystem_policy_bracket_path_mismatch"
        diagnosis.summary = "Created files are already owned by the worker, and bracketed Next.js route segments likely failed literal path matching."
        diagnosis.hints = [
            "Inspect allowlist/path matching before changing the plan or worker prompts.",
            "Treat Next.js dynamic route paths containing [segment] as literal path text, not glob character classes.",
            "Prefer fixing the orchestrator matcher over broadening worker ownership.",
        ]
        diagnosis.suspected_files = sorted(set([ORCHESTRATOR.name, *bracket_paths]))
        return diagnosis

    if owned_matches and len(owned_matches) == len(created_paths):
        diagnosis.classifier = "filesystem_policy_owned_path_mismatch"
        diagnosis.summary = "Created files are already listed in worker owned_paths, so policy matching or path normalization is likely wrong."
        diagnosis.hints = [
            "Compare created file paths with worker owned_paths before editing the plan.",
            "Inspect orchestrator allowlist and path normalization logic.",
        ]
        diagnosis.suspected_files = sorted(set([ORCHESTRATOR.name, *owned_matches]))
        return diagnosis

    diagnosis.summary = "Filesystem policy failure appears to involve paths not fully covered by owned_paths."
    diagnosis.hints = [
        "Compare worker created files against owned_paths and required_outputs.",
        "Only expand ownership if the files are truly missing from the plan.",
    ]
    diagnosis.suspected_files = sorted(set(created_paths))
    return diagnosis


def allowed_files_for_failure(classifier: str, diagnosis: Optional[FailureDiagnosis] = None) -> List[str]:
    base = {
        ORCHESTRATOR.name,
        Path(__file__).name,
        README_MD.name,
        PROMPT_V3.name,
    }
    plan_paths = load_plan_paths()
    if classifier in {"artifact_validation", "build_validation", "runtime_validation", "filesystem_policy", "unknown", "codex_exec_failure"}:
        base.update(plan_paths)
    if diagnosis:
        base.update(diagnosis.suspected_files)
        if diagnosis.classifier in {"filesystem_policy_bracket_path_mismatch", "filesystem_policy_owned_path_mismatch"}:
            base = {item for item in base if item in {ORCHESTRATOR.name, Path(__file__).name, PROMPT_V3.name, README_MD.name} or item in diagnosis.suspected_files}
    return sorted(base)


def repair_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["final_status", "root_cause", "summary", "changed_files", "verification", "blockers"],
        "properties": {
            "final_status": {"type": "string", "enum": ["completed", "blocked"]},
            "root_cause": {"type": "string", "minLength": 3},
            "summary": {"type": "string", "minLength": 3},
            "changed_files": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "verification": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "blockers": {"type": "array", "items": {"type": "string", "minLength": 1}},
        },
    }


def write_schema() -> Path:
    path = SCHEMAS_DIR / "repair_result.json"
    write_text(path, json.dumps(repair_schema(), indent=2))
    return path


def build_repair_prompt(
    attempt: int,
    classifier: str,
    diagnosis: FailureDiagnosis,
    orchestrator_command: Sequence[str],
    failure_output: str,
    allowed_files: Sequence[str],
) -> str:
    decision_tail = load_recent_decisions()
    worktree_state = run_capture(["git", "worktree", "list", "--porcelain"])
    git_status = run_capture(["git", "status", "--short"])
    plan_hint = PLAN_JSON.read_text(encoding="utf-8")[:4000] if PLAN_JSON.exists() else ""
    validation_report_block = ""
    if diagnosis.report_path:
        validation_report_block = textwrap.dedent(
            f"""

            Persisted validation report:
            Path: {diagnosis.report_path}
            ```json
            {tail_text(diagnosis.report_excerpt, 7000)}
            ```
            """
        ).rstrip()
    return textwrap.dedent(
        f"""\
        You are a bounded repair agent for a failing Codex-only orchestration repository.

        Goal:
        Make this command succeed on the next rerun without broad refactors:
        {' '.join(orchestrator_command)}

        Repair attempt: {attempt}
        Failure class: {classifier}
        Local pre-diagnosis:
        {diagnosis.summary}

        Editable files only:
        {json.dumps(list(allowed_files), indent=2)}

        Hard constraints:
        - Do not edit files outside the allowed list.
        - Do not use network access or package installation commands.
        - Prefer the smallest durable fix for the current root cause.
        - Preserve the explicit staged workflow design.
        - If the fix requires prompt hardening for future runs, you may edit `Prompt_V3.md` if it is in the allowed list.
        - Run lightweight local verification after editing if possible.
        - Return only JSON matching the provided schema.
        - Treat the local pre-diagnosis and any persisted validation report as strong evidence unless the code clearly disproves them.
        - Prefer fixing files explicitly cited by the validator before making speculative changes elsewhere.

        Local repair hints:
        {json.dumps(diagnosis.hints, indent=2)}

        Recent combined orchestrator output:
        ```text
        {tail_text(failure_output)}
        ```

        Recent decision log tail:
        ```jsonl
        {tail_text(decision_tail, 4000)}
        ```

        Current git worktree state:
        ```text
        {tail_text(worktree_state, 3000)}
        ```

        Current git status:
        ```text
        {tail_text(git_status, 3000)}
        ```

        Current plan excerpt if present:
        ```json
        {tail_text(plan_hint, 4000)}
        ```
        {validation_report_block}
        """
    ).strip()


def run_codex_repair(prompt: str, schema_path: Path, timeout: int) -> RepairResult:
    command = [
        "codex",
        "exec",
        "--json",
        "--model",
        MODEL,
        "--sandbox",
        SANDBOX,
        "--config",
        f'approval_policy="{APPROVAL_POLICY}"',
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
    ]
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    final_text = ""
    usage: Dict[str, Any] = {}
    error_messages: List[str] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final_text = item.get("text", "")
        elif event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
        elif event.get("type") in {"error", "turn.failed"}:
            message = event.get("message") or event.get("error", {}).get("message") or line
            error_messages.append(str(message))
    if proc.returncode != 0:
        details = " | ".join(part for part in [proc.stderr.strip(), " || ".join(error_messages).strip()] if part)
        raise RuntimeError(f"codex repair failed ({proc.returncode}): {details}")
    payload = json.loads(final_text)
    log_verbose(f"Codex repair usage: {json.dumps(usage, ensure_ascii=True)}")
    return RepairResult(
        final_status=payload["final_status"],
        root_cause=payload["root_cause"],
        summary=payload["summary"],
        changed_files=payload["changed_files"],
        verification=payload["verification"],
        blockers=payload["blockers"],
        usage=usage,
    )


def verify_python_files() -> List[str]:
    candidates = [str(path.relative_to(ROOT)) for path in ROOT.glob("*.py")]
    if not candidates:
        return []
    subprocess.run([sys.executable, "-m", "py_compile", *candidates], cwd=str(ROOT), check=False)
    return [f"{sys.executable} -m py_compile {' '.join(candidates)}"]


def fingerprint_failure(classifier: str, output: str) -> str:
    normalized = classifier + "\n" + tail_text(output, 4000)
    return sha256_bytes(normalized.encode("utf-8"))


def choose_resume_stage(changed_files: Sequence[str], diagnosis: FailureDiagnosis) -> Optional[str]:
    changed = set(changed_files)
    if not changed:
        return None
    if changed <= {"README.md"}:
        return "Final acceptance summary"
    if changed & {"orchestrator.py"}:
        if diagnosis.classifier in {
            "stale_worktree",
            "dependency_deadlock",
            "filesystem_policy",
            "filesystem_policy_bracket_path_mismatch",
            "filesystem_policy_owned_path_mismatch",
        }:
            return "Worker generation"
        if diagnosis.classifier in {"build_validation", "runtime_validation", "artifact_validation"}:
            return "Artifact validation"
        if diagnosis.classifier in {"schema_compatibility", "codex_exec_failure"}:
            return "Context analysis"
        return "Planner generation"
    if changed & {"Prompt_V3.md"}:
        return "Planner generation"
    if any(path.startswith(".orchestrator/") for path in changed):
        return "Planner generation"
    if any(path.startswith(("app/", "components/", "lib/", "styles/", "scripts/", "db/", "docs/", "hooks/", "data/")) for path in changed):
        if diagnosis.classifier in {"build_validation", "runtime_validation", "artifact_validation"}:
            return "Artifact validation"
        return "Worker generation"
    if any(path.endswith((".json", ".ts", ".tsx", ".js", ".jsx", ".sql", ".css", ".md")) for path in changed):
        return "Worker generation"
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex self-healing supervisor for orchestrator.py")
    parser.add_argument("--project-brief", default="Project_description.md", help="Path to Project_description.md")
    parser.add_argument("--max-concurrency", type=int, default=None, help="Forwarded to orchestrator.py")
    parser.add_argument("--bootstrap-plan", action="store_true", help="Forwarded to orchestrator.py")
    parser.add_argument("--dry-run-preflight", action="store_true", help="Forwarded to orchestrator.py")
    parser.add_argument("--max-heal-attempts", type=int, default=3, help="Maximum Codex repair attempts after a failed orchestrator run")
    parser.add_argument("--run-timeout", type=int, default=RUN_TIMEOUT_SECONDS, help="Timeout in seconds for each orchestrator run")
    parser.add_argument("--repair-timeout", type=int, default=CODEX_TIMEOUT_SECONDS, help="Timeout in seconds for each Codex repair call")
    parser.add_argument("--verbose", action="store_true", help="Print detailed diagnosis, repair-scope, and resume reasoning")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    global VERBOSE
    VERBOSE = args.verbose
    ensure_dirs()
    schema_path = write_schema()
    orchestrator_command = build_orchestrator_command(args)
    next_resume_stage: Optional[str] = None
    seen_fingerprints: Dict[str, int] = {}

    log_verbose(f"Supervisor configuration: model={MODEL}, sandbox={SANDBOX}, approval_policy={APPROVAL_POLICY}, run_timeout={args.run_timeout}, repair_timeout={args.repair_timeout}")
    log_verbose(f"Orchestrator base command: {' '.join(orchestrator_command)}")

    for run_attempt in range(1, args.max_heal_attempts + 2):
        command_for_run = with_resume_stage(orchestrator_command, next_resume_stage)
        log_step(f"Supervisor run attempt {run_attempt}: {' '.join(command_for_run)}")
        if next_resume_stage:
            log_verbose(f"Resuming from stage selected by previous repair: {next_resume_stage}")
        result = run_streaming(command_for_run, timeout=args.run_timeout)
        run_log_path = RUN_LOGS_DIR / f"run_attempt_{run_attempt:02d}.log"
        write_text(run_log_path, result.output)
        append_jsonl(ATTEMPTS_JSONL, {
            "timestamp": utc_now(),
            "type": "orchestrator_run",
            "attempt": run_attempt,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "resume_from_stage": next_resume_stage,
            "log_path": str(run_log_path.relative_to(ROOT)),
        })
        if result.exit_code == 0:
            report = {
                "status": "completed",
                "attempts": run_attempt,
                "command": command_for_run,
                "final_log": str(run_log_path.relative_to(ROOT)),
            }
            write_text(FINAL_REPORT_JSON, json.dumps(report, indent=2))
            log_step("Supervisor completed successfully")
            return 0

        classifier = classify_failure(result.output)
        diagnosis = diagnose_failure(classifier, result.output)
        fingerprint = fingerprint_failure(diagnosis.classifier, result.output)
        seen_fingerprints[fingerprint] = seen_fingerprints.get(fingerprint, 0) + 1
        log_verbose(f"Failure classified as: {classifier}")
        log_json("Failure diagnosis", asdict(diagnosis), limit=7000)
        log_verbose(f"Failure fingerprint occurrence count: {seen_fingerprints[fingerprint]}")
        if run_attempt > args.max_heal_attempts or seen_fingerprints[fingerprint] > 2:
            report = {
                "status": "blocked",
                "attempts": run_attempt,
                "failure_class": diagnosis.classifier,
                "reason": "maximum repair attempts reached" if run_attempt > args.max_heal_attempts else "repeated failure fingerprint",
                "final_log": str(run_log_path.relative_to(ROOT)),
                "diagnosis": asdict(diagnosis),
            }
            write_text(FINAL_REPORT_JSON, json.dumps(report, indent=2))
            return result.exit_code or 1

        append_jsonl(ATTEMPTS_JSONL, {
            "timestamp": utc_now(),
            "type": "failure_diagnosis",
            "attempt": run_attempt,
            "failure_class": classifier,
            "diagnosis": asdict(diagnosis),
        })
        allowed_files = allowed_files_for_failure(classifier, diagnosis)
        log_json("Allowed editable files", allowed_files, limit=7000)
        before = snapshot_workspace(ROOT)
        prompt = build_repair_prompt(run_attempt, diagnosis.classifier, diagnosis, command_for_run, result.output, allowed_files)
        log_verbose(f"Repair prompt length: {len(prompt)} characters")
        if diagnosis.report_path:
            log_verbose(f"Repair prompt includes persisted validation report: {diagnosis.report_path}")
        repair = run_codex_repair(prompt, schema_path, timeout=args.repair_timeout)
        log_json("Repair result", asdict(repair), limit=7000)
        verify_python_files()
        after = snapshot_workspace(ROOT)
        changed_files = diff_snapshots(before, after)
        disallowed_changes = sorted(path for path in changed_files if path not in allowed_files)
        next_resume_stage = choose_resume_stage(changed_files, diagnosis)
        log_json("Detected changed files", changed_files)
        if disallowed_changes:
            log_json("Disallowed changes", disallowed_changes)
        log_verbose(f"Selected next resume stage: {next_resume_stage or 'Stage 1'}")
        repair_log_payload = {
            "timestamp": utc_now(),
            "type": "repair_attempt",
            "attempt": run_attempt,
            "failure_class": diagnosis.classifier,
            "allowed_files": allowed_files,
            "diagnosis": asdict(diagnosis),
            "repair_result": asdict(repair),
            "detected_changed_files": changed_files,
            "disallowed_changes": disallowed_changes,
            "next_resume_stage": next_resume_stage,
        }
        repair_log_path = REPAIR_LOGS_DIR / f"repair_attempt_{run_attempt:02d}.json"
        write_text(repair_log_path, json.dumps(repair_log_payload, indent=2))
        append_jsonl(ATTEMPTS_JSONL, {
            "timestamp": utc_now(),
            "type": "repair_attempt",
            "attempt": run_attempt,
            "failure_class": diagnosis.classifier,
            "repair_log_path": str(repair_log_path.relative_to(ROOT)),
            "final_status": repair.final_status,
            "detected_changed_files": changed_files,
            "next_resume_stage": next_resume_stage,
        })
        if disallowed_changes:
            report = {
                "status": "blocked",
                "attempts": run_attempt,
                "failure_class": diagnosis.classifier,
                "reason": "repair edited files outside the allowed set",
                "repair_log": str(repair_log_path.relative_to(ROOT)),
                "disallowed_changes": disallowed_changes,
                "diagnosis": asdict(diagnosis),
            }
            write_text(FINAL_REPORT_JSON, json.dumps(report, indent=2))
            return 1
        if repair.final_status != "completed" and not changed_files:
            report = {
                "status": "blocked",
                "attempts": run_attempt,
                "failure_class": diagnosis.classifier,
                "reason": "repair agent reported blocked without changing files",
                "repair_log": str(repair_log_path.relative_to(ROOT)),
                "diagnosis": asdict(diagnosis),
            }
            write_text(FINAL_REPORT_JSON, json.dumps(report, indent=2))
            return 1
        if next_resume_stage:
            log_step(f"Repair attempt {run_attempt} complete; rerunning orchestrator from {next_resume_stage}")
        else:
            log_step(f"Repair attempt {run_attempt} complete; rerunning orchestrator from Stage 1")

    return 1


if __name__ == "__main__":
    sys.exit(main())

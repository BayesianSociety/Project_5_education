#!/usr/bin/env python3
"""
Production-oriented Codex-only multi-agent orchestrator.

This workflow:
- reads Project_description.md in full before development work starts
- uses `codex exec` for role execution
- keeps stages explicit and phase-based
- bounds concurrency for editing workers
- isolates editing workers in git worktrees
- validates plans through a typed schema and targeted repair loop
- snapshots the filesystem with SHA-256 manifests
- enforces per-step filesystem allowlists
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ROOT = Path.cwd()
DEFAULT_BRIEF = ROOT / "Project_description.md"
ORCH_DIR = ROOT / ".orchestrator"
SCHEMAS_DIR = ORCH_DIR / "schemas"
MANIFESTS_DIR = ORCH_DIR / "manifests"
REPORTS_DIR = ORCH_DIR / "reports"
TASKS_DIR = ORCH_DIR / "worker_tasks"
WORKTREES_DIR = ROOT / "tmp" / "worktrees"
DECISION_LOG = ORCH_DIR / "decision_log.jsonl"
RUNTIME_CONFIG_JSON = ORCH_DIR / "runtime_config.json"
CONTEXT_ANALYSIS_JSON = ORCH_DIR / "context_analysis.json"
PLAN_JSON = ORCH_DIR / "plan.json"
PLAN_VALIDATION_JSON = ORCH_DIR / "plan_validation.json"
FINAL_SUMMARY_JSON = ORCH_DIR / "final_acceptance_summary.json"
CHECKPOINTS_JSON = ORCH_DIR / "checkpoints.json"
README_MD = ROOT / "README.md"
WORKER_RESULTS_JSON = REPORTS_DIR / "worker_results.json"
ARTIFACT_VALIDATION_JSON = REPORTS_DIR / "artifact_validation.json"
BUILD_VALIDATION_JSON = REPORTS_DIR / "build_validation.json"
RUNTIME_VALIDATION_JSON = REPORTS_DIR / "runtime_validation.json"

PINK_BOLD = "\033[1;95m"
RESET = "\033[0m"

MODEL = os.getenv("CODEX_MODEL", "gpt-5.1-codex")
SANDBOX = os.getenv("CODEX_SANDBOX", "workspace-write")
APPROVAL_POLICY = os.getenv("CODEX_APPROVAL_POLICY", "never")
CODEX_TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "1800"))
MAX_JSON_LINE = 8 * 1024 * 1024
MAX_REPAIR_ATTEMPTS = 2
RETRYABLE_RUNTIME_PATTERNS = (
    "broken pipe",
    "connection reset",
    "transport closed",
    "unexpected eof",
    "timed out",
    "json decode",
    "stream ended unexpectedly",
)
BANNED_INSTALL_PATTERNS = (
    "npm install",
    "npm ci",
    "pnpm install",
    "yarn install",
    "bun install",
)
REQUIRED_STAGE_NAMES = [
    "Environment preflight",
    "Context analysis",
    "Planner generation",
    "Planner schema validation",
    "Planner repair loop if needed",
    "Worker generation",
    "Artifact validation",
    "Build validation",
    "Runtime validation",
    "Final acceptance summary",
]
STAGE_NAME_TO_INDEX = {name: idx for idx, name in enumerate(REQUIRED_STAGE_NAMES, start=1)}
STAGE_SLUGS = {re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"): idx for idx, name in enumerate(REQUIRED_STAGE_NAMES, start=1)}
REQUIRED_ROLE_NAMES = [
    "Orchestrator",
    "Context Analyst",
    "Architect",
    "Backend Producer",
    "Frontend Producer",
    "Verification Agent",
]
EDITING_ROLES = {"Backend Producer", "Frontend Producer"}
CANONICAL_ASSET_DIRS = [
    ROOT / "public" / "assets" / "backgrounds",
    ROOT / "public" / "assets" / "sprites",
    ROOT / "design" / "layout_refs",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_step(message: str) -> None:
    print(f"{PINK_BOLD}{message}{RESET}", flush=True)


def ensure_dirs() -> None:
    for path in [ORCH_DIR, SCHEMAS_DIR, MANIFESTS_DIR, REPORTS_DIR, TASKS_DIR, WORKTREES_DIR, *CANONICAL_ASSET_DIRS]:
        path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_workspace_files(root: Path) -> Iterable[Path]:
    excluded = {".git", "node_modules", "__pycache__", ".next", ".venv"}
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in excluded for part in path.parts):
            continue
        yield path


def snapshot_workspace(root: Path) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for path in iter_workspace_files(root):
        rel = str(path.relative_to(root))
        try:
            snapshot[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
        except FileNotFoundError:
            continue
    return snapshot


def diff_snapshots(before: Dict[str, Dict[str, Any]], after: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    before_keys = set(before)
    after_keys = set(after)
    modified = [key for key in sorted(before_keys & after_keys) if before[key]["sha256"] != after[key]["sha256"]]
    return {
        "created": sorted(after_keys - before_keys),
        "modified": modified,
        "deleted": sorted(before_keys - after_keys),
    }


def matches_any_glob(rel_path: str, globs: Sequence[str]) -> bool:
    """Return True if rel_path matches glob or resides under a listed directory."""
    for pattern in globs:
        normalized = pattern.rstrip("/")
        # Treat exact path matches literally before considering glob syntax.
        if rel_path == pattern:
            return True
        if normalized and rel_path.startswith(f"{normalized}/"):
            return True
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # Treat plain paths (no wildcard metacharacters) as directory roots.
        if not any(ch in pattern for ch in "*?"):
            if not normalized:
                continue
            if rel_path == normalized:
                return True
    return False


@dataclass(frozen=True)
class StepPolicy:
    name: str
    allowed_create_globs: Tuple[str, ...]
    allowed_modify_globs: Tuple[str, ...]
    forbidden_globs: Tuple[str, ...] = ()
    frozen_inputs: Tuple[str, ...] = ()
    required_outputs: Tuple[str, ...] = ()
    allow_delete: bool = False


def enforce_policy(before: Dict[str, Dict[str, Any]], after: Dict[str, Dict[str, Any]], policy: StepPolicy) -> Dict[str, List[str]]:
    diff = diff_snapshots(before, after)
    violations: List[str] = []

    if diff["deleted"] and not policy.allow_delete:
        violations.append(f"Unexpected deletions: {diff['deleted'][:20]}")

    for rel in diff["created"]:
        if matches_any_glob(rel, policy.forbidden_globs):
            violations.append(f"Created forbidden path: {rel}")
        elif not matches_any_glob(rel, policy.allowed_create_globs):
            violations.append(f"Created outside allowlist: {rel}")

    for rel in diff["modified"]:
        if matches_any_glob(rel, policy.forbidden_globs):
            violations.append(f"Modified forbidden path: {rel}")
        elif not matches_any_glob(rel, policy.allowed_modify_globs):
            violations.append(f"Modified outside allowlist: {rel}")

    for rel in policy.frozen_inputs:
        if rel in diff["modified"]:
            violations.append(f"Modified frozen input: {rel}")

    for rel in policy.required_outputs:
        if rel not in after:
            violations.append(f"Required output missing: {rel}")

    if violations:
        raise RuntimeError(f"[{policy.name}] policy violation(s): " + "; ".join(violations))

    return diff


def write_manifest(stage_index: int, stage_name: str, note: str, root: Path = ROOT) -> Path:
    snapshot = snapshot_workspace(root)
    payload = {
        "stage_index": stage_index,
        "stage_name": stage_name,
        "note": note,
        "generated_at": utc_now(),
        "workspace_root": str(root),
        "snapshot_sha256": sha256_bytes(json.dumps(snapshot, sort_keys=True).encode("utf-8")),
        "files": snapshot,
    }
    path = MANIFESTS_DIR / f"{stage_index:02d}_{slugify(stage_name)}.json"
    write_text(path, json.dumps(payload, indent=2))
    return path


def load_json_file(path: Path) -> Dict[str, Any]:
    return load_json(read_text(path))


def load_json_list_file(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(read_text(path))
    if not isinstance(data, list):
        raise RuntimeError(f"Expected JSON list in {path}")
    return data


def checkpoint_artifacts(stage_index: int) -> List[Path]:
    mapping = {
        1: [REPORTS_DIR / "environment_preflight.json"],
        2: [CONTEXT_ANALYSIS_JSON],
        3: [PLAN_JSON],
        4: [PLAN_VALIDATION_JSON],
        5: [PLAN_VALIDATION_JSON],
        6: [WORKER_RESULTS_JSON],
        7: [ARTIFACT_VALIDATION_JSON],
        8: [BUILD_VALIDATION_JSON],
        9: [RUNTIME_VALIDATION_JSON],
        10: [FINAL_SUMMARY_JSON],
    }
    return mapping[stage_index]


def load_checkpoints() -> Dict[str, Any]:
    if not CHECKPOINTS_JSON.exists():
        return {}
    try:
        data = json.loads(read_text(CHECKPOINTS_JSON))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid checkpoint file: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Checkpoint file must be a JSON object")
    return data


def write_checkpoint(stage_index: int, stage_name: str, note: str, project_brief_path: Path) -> None:
    checkpoints = load_checkpoints()
    artifacts = checkpoint_artifacts(stage_index)
    payload = {
        "stage_index": stage_index,
        "stage_name": stage_name,
        "note": note,
        "completed_at": utc_now(),
        "project_brief_path": str(project_brief_path.relative_to(ROOT)),
        "project_brief_sha256": sha256_file(project_brief_path),
        "orchestrator_sha256": sha256_file(Path(__file__)),
        "artifacts": [str(path.relative_to(ROOT)) for path in artifacts if path.exists()],
    }
    checkpoints[str(stage_index)] = payload
    write_text(CHECKPOINTS_JSON, json.dumps(checkpoints, indent=2))


def parse_resume_stage(value: Optional[str]) -> int:
    if not value:
        return 1
    raw = value.strip()
    if not raw:
        return 1
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(REQUIRED_STAGE_NAMES):
            return index
    if raw in REQUIRED_STAGE_NAMES:
        return STAGE_NAME_TO_INDEX[raw]
    normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    if normalized in STAGE_SLUGS:
        return STAGE_SLUGS[normalized]
    raise RuntimeError(f"Unknown resume stage: {value}")


def ensure_resume_prerequisites(resume_stage_index: int, project_brief_path: Path) -> None:
    checkpoints = load_checkpoints()
    current_brief_sha = sha256_file(project_brief_path)
    for stage_index in range(1, resume_stage_index):
        checkpoint = checkpoints.get(str(stage_index))
        if not checkpoint:
            raise RuntimeError(f"Cannot resume from stage {resume_stage_index}: missing checkpoint for stage {stage_index}")
        if checkpoint.get("project_brief_sha256") != current_brief_sha:
            raise RuntimeError(f"Cannot resume from stage {resume_stage_index}: project brief changed since stage {stage_index}")
        for rel_path in checkpoint.get("artifacts", []):
            artifact_path = ROOT / rel_path
            if not artifact_path.exists():
                raise RuntimeError(f"Cannot resume from stage {resume_stage_index}: missing artifact {rel_path} from stage {stage_index}")


def load_worker_results_report() -> List[WorkerResult]:
    payload = load_json_list_file(WORKER_RESULTS_JSON)
    return [WorkerResult(**item) for item in payload]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def repo_file_listing(limit: int = 300) -> List[str]:
    paths = sorted(str(path.relative_to(ROOT)) for path in iter_workspace_files(ROOT))
    return paths[:limit]


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required command not found: {name}")
    return path


async def run_command(args: Sequence[str], cwd: Path = ROOT, timeout: int = 120) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Timed out running command: {' '.join(shlex.quote(part) for part in args)}")
    return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


@dataclass
class CodexRunResult:
    final_text: str
    usage: Dict[str, Any]
    events_seen: int
    stderr: str
    returncode: int


async def run_codex(prompt: str, *, cwd: Path, schema_path: Optional[Path] = None, timeout: Optional[int] = None) -> CodexRunResult:
    command = [
        "codex",
        "exec",
        "--experimental-json",
        "--model",
        MODEL,
        "--sandbox",
        SANDBOX,
        "--config",
        f'approval_policy="{APPROVAL_POLICY}"',
        "--skip-git-repo-check",
    ]
    if schema_path:
        command.extend(["--output-schema", str(schema_path)])

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=MAX_JSON_LINE,
        env=os.environ.copy(),
    )

    assert proc.stdin is not None
    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    final_text = ""
    usage: Dict[str, Any] = {}
    events_seen = 0
    error_messages: List[str] = []
    stderr_chunks: List[str] = []

    async def consume_stdout() -> None:
        nonlocal final_text, usage, events_seen
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            events_seen += 1
            event = json.loads(decoded)
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                final_text = item.get("text", "")
            elif event.get("type") == "turn.completed":
                usage = event.get("usage") or {}
            elif event.get("type") in {"error", "turn.failed"}:
                message = event.get("message") or event.get("error", {}).get("message") or decoded
                error_messages.append(str(message).strip())

    async def consume_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk.decode("utf-8", errors="replace"))

    tasks = [asyncio.create_task(consume_stdout()), asyncio.create_task(consume_stderr())]
    timeout = timeout or CODEX_TIMEOUT_SECONDS

    try:
        returncode = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise RuntimeError(f"codex exec timed out after {timeout} seconds")

    await asyncio.gather(*tasks, return_exceptions=True)
    stderr_text = "".join(stderr_chunks)
    if returncode != 0:
        details = " | ".join(part for part in [stderr_text.strip(), " || ".join(error_messages).strip()] if part)
        raise RuntimeError(f"codex exec failed ({returncode}): {details}")

    return CodexRunResult(
        final_text=final_text,
        usage=usage,
        events_seen=events_seen,
        stderr=stderr_text,
        returncode=returncode,
    )


def classify_failure(exc: Exception) -> str:
    text = str(exc).lower()
    if any(pattern in text for pattern in RETRYABLE_RUNTIME_PATTERNS):
        return "retryable_infrastructure"
    return "task_failure"


def load_json(text: str) -> Dict[str, Any]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("Expected a JSON object")
    return data


def write_schema(name: str, schema: Dict[str, Any]) -> Path:
    path = SCHEMAS_DIR / f"{name}.json"
    write_text(path, json.dumps(schema, indent=2))
    return path


def narrow_string_schema(min_length: int = 1) -> Dict[str, Any]:
    return {"type": "string", "minLength": min_length}


def context_analysis_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "project_brief_path",
            "domain",
            "constraints",
            "success_criteria",
            "expected_outputs",
            "stack_requirements",
            "validation_expectations",
            "repo_constraints",
            "missing_information",
            "assumptions",
        ],
        "properties": {
            "project_brief_path": {"type": "string", "const": "Project_description.md"},
            "domain": narrow_string_schema(10),
            "constraints": {"type": "array", "items": narrow_string_schema(3), "minItems": 5},
            "success_criteria": {"type": "array", "items": narrow_string_schema(3), "minItems": 5},
            "expected_outputs": {"type": "array", "items": narrow_string_schema(3), "minItems": 5},
            "stack_requirements": {"type": "array", "items": narrow_string_schema(3), "minItems": 3},
            "validation_expectations": {"type": "array", "items": narrow_string_schema(3), "minItems": 4},
            "repo_constraints": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "missing_information": {"type": "array", "items": narrow_string_schema(3)},
            "assumptions": {"type": "array", "items": narrow_string_schema(3)},
        },
    }


def worker_task_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "role",
            "summary",
            "owned_paths",
            "required_outputs",
            "read_only_inputs",
            "forbidden_paths",
            "dependencies",
            "contracts",
            "validation_rules",
        ],
        "properties": {
            "role": {"enum": ["Backend Producer", "Frontend Producer"]},
            "summary": narrow_string_schema(10),
            "owned_paths": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "required_outputs": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "read_only_inputs": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "forbidden_paths": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "dependencies": {"type": "array", "items": narrow_string_schema(3)},
            "contracts": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "validation_rules": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "kind", "target", "expectation"],
                    "properties": {
                        "name": narrow_string_schema(3),
                        "kind": {"enum": ["file_exists", "contains_text", "json_parse", "route_contract", "sqlite_artifact", "offline_command"]},
                        "target": narrow_string_schema(3),
                        "expectation": narrow_string_schema(3),
                    },
                },
            },
        },
    }


def plan_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "task_summary",
            "project_brief_path",
            "stages",
            "roles",
            "shared_artifacts",
            "contracts",
            "validation_rules",
            "build_expectations",
            "runtime_expectations",
            "worker_tasks",
        ],
        "properties": {
            "task_summary": narrow_string_schema(10),
            "project_brief_path": {"type": "string", "const": "Project_description.md"},
            "stages": {"type": "array", "items": narrow_string_schema(3), "minItems": 10, "maxItems": 10},
            "roles": {"type": "array", "items": narrow_string_schema(3), "minItems": 6, "maxItems": 6},
            "shared_artifacts": {"type": "array", "items": narrow_string_schema(3), "minItems": 4},
            "contracts": {"type": "array", "items": narrow_string_schema(3), "minItems": 3},
            "validation_rules": {
                "type": "array",
                "minItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "kind", "target", "expectation"],
                    "properties": {
                        "name": narrow_string_schema(3),
                        "kind": {"enum": ["file_exists", "contains_text", "json_parse", "route_contract", "sqlite_artifact", "offline_command"]},
                        "target": narrow_string_schema(3),
                        "expectation": narrow_string_schema(3),
                    },
                },
            },
            "build_expectations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "command", "offline_safe"],
                    "properties": {
                        "name": narrow_string_schema(3),
                        "command": narrow_string_schema(3),
                        "offline_safe": {"type": "boolean", "const": True},
                    },
                },
            },
            "runtime_expectations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "command", "offline_safe"],
                    "properties": {
                        "name": narrow_string_schema(3),
                        "command": narrow_string_schema(3),
                        "offline_safe": {"type": "boolean", "const": True},
                    },
                },
            },
            "worker_tasks": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": worker_task_schema(),
            },
        },
    }


class PlanValidationError(RuntimeError):
    pass


def is_concrete_relative_path(value: str) -> bool:
    path = Path(value)
    return (
        bool(value.strip())
        and value == value.strip()
        and not path.is_absolute()
        and not value.startswith("./")
        and ".." not in path.parts
        and not value.endswith("/")
        and "\n" not in value
        and "\r" not in value
    )


def is_concrete_relative_file_path(value: str) -> bool:
    if not is_concrete_relative_path(value):
        return False
    path = Path(value)
    return bool(path.suffix) or path.name in {"Dockerfile", "Makefile", "README.md"}


def validate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []

    if plan.get("project_brief_path") != "Project_description.md":
        errors.append("project_brief_path must equal Project_description.md")
    if plan.get("stages") != REQUIRED_STAGE_NAMES:
        errors.append("stages must exactly match the required ten pipeline stage names")
    if plan.get("roles") != REQUIRED_ROLE_NAMES:
        errors.append("roles must exactly match the required role names in order")

    seen_owned: Dict[str, str] = {}
    worker_roles = set()

    for idx, task in enumerate(plan.get("worker_tasks", [])):
        role = task.get("role")
        if role in worker_roles:
            errors.append(f"worker_tasks[{idx}].role duplicates {role}")
        worker_roles.add(role)

        for field in ("owned_paths", "required_outputs", "read_only_inputs", "forbidden_paths"):
            for item_idx, value in enumerate(task.get(field, [])):
                if not is_concrete_relative_file_path(value):
                    errors.append(f"worker_tasks[{idx}].{field}[{item_idx}] must be a concrete relative file path")

        for owned in task.get("owned_paths", []):
            previous = seen_owned.get(owned)
            if previous:
                errors.append(f"overlapping ownership for {owned}: {previous} and {role}")
            seen_owned[owned] = role

        required_outputs = set(task.get("required_outputs", []))
        owned_paths = set(task.get("owned_paths", []))
        if not required_outputs.issubset(owned_paths):
            errors.append(f"worker_tasks[{idx}] required_outputs must be a subset of owned_paths")

        for rule_idx, rule in enumerate(task.get("validation_rules", [])):
            if rule.get("kind") not in {"file_exists", "contains_text", "json_parse", "route_contract", "sqlite_artifact", "offline_command"}:
                errors.append(f"worker_tasks[{idx}].validation_rules[{rule_idx}].kind is invalid")
            if not rule.get("target"):
                errors.append(f"worker_tasks[{idx}].validation_rules[{rule_idx}].target is required")
            elif rule.get("kind") != "offline_command" and not is_concrete_relative_file_path(str(rule.get("target"))):
                errors.append(f"worker_tasks[{idx}].validation_rules[{rule_idx}].target must be a concrete relative file path")

    if worker_roles != EDITING_ROLES:
        errors.append("worker_tasks must contain exactly Backend Producer and Frontend Producer")

    for idx, rule in enumerate(plan.get("validation_rules", [])):
        if rule.get("kind") not in {"file_exists", "contains_text", "json_parse", "route_contract", "sqlite_artifact", "offline_command"}:
            errors.append(f"validation_rules[{idx}].kind is invalid")
        if not rule.get("target"):
            errors.append(f"validation_rules[{idx}].target is required")
        elif rule.get("kind") != "offline_command" and not is_concrete_relative_file_path(str(rule.get("target"))):
            errors.append(f"validation_rules[{idx}].target must be a concrete relative file path")

    for field in ("shared_artifacts", "contracts"):
        for idx, value in enumerate(plan.get(field, [])):
            if not is_concrete_relative_file_path(value):
                errors.append(f"{field}[{idx}] must be a concrete relative file path")

    for bucket in ("build_expectations", "runtime_expectations"):
        for idx, entry in enumerate(plan.get(bucket, [])):
            command = str(entry.get("command", "")).lower()
            if any(pattern in command for pattern in BANNED_INSTALL_PATTERNS):
                errors.append(f"{bucket}[{idx}].command uses a banned install command")
            if re.search(r"\b(npm|pnpm|yarn|bun)\b", command):
                errors.append(f"{bucket}[{idx}].command must not depend on package-manager scripts")
            if re.search(r"(^|\\s)node\\s+\\S+\\.ts(\\s|$)", command):
                errors.append(f"{bucket}[{idx}].command must not execute TypeScript files directly with node")
            if not entry.get("offline_safe", False):
                errors.append(f"{bucket}[{idx}].offline_safe must be true")

    if errors:
        raise PlanValidationError("; ".join(errors))

    return {"status": "valid", "worker_roles": sorted(worker_roles)}


def load_project_brief(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Project brief not found: {path}")
    text = read_text(path)
    if len(text.strip()) < 1000:
        raise RuntimeError("Project_description.md is unexpectedly short")
    append_jsonl(DECISION_LOG, {
        "timestamp": utc_now(),
        "type": "project_brief_ingested",
        "path": str(path.relative_to(ROOT)),
        "char_count": len(text),
        "line_count": len(text.splitlines()),
        "sha256": sha256_bytes(text.encode("utf-8")),
    })
    return text


def role_header(name: str) -> str:
    return textwrap.dedent(
        f"""\
        You are the {name} inside a Codex-only multi-agent workflow.
        Operate only from repository state, shared artifacts, and the full Project_description.md content provided below.
        Do not assume hidden requirements.
        Return only JSON matching the required schema.
        """
    ).strip()


def context_prompt(project_brief: str, repo_files: Sequence[str]) -> str:
    return f"""\
{role_header("Context Analyst")}

Repository file listing sample:
{json.dumps(list(repo_files), indent=2)}

You are read-only. Interpret the canonical brief in full and extract only durable, implementation-driving facts.

Project_description.md (full text):
{project_brief}
"""


def planner_prompt(project_brief: str, context_json: str) -> str:
    return f"""\
{role_header("Architect")}

Produce the machine-checkable implementation plan.
Rules:
- Use exactly the required stages and roles.
- Create exactly two editing worker tasks: Backend Producer and Frontend Producer.
- Every path field must contain only concrete relative file paths.
- Do not use directory placeholders, `./` prefixes, or leading/trailing whitespace in any path field.
- Ensure owned_paths do not overlap between workers.
- Required outputs must be subsets of owned_paths.
- Use Next.js, SQLite, and WebGL or WebGPU only when relevant to the brief.
- Validation must be offline-safe. Do not use install commands.
- Build expectations and runtime expectations must be shell commands the orchestrator can run without network access.
- Do not emit `npm run ...`, `pnpm ...`, `yarn ...`, `bun ...`, or `node path/to/file.ts` unless the repository already contains the local offline runtime dependencies needed to execute them.
- Prefer artifact-based checks such as `test -f`, `rg`, JSON parsing, and Python static validation when JavaScript dependencies are not guaranteed to exist locally.
- Shared artifacts should include planner/contract files written by the orchestrator or agents.

Structured context:
{context_json}

Project_description.md (full text):
{project_brief}
"""


def planner_repair_prompt(project_brief: str, context_json: str, invalid_plan_json: str, validation_error: str) -> str:
    return f"""\
{role_header("Architect")}

The previous plan failed validation.
Targeted error:
{validation_error}

Repair the exact offending fields without changing unrelated valid structure.

Previous invalid plan:
{invalid_plan_json}

Structured context:
{context_json}

Project_description.md (full text):
{project_brief}
"""


def worker_prompt(
    role: str,
    task: Dict[str, Any],
    project_brief: str,
    plan_json: str,
    context_json: str,
) -> str:
    owned_paths = "\n".join(f"- {item}" for item in task["owned_paths"])
    forbidden_paths = "\n".join(f"- {item}" for item in task["forbidden_paths"])
    readonly_inputs = "\n".join(f"- {item}" for item in task["read_only_inputs"])
    required_outputs = "\n".join(f"- {item}" for item in task["required_outputs"])
    contracts = "\n".join(f"- {item}" for item in task["contracts"])
    validation_rules = "\n".join(
        f"- {rule['kind']} :: {rule['target']} :: {rule['expectation']}" for rule in task["validation_rules"]
    )
    return f"""\
You are the {role}. You are not alone in the codebase. Do not revert edits made by others, and do not touch files outside your ownership.
Work only inside this worktree. Follow the Architect plan and the project brief. Use repository state, shared artifacts, and Project_description.md only.

You own only:
{owned_paths}

Do not modify:
{forbidden_paths}

Read-only inputs:
{readonly_inputs}

Editable outputs:
{required_outputs}

Task summary:
{task["summary"]}

Contracts:
{contracts}

Validation rules:
{validation_rules}

Required final output format:
{{
  "final_status": "completed" | "blocked",
  "changed_files": ["relative/path"],
  "summary": "short summary",
  "blockers": ["..."]
}}

Structured context:
{context_json}

Plan:
{plan_json}

Project_description.md (full text):
{project_brief}
"""


def verification_prompt(project_brief: str, context_json: str, plan_json: str, artifact_inventory: Sequence[str]) -> str:
    return f"""\
{role_header("Verification Agent")}

Validate artifacts semantically using the declared contracts. Read the actual artifact files you reference.
Do not modify the repository.
Return findings based on durable evidence, not wording preference.
Every finding must include the concrete source file paths you actually inspected.
Every `source_files` entry must be an existing relative file path in this repository.
Do not cite files you did not read.
Prefer a few high-signal findings with exact file-level evidence over broad speculative criticism.

Artifact inventory:
{json.dumps(list(artifact_inventory), indent=2)}

Structured context:
{context_json}

Plan:
{plan_json}

Project_description.md (full text):
{project_brief}
"""


def verification_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "checked_files", "findings", "summary"],
        "properties": {
            "status": {"type": "string", "enum": ["passed", "failed"]},
            "checked_files": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["severity", "message", "source_files"],
                    "properties": {
                        "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                        "message": narrow_string_schema(3),
                        "source_files": {"type": "array", "items": narrow_string_schema(3), "minItems": 1},
                    },
                },
            },
            "summary": narrow_string_schema(3),
        },
    }


@dataclass
class WorkerResult:
    role: str
    final_status: str
    changed_files: List[str]
    summary: str
    blockers: List[str]
    usage: Dict[str, Any] = field(default_factory=dict)
    retries: int = 0


def worker_result_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["final_status", "changed_files", "summary", "blockers"],
        "properties": {
            "final_status": {"enum": ["completed", "blocked"]},
            "changed_files": {"type": "array", "items": narrow_string_schema(3)},
            "summary": narrow_string_schema(3),
            "blockers": {"type": "array", "items": narrow_string_schema(3)},
        },
    }


async def ensure_git_worktree(path: Path) -> None:
    await run_command(["git", "worktree", "prune"], cwd=ROOT, timeout=120)
    if path.exists():
        shutil.rmtree(path)
    rc, _, stderr = await run_command(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT, timeout=120)
    if rc != 0 and "is not a working tree" not in stderr and "is a main working tree" not in stderr:
        raise RuntimeError(f"Failed to clear existing git worktree registration at {path}: {stderr}")
    rc, _, stderr = await run_command(["git", "worktree", "add", "--detach", "--force", str(path), "HEAD"], cwd=ROOT, timeout=120)
    if rc != 0:
        raise RuntimeError(f"Failed to create git worktree at {path}: {stderr}")
    await mirror_local_deletions(path)


def parse_deleted_paths_from_status(status_payload: str) -> List[str]:
    deleted: List[str] = []
    if not status_payload:
        return deleted
    entries = status_payload.split("\0")
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        idx += 1
        if not entry or len(entry) < 3:
            continue
        status = entry[:2]
        rel_path = entry[3:]
        if status in {"??", "!!"}:
            continue
        if status[0] in {"R", "C"} and idx < len(entries):
            # Skip rename/copy destination entry
            idx += 1
        if "D" in status and rel_path:
            deleted.append(rel_path)
    return deleted


async def mirror_local_deletions(worktree_path: Path) -> None:
    rc, status_payload, stderr = await run_command(["git", "status", "--porcelain", "-z"], cwd=ROOT, timeout=120)
    if rc != 0:
        raise RuntimeError(f"Failed to inspect git status: {stderr}")
    deleted_paths = parse_deleted_paths_from_status(status_payload)
    for rel_path in deleted_paths:
        target = worktree_path / rel_path
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)


async def remove_git_worktree(path: Path) -> None:
    await run_command(["git", "worktree", "prune"], cwd=ROOT, timeout=120)
    rc, _, stderr = await run_command(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT, timeout=120)
    if path.exists():
        shutil.rmtree(path)
    if rc != 0 and "is not a working tree" not in stderr:
        raise RuntimeError(f"Failed to remove git worktree {path}: {stderr}")
    await run_command(["git", "worktree", "prune"], cwd=ROOT, timeout=120)


def copy_selected_paths(source_root: Path, dest_root: Path, paths: Iterable[str]) -> List[str]:
    copied: List[str] = []
    for rel in sorted(set(paths)):
        src = source_root / rel
        dst = dest_root / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return copied


def validate_artifact_paths(plan: Dict[str, Any]) -> Dict[str, Any]:
    missing: List[str] = []
    for task in plan["worker_tasks"]:
        for path in task["required_outputs"]:
            if not (ROOT / path).exists():
                missing.append(path)
    if missing:
        raise RuntimeError(f"Artifact validation failed. Missing required outputs: {missing}")
    return {"status": "passed", "missing": []}


def detect_relevant_files(paths: Iterable[str]) -> List[str]:
    relevant_suffixes = {".ts", ".tsx", ".js", ".jsx", ".sql", ".md", ".html", ".css", ".json"}
    return [path for path in sorted(set(paths)) if Path(path).suffix in relevant_suffixes]


async def run_offline_validation_commands(entries: Sequence[Dict[str, Any]], report_name: str) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for entry in entries:
        command = str(entry["command"]).strip()
        lower = command.lower()
        if any(pattern in lower for pattern in BANNED_INSTALL_PATTERNS):
            raise RuntimeError(f"{report_name} rejected banned install command: {command}")
        rc, stdout, stderr = await run_command(["bash", "-lc", command], cwd=ROOT, timeout=300)
        results.append({
            "name": entry["name"],
            "command": command,
            "returncode": rc,
            "stdout_tail": stdout[-1000:],
            "stderr_tail": stderr[-1000:],
        })
        if rc != 0:
            raise RuntimeError(f"{report_name} command failed: {command}")
    return {"status": "passed", "results": results}


async def stage_environment_preflight(project_brief: str) -> Dict[str, Any]:
    log_step("Stage 1/10: Environment preflight")
    ensure_dirs()
    codex_path = require_command("codex")
    git_path = require_command("git")
    python_path = require_command("python3")
    node_path = shutil.which("node")
    npm_path = shutil.which("npm")
    if "Next.js" in project_brief and (not node_path or not npm_path):
        raise RuntimeError("Project brief requires Next.js, but node or npm is missing")

    versions: Dict[str, str] = {}
    for name, command in [("codex", [codex_path, "--version"]), ("git", [git_path, "--version"]), ("python3", [python_path, "--version"])]:
        rc, stdout, stderr = await run_command(command, cwd=ROOT, timeout=60)
        if rc != 0:
            raise RuntimeError(f"Preflight failed for {name}: {stderr}")
        versions[name] = (stdout or stderr).strip()

    if node_path:
        rc, stdout, stderr = await run_command([node_path, "--version"], cwd=ROOT, timeout=60)
        versions["node"] = (stdout or stderr).strip()
    if npm_path:
        rc, stdout, stderr = await run_command([npm_path, "--version"], cwd=ROOT, timeout=60)
        versions["npm"] = (stdout or stderr).strip()

    rc, stdout, stderr = await run_command(["git", "worktree", "list"], cwd=ROOT, timeout=60)
    if rc != 0:
        raise RuntimeError(f"git worktree list failed: {stderr}")

    report = {
        "status": "passed",
        "versions": versions,
        "worktree_list": stdout.strip().splitlines(),
        "asset_dirs": [str(path.relative_to(ROOT)) for path in CANONICAL_ASSET_DIRS],
    }
    write_text(REPORTS_DIR / "environment_preflight.json", json.dumps(report, indent=2))
    return report


async def stage_context_analysis(project_brief: str) -> Dict[str, Any]:
    log_step("Stage 2/10: Context analysis")
    schema_path = write_schema("context_analysis", context_analysis_schema())
    result = await run_codex(
        context_prompt(project_brief, repo_file_listing()),
        cwd=ROOT,
        schema_path=schema_path,
    )
    payload = load_json(result.final_text)
    write_text(CONTEXT_ANALYSIS_JSON, json.dumps(payload, indent=2))
    append_jsonl(DECISION_LOG, {"timestamp": utc_now(), "type": "context_analysis_complete", "usage": result.usage})
    return payload


async def stage_planner_generation(project_brief: str, context_payload: Dict[str, Any]) -> Dict[str, Any]:
    log_step("Stage 3/10: Planner generation")
    schema_path = write_schema("plan", plan_schema())
    result = await run_codex(
        planner_prompt(project_brief, json.dumps(context_payload, indent=2)),
        cwd=ROOT,
        schema_path=schema_path,
    )
    payload = load_json(result.final_text)
    write_text(PLAN_JSON, json.dumps(payload, indent=2))
    append_jsonl(DECISION_LOG, {"timestamp": utc_now(), "type": "plan_generated", "usage": result.usage})
    return payload


async def stage_plan_validation(project_brief: str, context_payload: Dict[str, Any], plan_payload: Dict[str, Any]) -> Dict[str, Any]:
    log_step("Stage 4/10: Planner schema validation")
    try:
        report = validate_plan(plan_payload)
        write_text(PLAN_VALIDATION_JSON, json.dumps({"status": "valid", "details": report}, indent=2))
        return plan_payload
    except PlanValidationError as exc:
        write_text(PLAN_VALIDATION_JSON, json.dumps({"status": "invalid", "error": str(exc)}, indent=2))
        return await stage_plan_repair(project_brief, context_payload, plan_payload, str(exc))


async def stage_plan_repair(project_brief: str, context_payload: Dict[str, Any], plan_payload: Dict[str, Any], validation_error: str) -> Dict[str, Any]:
    log_step("Stage 5/10: Planner repair loop if needed")
    schema_path = write_schema("plan_repair", plan_schema())
    current = plan_payload
    last_error = validation_error
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        result = await run_codex(
            planner_repair_prompt(
                project_brief,
                json.dumps(context_payload, indent=2),
                json.dumps(current, indent=2),
                last_error,
            ),
            cwd=ROOT,
            schema_path=schema_path,
        )
        current = load_json(result.final_text)
        try:
            validate_plan(current)
            write_text(PLAN_JSON, json.dumps(current, indent=2))
            write_text(PLAN_VALIDATION_JSON, json.dumps({"status": "valid_after_repair", "attempt": attempt}, indent=2))
            append_jsonl(DECISION_LOG, {
                "timestamp": utc_now(),
                "type": "plan_repaired",
                "attempt": attempt,
                "previous_error": last_error,
            })
            return current
        except PlanValidationError as exc:
            last_error = str(exc)
            write_text(PLAN_VALIDATION_JSON, json.dumps({"status": "invalid_after_repair", "attempt": attempt, "error": last_error}, indent=2))
    raise RuntimeError(f"Planner repair loop exhausted: {last_error}")


async def run_worker_task(
    semaphore: asyncio.Semaphore,
    project_brief: str,
    context_payload: Dict[str, Any],
    plan_payload: Dict[str, Any],
    task: Dict[str, Any],
) -> WorkerResult:
    role = task["role"]
    worktree_path = WORKTREES_DIR / slugify(role)
    schema_path = write_schema(f"{slugify(role)}_result", worker_result_schema())
    prompt = worker_prompt(role, task, project_brief, json.dumps(plan_payload, indent=2), json.dumps(context_payload, indent=2))

    async with semaphore:
        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            retries = attempt
            await ensure_git_worktree(worktree_path)
            before = snapshot_workspace(worktree_path)
            try:
                log_step(f"Worker launch: {role} (attempt {attempt + 1})")
                result = await run_codex(prompt, cwd=worktree_path, schema_path=schema_path)
                payload = load_json(result.final_text)
                after = snapshot_workspace(worktree_path)
                policy = StepPolicy(
                    name=role,
                    allowed_create_globs=tuple(task["owned_paths"]),
                    allowed_modify_globs=tuple(task["owned_paths"]),
                    forbidden_globs=tuple(task["forbidden_paths"]),
                    frozen_inputs=tuple(task["read_only_inputs"]),
                    required_outputs=tuple(task["required_outputs"]),
                )
                enforce_policy(before, after, policy)
                copied = copy_selected_paths(worktree_path, ROOT, task["owned_paths"])
                append_jsonl(DECISION_LOG, {
                    "timestamp": utc_now(),
                    "type": "worker_completed",
                    "role": role,
                    "attempt": attempt + 1,
                    "copied_paths": copied,
                    "usage": result.usage,
                })
                await remove_git_worktree(worktree_path)
                return WorkerResult(
                    role=role,
                    final_status=payload["final_status"],
                    changed_files=payload["changed_files"],
                    summary=payload["summary"],
                    blockers=payload["blockers"],
                    usage=result.usage,
                    retries=retries,
                )
            except Exception as exc:
                failure_class = classify_failure(exc)
                append_jsonl(DECISION_LOG, {
                    "timestamp": utc_now(),
                    "type": "worker_failure",
                    "role": role,
                    "attempt": attempt + 1,
                    "failure_class": failure_class,
                    "error": str(exc),
                })
                await remove_git_worktree(worktree_path)
                if failure_class == "retryable_infrastructure" and attempt < MAX_REPAIR_ATTEMPTS:
                    log_step(f"Retrying {role} after retryable infrastructure failure")
                    continue
                raise
    raise RuntimeError(f"Worker {role} ended unexpectedly")


def build_dependency_owner_map(plan_payload: Dict[str, Any]) -> Dict[str, str]:
    owners: Dict[str, str] = {}
    for task in plan_payload.get("worker_tasks", []):
        role = task["role"]
        for path in task.get("owned_paths", []):
            owners.setdefault(path, role)
        for path in task.get("required_outputs", []):
            owners.setdefault(path, role)
    return owners


def normalize_dependency_name(dependency: str, roles: Sequence[str]) -> str:
    for role in roles:
        if dependency == role:
            return role
        if dependency.startswith(f"{role} "):
            return role
    return dependency


def dependency_is_satisfied(dependency: str, completed_roles: set[str], dependency_owner_map: Dict[str, str]) -> bool:
    if dependency in completed_roles:
        return True
    owner = dependency_owner_map.get(dependency)
    if owner:
        return owner in completed_roles
    return (ROOT / dependency).exists()


def detect_worker_dependency_cycle(pending_tasks: Dict[str, Dict[str, Any]], dependency_owner_map: Dict[str, str]) -> Optional[List[str]]:
    """Return one cycle of role dependencies if detected, else None."""
    graph: Dict[str, List[str]] = {role: [] for role in pending_tasks}
    for role, task in pending_tasks.items():
        for dependency in task.get("dependencies", []):
            target: Optional[str] = None
            if dependency in pending_tasks:
                target = dependency
            else:
                owner = dependency_owner_map.get(dependency)
                if owner in pending_tasks:
                    target = owner
            if target and target != role:
                graph[role].append(target)

    visited: set[str] = set()
    stack: List[str] = []
    stack_set: set[str] = set()

    def dfs(node: str) -> Optional[List[str]]:
        visited.add(node)
        stack.append(node)
        stack_set.add(node)
        for neighbor in graph[node]:
            if neighbor not in visited:
                cycle = dfs(neighbor)
                if cycle:
                    return cycle
            elif neighbor in stack_set:
                idx = stack.index(neighbor)
                return stack[idx:].copy()
        stack.pop()
        stack_set.remove(node)
        return None

    for role in graph:
        if role not in visited:
            cycle = dfs(role)
            if cycle:
                return cycle
    return None


async def stage_worker_generation(project_brief: str, context_payload: Dict[str, Any], plan_payload: Dict[str, Any], max_concurrency: int) -> List[WorkerResult]:
    log_step("Stage 6/10: Worker generation")
    for task in plan_payload["worker_tasks"]:
        task_path = TASKS_DIR / f"{slugify(task['role'])}.json"
        write_text(task_path, json.dumps(task, indent=2))

    semaphore = asyncio.Semaphore(max_concurrency)
    roles = plan_payload.get("roles", [])
    pending = {}
    for task in plan_payload["worker_tasks"]:
        normalized_task = dict(task)
        normalized_task["dependencies"] = [
            normalize_dependency_name(dep, roles) for dep in task.get("dependencies", [])
        ]
        pending[task["role"]] = normalized_task
    completed_roles = {"Architect"}
    dependency_owner_map = build_dependency_owner_map(plan_payload)
    results: List[WorkerResult] = []

    while pending:
        ready = [
            task for task in pending.values()
            if all(dependency_is_satisfied(dep, completed_roles, dependency_owner_map) for dep in task.get("dependencies", []))
        ]
        if not ready:
            cycle = detect_worker_dependency_cycle(pending, dependency_owner_map)
            if cycle:
                forced_role = cycle[0]
                log_step(
                    "Worker dependency cycle detected; forcing execution order for "
                    + ", ".join(cycle)
                )
                ready = [pending[forced_role]]
            else:
                unresolved = {
                    role: [
                        dep for dep in task.get("dependencies", [])
                        if not dependency_is_satisfied(dep, completed_roles, dependency_owner_map)
                    ]
                    for role, task in pending.items()
                }
                raise RuntimeError(f"Worker dependency deadlock: {unresolved}")
        batch = ready[:max_concurrency]
        batch_results = await asyncio.gather(
            *(run_worker_task(semaphore, project_brief, context_payload, plan_payload, task) for task in batch)
        )
        for item in batch_results:
            completed_roles.add(item.role)
            pending.pop(item.role, None)
            results.append(item)

    write_text(REPORTS_DIR / "worker_results.json", json.dumps([asdict(item) for item in results], indent=2))
    return results


async def stage_artifact_validation(project_brief: str, context_payload: Dict[str, Any], plan_payload: Dict[str, Any]) -> Dict[str, Any]:
    log_step("Stage 7/10: Artifact validation")
    local_report = validate_artifact_paths(plan_payload)
    relevant_files = detect_relevant_files(
        [path for task in plan_payload["worker_tasks"] for path in task["required_outputs"]] + plan_payload["shared_artifacts"]
    )
    schema_path = write_schema("verification", verification_schema())
    result = await run_codex(
        verification_prompt(project_brief, json.dumps(context_payload, indent=2), json.dumps(plan_payload, indent=2), relevant_files),
        cwd=ROOT,
        schema_path=schema_path,
    )
    payload = load_json(result.final_text)
    report = {"local_report": local_report, "agent_report": payload}
    write_text(REPORTS_DIR / "artifact_validation.json", json.dumps(report, indent=2))
    if payload["status"] == "failed":
        raise RuntimeError("Verification Agent reported artifact validation failure")
    return report


async def stage_build_validation(plan_payload: Dict[str, Any]) -> Dict[str, Any]:
    log_step("Stage 8/10: Build validation")
    report = await run_offline_validation_commands(plan_payload["build_expectations"], "build_validation")
    write_text(REPORTS_DIR / "build_validation.json", json.dumps(report, indent=2))
    return report


async def stage_runtime_validation(plan_payload: Dict[str, Any]) -> Dict[str, Any]:
    log_step("Stage 9/10: Runtime validation")
    report = await run_offline_validation_commands(plan_payload["runtime_expectations"], "runtime_validation")
    write_text(REPORTS_DIR / "runtime_validation.json", json.dumps(report, indent=2))
    return report


async def stage_final_acceptance_summary(
    project_brief_path: Path,
    context_payload: Dict[str, Any],
    plan_payload: Dict[str, Any],
    worker_results: List[WorkerResult],
) -> Dict[str, Any]:
    log_step("Stage 10/10: Final acceptance summary")
    summary = {
        "status": "passed",
        "project_brief_path": str(project_brief_path.relative_to(ROOT)),
        "project_brief_sha256": sha256_file(project_brief_path),
        "roles": REQUIRED_ROLE_NAMES,
        "stages": REQUIRED_STAGE_NAMES,
        "context_domain": context_payload["domain"],
        "worker_results": [asdict(item) for item in worker_results],
        "artifacts": sorted(str(path.relative_to(ROOT)) for path in ORCH_DIR.rglob("*") if path.is_file()),
        "generated_at": utc_now(),
    }
    write_text(FINAL_SUMMARY_JSON, json.dumps(summary, indent=2))
    return summary


def write_runtime_config(project_brief_path: Path, max_concurrency: int) -> None:
    payload = {
        "model": MODEL,
        "sandbox_mode": SANDBOX,
        "approval_policy": APPROVAL_POLICY,
        "workspace_root": str(ROOT),
        "timeout_policy_seconds": CODEX_TIMEOUT_SECONDS,
        "project_brief_path": str(project_brief_path.relative_to(ROOT)),
        "canonical_output_locations": {
            "orchestrator_dir": str(ORCH_DIR.relative_to(ROOT)),
            "manifests": str(MANIFESTS_DIR.relative_to(ROOT)),
            "reports": str(REPORTS_DIR.relative_to(ROOT)),
            "worker_tasks": str(TASKS_DIR.relative_to(ROOT)),
            "worktrees": str(WORKTREES_DIR.relative_to(ROOT)),
        },
        "max_concurrency": max_concurrency,
    }
    write_text(RUNTIME_CONFIG_JSON, json.dumps(payload, indent=2))


def default_bootstrap_plan() -> Dict[str, Any]:
    return {
        "task_summary": "Build and validate the Codex-only multi-agent orchestrator that consumes Project_description.md in full and coordinates bounded concurrent workers through explicit stages.",
        "project_brief_path": "Project_description.md",
        "stages": REQUIRED_STAGE_NAMES,
        "roles": REQUIRED_ROLE_NAMES,
        "shared_artifacts": [
            ".orchestrator/context_analysis.json",
            ".orchestrator/plan.json",
            ".orchestrator/plan_validation.json",
            ".orchestrator/final_acceptance_summary.json",
        ],
        "contracts": [
            "Project_description.md is the canonical brief and must be read in full before worker execution.",
            "Worker ownership must not overlap and must be enforced through worktree policy checks.",
            "Validation commands must be offline-safe and must not use install commands.",
        ],
        "validation_rules": [
            {"name": "Brief exists", "kind": "file_exists", "target": "Project_description.md", "expectation": "project brief is present"},
            {"name": "Context analysis written", "kind": "json_parse", "target": ".orchestrator/context_analysis.json", "expectation": "valid JSON object"},
            {"name": "Plan written", "kind": "json_parse", "target": ".orchestrator/plan.json", "expectation": "valid JSON object"},
            {"name": "README present", "kind": "file_exists", "target": "README.md", "expectation": "usage instructions exist"},
            {"name": "Summary written", "kind": "json_parse", "target": ".orchestrator/final_acceptance_summary.json", "expectation": "final summary exists"},
        ],
        "build_expectations": [
            {"name": "Python compile", "command": "python3 -m py_compile orchestrator.py multi_agent_workflow_deterministic_ver3_finance.py", "offline_safe": True},
        ],
        "runtime_expectations": [
            {"name": "Preflight dry run", "command": "python3 orchestrator.py --dry-run-preflight --project-brief Project_description.md", "offline_safe": True},
        ],
        "worker_tasks": [
            {
                "role": "Backend Producer",
                "summary": "Own the Python orchestration entrypoint and compatibility wrapper so the workflow can run its staged execution model.",
                "owned_paths": ["orchestrator.py", "multi_agent_workflow_deterministic_ver3_finance.py"],
                "required_outputs": ["orchestrator.py", "multi_agent_workflow_deterministic_ver3_finance.py"],
                "read_only_inputs": ["Project_description.md"],
                "forbidden_paths": ["README.md", "04.README.md", "05.Use.md"],
                "dependencies": ["Architect"],
                "contracts": [
                    "Use codex exec for role execution.",
                    "Implement bounded concurrency with git worktrees for editing workers.",
                ],
                "validation_rules": [
                    {"name": "orchestrator exists", "kind": "file_exists", "target": "orchestrator.py", "expectation": "entrypoint present"},
                    {"name": "wrapper exists", "kind": "file_exists", "target": "multi_agent_workflow_deterministic_ver3_finance.py", "expectation": "compatibility wrapper present"},
                ],
            },
            {
                "role": "Frontend Producer",
                "summary": "Own the usage documentation so operators can start the workflow and understand the generated artifacts.",
                "owned_paths": ["README.md"],
                "required_outputs": ["README.md"],
                "read_only_inputs": ["Project_description.md", "orchestrator.py"],
                "forbidden_paths": ["04.README.md", "05.Use.md", "multi_agent_workflow_deterministic_ver3_finance.py"],
                "dependencies": ["Architect"],
                "contracts": [
                    "Document how to run the orchestrator and what it validates.",
                ],
                "validation_rules": [
                    {"name": "readme exists", "kind": "file_exists", "target": "README.md", "expectation": "usage instructions exist"},
                ],
            },
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex-only multi-agent orchestrator")
    parser.add_argument("--project-brief", default=str(DEFAULT_BRIEF), help="Path to Project_description.md")
    parser.add_argument("--max-concurrency", type=int, default=2, help="Maximum concurrent editing workers")
    parser.add_argument("--dry-run-preflight", action="store_true", help="Run only environment preflight and exit")
    parser.add_argument("--bootstrap-plan", action="store_true", help="Use the local bootstrap plan instead of invoking Codex for planning")
    parser.add_argument("--resume-from-stage", default="", help="Resume from a stage index, exact stage name, or stage slug")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    ensure_dirs()

    project_brief_path = Path(args.project_brief)
    if not project_brief_path.is_absolute():
        project_brief_path = ROOT / project_brief_path
    project_brief = load_project_brief(project_brief_path)
    write_runtime_config(project_brief_path, args.max_concurrency)
    resume_stage_index = parse_resume_stage(args.resume_from_stage)
    if resume_stage_index > 1:
        ensure_resume_prerequisites(resume_stage_index, project_brief_path)
        log_step(f"Resuming from Stage {resume_stage_index}/10: {REQUIRED_STAGE_NAMES[resume_stage_index - 1]}")

    preflight_report: Dict[str, Any]
    context_payload: Dict[str, Any]
    plan_payload: Dict[str, Any]
    worker_results: List[WorkerResult]

    if resume_stage_index <= 1:
        preflight_report = await stage_environment_preflight(project_brief)
        write_manifest(1, REQUIRED_STAGE_NAMES[0], "Environment preflight complete")
        write_checkpoint(1, REQUIRED_STAGE_NAMES[0], "Environment preflight complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 1/10: Environment preflight")
        preflight_report = load_json_file(REPORTS_DIR / "environment_preflight.json")
    if args.dry_run_preflight:
        log_step("Dry-run preflight completed")
        return

    if resume_stage_index <= 2:
        context_payload = await stage_context_analysis(project_brief)
        write_manifest(2, REQUIRED_STAGE_NAMES[1], "Context analysis complete")
        write_checkpoint(2, REQUIRED_STAGE_NAMES[1], "Context analysis complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 2/10: Context analysis")
        context_payload = load_json_file(CONTEXT_ANALYSIS_JSON)

    if resume_stage_index <= 3:
        if args.bootstrap_plan:
            log_step("Stage 3/10: Planner generation (bootstrap plan)")
            plan_payload = default_bootstrap_plan()
            write_text(PLAN_JSON, json.dumps(plan_payload, indent=2))
        else:
            plan_payload = await stage_planner_generation(project_brief, context_payload)
        write_manifest(3, REQUIRED_STAGE_NAMES[2], "Planner generation complete")
        write_checkpoint(3, REQUIRED_STAGE_NAMES[2], "Planner generation complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 3/10: Planner generation")
        plan_payload = load_json_file(PLAN_JSON)

    if resume_stage_index <= 4:
        if args.bootstrap_plan:
            log_step("Stage 4/10: Planner schema validation")
            validate_plan(plan_payload)
            write_text(PLAN_VALIDATION_JSON, json.dumps({"status": "valid", "details": {"bootstrap": True}}, indent=2))
        else:
            plan_payload = await stage_plan_validation(project_brief, context_payload, plan_payload)
        write_manifest(4, REQUIRED_STAGE_NAMES[3], "Planner validation complete")
        write_checkpoint(4, REQUIRED_STAGE_NAMES[3], "Planner validation complete", project_brief_path)
        write_manifest(5, REQUIRED_STAGE_NAMES[4], "Planner repair stage accounted for")
        write_checkpoint(5, REQUIRED_STAGE_NAMES[4], "Planner repair stage accounted for", project_brief_path)
    else:
        log_step("Resume skip: Stage 4/10: Planner schema validation")
        log_step("Resume skip: Stage 5/10: Planner repair loop if needed")
        plan_payload = load_json_file(PLAN_JSON)

    if resume_stage_index <= 6:
        worker_results = await stage_worker_generation(project_brief, context_payload, plan_payload, args.max_concurrency)
        write_manifest(6, REQUIRED_STAGE_NAMES[5], "Worker generation complete")
        write_checkpoint(6, REQUIRED_STAGE_NAMES[5], "Worker generation complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 6/10: Worker generation")
        worker_results = load_worker_results_report()

    if resume_stage_index <= 7:
        await stage_artifact_validation(project_brief, context_payload, plan_payload)
        write_manifest(7, REQUIRED_STAGE_NAMES[6], "Artifact validation complete")
        write_checkpoint(7, REQUIRED_STAGE_NAMES[6], "Artifact validation complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 7/10: Artifact validation")
        load_json_file(ARTIFACT_VALIDATION_JSON)

    if resume_stage_index <= 8:
        await stage_build_validation(plan_payload)
        write_manifest(8, REQUIRED_STAGE_NAMES[7], "Build validation complete")
        write_checkpoint(8, REQUIRED_STAGE_NAMES[7], "Build validation complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 8/10: Build validation")
        load_json_file(BUILD_VALIDATION_JSON)

    if resume_stage_index <= 9:
        await stage_runtime_validation(plan_payload)
        write_manifest(9, REQUIRED_STAGE_NAMES[8], "Runtime validation complete")
        write_checkpoint(9, REQUIRED_STAGE_NAMES[8], "Runtime validation complete", project_brief_path)
    else:
        log_step("Resume skip: Stage 9/10: Runtime validation")
        load_json_file(RUNTIME_VALIDATION_JSON)

    if resume_stage_index <= 10:
        await stage_final_acceptance_summary(project_brief_path, context_payload, plan_payload, worker_results)
        write_manifest(10, REQUIRED_STAGE_NAMES[9], "Final acceptance summary complete")
        write_checkpoint(10, REQUIRED_STAGE_NAMES[9], "Final acceptance summary complete", project_brief_path)

    append_jsonl(DECISION_LOG, {
        "timestamp": utc_now(),
        "type": "run_complete",
        "preflight_status": preflight_report["status"],
        "resume_from_stage": resume_stage_index,
    })
    log_step("Workflow completed successfully")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(130)

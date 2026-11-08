"""Opt-in host binding for a reviewed delegate_task.

Ordinary delegation is unchanged when ``review_contract`` is omitted. When it
is present, this module — not the parent model's text — hashes the source and
artifact, installs the host schemas, and accepts a review verdict only from
the review child's validated JSON. Evidence is a host-issued ref into those
bytes. A matching schema is not a release: release stays unexecuted until a
real owner authorizes it outside this contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

_MAX_TEXT_CHARS = 200_000
_SPAN_LINES = 12
_ROLES = ("work", "review")

WORK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {"status": {"type": "string", "enum": ["draft_written"]}},
}
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["verdict", "artifact_sha256", "evidence"],
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "needs_revision"]},
        "artifact_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["ref"],
                "properties": {
                    "ref": {"type": "string", "pattern": "^e[1-9][0-9]*$"},
                    "note": {"type": "string"},
                },
            },
        },
    },
}

_RELEASE = {"executed": False, "status": "owner_authorization_required"}


def start_review_contract(
    task_list: list[dict[str, Any]], raw: Any,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[str]]:
    """``(binding, cached_tool_result, error)``. A cache hit spawns nothing."""
    if not isinstance(raw, dict):
        return None, None, "review_contract must be an object with source and artifact paths."
    if len(task_list) != 1:
        return None, None, (
            "review_contract covers one task per call. Run the worker, then the reviewer, "
            "so the review hashes the artifact the worker left."
        )
    role = _task_role(task_list[0])
    if role not in _ROLES:
        return None, None, (
            "Set the task's option or review_role to work or review. "
            "review_contract does not infer a role from the goal text."
        )
    binding, text, error = _bind(raw, role)
    if error:
        return None, None, error
    _install(task_list[0], binding, text)
    cached = _cached_result(binding) if role == "review" else None
    return binding, cached, None


def evaluate_review(
    binding: dict[str, Any], results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Host verdict for one finished task. Work never counts as a review."""
    if binding.get("role") != "review":
        return _record(binding, review_state="awaiting_review", reason="work_is_not_a_review")
    entry = results[0] if results else {}
    if entry.get("schema_valid") is not True or entry.get("task_success") is not True:
        verdict = _record(binding, review_state="held_failure", reason="review_output_not_validated")
        _store(verdict)
        return verdict
    parsed = _parsed_summary(str(entry.get("summary") or ""))
    if not isinstance(parsed, dict):
        verdict = _record(binding, review_state="held_failure", reason="review_output_not_json")
        _store(verdict)
        return verdict
    verdict = _judge(binding, parsed)
    _store(verdict)
    return verdict


def _task_role(task: dict[str, Any]) -> Optional[str]:
    for key in ("review_role", "option"):
        value = task.get(key)
        if value in _ROLES:
            return value
    return None


def _bind(raw: dict[str, Any], role: str) -> tuple[Optional[dict[str, Any]], dict[str, str], Optional[str]]:
    ignored = raw.get("verdict", raw.get("review_verdict"))
    if ignored is not None and not isinstance(ignored, str):
        ignored = str(ignored)
    source, source_text, error = _identity(raw.get("source"), "source")
    if error:
        return None, {}, error
    artifact, artifact_text, error = _identity(raw.get("artifact"), "artifact")
    if error:
        return None, {}, error
    requirements = None
    requirements_text = ""
    if raw.get("requirements") is not None:
        requirements, requirements_text, error = _identity(raw.get("requirements"), "requirements")
        if error:
            return None, {}, error
    binding = {
        "role": role,
        "source": source,
        "artifact": artifact,
        "requirements": requirements,
        "evidence": _spans(artifact_text or ""),
        "ignored_caller_verdict": ignored,
    }
    return binding, {
        "artifact": artifact_text or "",
        "source": source_text or "",
        "requirements": requirements_text or "",
    }, None


def _identity(spec: Any, label: str) -> tuple[Optional[dict[str, str]], Optional[str], Optional[str]]:
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str) or not spec["path"].strip():
        return None, None, f"review_contract.{label}.path must be the local file to bind."
    path = Path(spec["path"]).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        return None, None, f"review_contract.{label} path cannot be resolved: {exc}"
    if not path.is_file():
        return None, None, f"review_contract.{label} is not a file: {path}"
    try:
        blob = path.read_bytes()
    except OSError as exc:
        return None, None, f"review_contract.{label} cannot be read: {exc}"
    if len(blob) > _MAX_TEXT_CHARS:
        return None, None, f"review_contract.{label} is larger than {_MAX_TEXT_CHARS} characters."
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, f"review_contract.{label} must be utf-8 text so evidence refs name real lines."
    digest = hashlib.sha256(blob).hexdigest()
    claimed = spec.get("sha256")
    if claimed is not None and claimed != digest:
        return None, None, (
            f"review_contract.{label} sha256 does not match the file bytes. "
            "The host hash is the identity; the call was refused before any subagent started."
        )
    return {"path": str(path), "sha256": digest}, text, None


def _spans(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines() or [""]
    spans = []
    for start in range(0, len(lines), _SPAN_LINES):
        chunk = lines[start:start + _SPAN_LINES]
        body = "\n".join(chunk).encode("utf-8")
        spans.append({
            "ref": f"e{len(spans) + 1}",
            "start_line": start + 1,
            "end_line": start + len(chunk),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    return spans


def _install(task: dict[str, Any], binding: dict[str, Any], text: dict[str, str]) -> None:
    """Replace any caller schema and append the host evidence block to context."""
    role = binding["role"]
    task["output_schema"] = REVIEW_SCHEMA if role == "review" else WORK_SCHEMA
    block = _contract_text(binding, text)
    base = str(task.get("context") or "").rstrip()
    task["context"] = f"{base}\n\n{block}" if base else block


def _contract_text(binding: dict[str, Any], text: dict[str, str]) -> str:
    artifact = binding["artifact"]["sha256"]
    lines = [
        "HOST REVIEW CONTRACT (machine-checked):",
        f"source_sha256: {binding['source']['sha256']}",
        f"artifact_sha256: {artifact}",
        "Final response: JSON only. Prose, a tool-call transcript, and a verdict written by the parent are not a review.",
        "This contract does not grant release or owner approval.",
    ]
    if binding["role"] == "work":
        lines.append('Status must be "draft_written". Do not emit a review verdict.')
        return "\n".join(lines)
    lines.append("Cite evidence by ref id only. Do not copy quotes; the host resolves each ref against these bytes.")
    lines.append(f"Copy artifact_sha256 exactly: {artifact}")
    for span in binding["evidence"]:
        lines.append(f"{span['ref']} lines {span['start_line']}-{span['end_line']}")
    lines.append("ARTIFACT:")
    lines.extend(f"{number}|{line}" for number, line in enumerate(text["artifact"].splitlines() or [""], 1))
    lines.append("SOURCE:")
    lines.append(text["source"])
    if binding.get("requirements"):
        lines.append("REQUIREMENTS:")
        lines.append(text["requirements"])
    return "\n".join(lines)


def _judge(binding: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    if parsed.get("artifact_sha256") != binding["artifact"]["sha256"]:
        return _record(binding, review_state="held_failure", reason="artifact_sha_mismatch")
    current, error = _rehash(binding["artifact"]["path"])
    if error or current != binding["artifact"]["sha256"]:
        return _record(binding, review_state="held_failure", reason="artifact_changed")
    known = {span["ref"]: span for span in binding["evidence"]}
    cited: list[dict[str, Any]] = []
    feedback: list[dict[str, str]] = []
    for item in parsed.get("evidence") or []:
        if not isinstance(item, dict) or item.get("ref") not in known:
            return _record(binding, review_state="held_failure", reason="evidence_mismatch")
        cited.append(known[item["ref"]])
        note = item.get("note")
        feedback.append({"ref": item["ref"], "note": note if isinstance(note, str) else ""})
    if parsed.get("verdict") == "needs_revision":
        return _record(
            binding, review_state="needs_revision", cited=cited, feedback=feedback, accepted=False,
        )
    if parsed.get("verdict") == "pass" and cited:
        return _record(
            binding, review_state="accepted_review", cited=cited, feedback=feedback, accepted=True,
        )
    return _record(binding, review_state="held_failure", reason="verdict_not_accepted")


def _rehash(path: str) -> tuple[Optional[str], Optional[str]]:
    try:
        blob = Path(path).read_bytes()
    except OSError as exc:
        return None, str(exc)
    return hashlib.sha256(blob).hexdigest(), None


def _parsed_summary(summary: str) -> Optional[dict[str, Any]]:
    from tools.delegation_output_schema import extract_json_candidate
    try:
        parsed = json.loads(extract_json_candidate(summary))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _record(
    binding: dict[str, Any], *, review_state: str, reason: Optional[str] = None,
    cited: Optional[list[dict[str, Any]]] = None, feedback: Optional[list[dict[str, str]]] = None,
    accepted: bool = False,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "review_state": review_state,
        "effective_state": review_state,
        "review_accepted": accepted,
        "verdict_source": "review_child" if review_state in {"needs_revision", "accepted_review"} else None,
        "reason": reason,
        "release": dict(_RELEASE),
        "provenance": {
            "source": binding["source"],
            "artifact": binding["artifact"],
            "requirements": binding.get("requirements"),
            "evidence": cited or [],
        },
        "feedback": feedback or [],
        "cached": False,
    }
    if binding.get("ignored_caller_verdict") is not None:
        record["ignored_caller_verdict"] = binding["ignored_caller_verdict"]
    return record


def _cache_path(binding: dict[str, Any]) -> Path:
    from hermes_constants import get_hermes_home
    name = f"{binding['source']['sha256']}-{binding['artifact']['sha256']}.json"
    return get_hermes_home() / "review-contracts" / name


def _store(record: dict[str, Any]) -> None:
    if record["review_state"] == "awaiting_review":
        return
    path = _cache_path({"source": record["provenance"]["source"], "artifact": record["provenance"]["artifact"]})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except OSError:
        record["cache_write_error"] = "review record was not stored"


def _cached_result(binding: dict[str, Any]) -> Optional[dict[str, Any]]:
    path = _cache_path(binding)
    if not path.is_file():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(stored, dict) or stored.get("review_state") not in {
        "needs_revision", "held_failure", "accepted_review",
    }:
        return None
    stored["cached"] = True
    if stored["review_state"] != "accepted_review":
        stored["effective_state"] = "recheck_required"
        stored["review_accepted"] = False
    stored["release"] = dict(_RELEASE)
    if binding.get("ignored_caller_verdict") is not None:
        stored["ignored_caller_verdict"] = binding["ignored_caller_verdict"]
    return {
        "review_workflow": stored,
        "results": [],
        "spawned": False,
        "note": (
            "No subagent was started. These artifact bytes already have a host review record. "
            "A needs_revision or held failure stays recheck_required until the artifact bytes change. "
            "Release was not executed."
        ),
    }

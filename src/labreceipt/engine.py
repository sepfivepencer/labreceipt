"""Workspace observation, impact analysis, and acceptance execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labreceipt import __version__
from labreceipt.canonical import digest_json, sha256_bytes
from labreceipt.contracts import ArtifactSpec, Contract
from labreceipt.errors import LabReceiptError
from labreceipt.rules import ArtifactObservation, evaluate
from labreceipt.safeio import read_workspace_file


@dataclass(frozen=True)
class Verification:
    """A sealed receipt and its final verdict."""

    receipt: dict[str, Any]
    passed: bool


def observe(root: Path, artifact: ArtifactSpec) -> ArtifactObservation:
    """Observe one artifact without exposing content in the returned metadata."""
    try:
        data, size = read_workspace_file(root, artifact.path, artifact.max_bytes)
    except LabReceiptError as exc:
        message = str(exc)
        if message == "artifact is missing":
            state = "missing"
        elif message == "artifact exceeds its byte limit":
            state = "too_large"
        elif "symlink" in message or "regular file" in message:
            state = "unsafe_path"
        else:
            state = "unreadable"
        return ArtifactObservation(artifact.artifact_id, artifact.path, state, None, None, None)
    return ArtifactObservation(
        artifact.artifact_id,
        artifact.path,
        "ok",
        sha256_bytes(data),
        size,
        data,
    )


def _previous_artifacts(previous: dict[str, Any]) -> dict[str, Any]:
    artifact_map: dict[str, Any] = {}
    for item in previous.get("artifacts", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            artifact_map[item["id"]] = item
    return artifact_map


def _artifact_signature(value: dict[str, Any]) -> tuple[Any, Any, Any]:
    return value.get("state"), value.get("sha256"), value.get("bytes")


def calculate_impact(
    contract: Contract,
    observations: tuple[ArtifactObservation, ...],
    previous: dict[str, Any] | None,
) -> dict[str, list[str]]:
    """Return directly changed artifacts and dependency-transitive invalidations."""
    if previous is None:
        changed = {artifact.artifact_id for artifact in contract.artifacts}
    else:
        previous_artifacts = _previous_artifacts(previous)
        changed = {
            observation.artifact_id
            for observation in observations
            if observation.artifact_id not in previous_artifacts
            or _artifact_signature(observation.public_dict())
            != _artifact_signature(previous_artifacts[observation.artifact_id])
        }
    invalidated = set(changed)
    made_progress = True
    while made_progress:
        made_progress = False
        for artifact in contract.artifacts:
            if artifact.artifact_id not in invalidated and any(
                dependency in invalidated for dependency in artifact.depends_on
            ):
                invalidated.add(artifact.artifact_id)
                made_progress = True
    invalidated_rules = {rule.rule_id for rule in contract.rules if rule.artifact_id in invalidated}
    return {
        "changed_artifacts": sorted(changed),
        "invalidated_artifacts": sorted(invalidated),
        "invalidated_rules": sorted(invalidated_rules),
    }


def _validate_previous(contract: Contract, previous: dict[str, Any]) -> None:
    contract_record = previous.get("contract")
    engine_record = previous.get("engine")
    if not isinstance(contract_record, dict) or contract_record.get("sha256") != contract.digest:
        raise LabReceiptError("prior receipt belongs to a different contract")
    if not isinstance(engine_record, dict) or engine_record != {
        "name": "labreceipt",
        "version": __version__,
    }:
        raise LabReceiptError("prior receipt uses a different verification engine")


def verify(
    contract: Contract,
    workspace: Path,
    previous: dict[str, Any] | None = None,
) -> Verification:
    """Verify a confirmed contract and build a deterministic evidence receipt."""
    if contract.status != "confirmed":
        raise LabReceiptError(
            "candidate contract must be reviewed and confirmed before verification"
        )
    if previous is not None:
        _validate_previous(contract, previous)
    observations = tuple(observe(workspace, artifact) for artifact in contract.artifacts)
    by_id = {observation.artifact_id: observation for observation in observations}
    impact = calculate_impact(contract, observations, previous)
    evidence: list[dict[str, Any]] = []
    evaluated = 0
    for rule in contract.rules:
        passed, code, details = evaluate(rule, by_id[rule.artifact_id])
        evidence.append(
            {
                "artifact_id": rule.artifact_id,
                "code": code,
                "details": details,
                "execution": "evaluated",
                "rule_id": rule.rule_id,
                "status": "pass" if passed else "fail",
                "type": rule.rule_type,
            }
        )
        evaluated += 1
    failures = sum(item["status"] == "fail" for item in evidence)
    body = {
        "artifacts": [observation.public_dict() for observation in observations],
        "contract": {"id": contract.contract_id, "sha256": contract.digest},
        "engine": {"name": "labreceipt", "version": __version__},
        "evidence": evidence,
        "impact": impact,
        "schema_version": "1",
        "summary": {
            "evaluated": evaluated,
            "failed": failures,
            "passed": len(evidence) - failures,
            "reused": 0,
            "verdict": "pass" if failures == 0 else "fail",
        },
        "workspace": {
            "artifact_set_sha256": digest_json(
                [observation.public_dict() for observation in observations]
            )
        },
    }
    from labreceipt.receipts import seal_receipt

    receipt = seal_receipt(body)
    return Verification(receipt, failures == 0)

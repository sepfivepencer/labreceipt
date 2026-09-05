from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from labreceipt.contracts import Contract, contract_from_dict
from labreceipt.engine import observe, verify
from labreceipt.errors import LabReceiptError
from labreceipt.receipts import load_receipt, receipt_bytes, seal_receipt


def test_verify_passes_and_is_deterministic(contract: Contract, workspace: Path) -> None:
    first = verify(contract, workspace)
    second = verify(contract, workspace)
    assert first.passed
    assert first.receipt == second.receipt
    assert first.receipt["summary"] == {
        "evaluated": 3,
        "failed": 0,
        "passed": 3,
        "reused": 0,
        "verdict": "pass",
    }


def test_verify_rejects_candidate(contract_dict: dict[str, Any], workspace: Path) -> None:
    contract_dict["status"] = "candidate"
    contract_dict.pop("reviewed_by")
    with pytest.raises(LabReceiptError, match="reviewed"):
        verify(contract_from_dict(contract_dict), workspace)


def test_missing_artifact_fails(contract: Contract, workspace: Path) -> None:
    (workspace / "report.json").unlink()
    result = verify(contract, workspace)
    assert not result.passed
    assert result.receipt["summary"]["failed"] == 1
    assert result.receipt["artifacts"][1]["state"] == "missing"


def test_schema_failure_has_no_artifact_value(contract: Contract, workspace: Path) -> None:
    private = "private-payload-not-for-receipt"
    (workspace / "report.json").write_text(json.dumps({"answer": private}))
    result = verify(contract, workspace)
    assert not result.passed
    assert private not in json.dumps(result.receipt)


def test_changed_source_invalidates_dependent(contract: Contract, workspace: Path) -> None:
    previous = verify(contract, workspace).receipt
    (workspace / "source.txt").write_text("changed")
    result = verify(contract, workspace, previous)
    assert result.receipt["impact"] == {
        "changed_artifacts": ["source"],
        "invalidated_artifacts": ["report", "source"],
        "invalidated_rules": ["report_schema", "source_exists", "source_utf8"],
    }
    assert result.receipt["summary"]["reused"] == 0


def test_changed_dependent_invalidates_only_its_rules(contract: Contract, workspace: Path) -> None:
    previous = verify(contract, workspace).receipt
    (workspace / "report.json").write_text('{"answer":7}')
    result = verify(contract, workspace, previous)
    assert result.receipt["impact"]["invalidated_artifacts"] == ["report"]
    assert result.receipt["summary"]["reused"] == 0
    assert [item["execution"] for item in result.receipt["evidence"]] == [
        "evaluated",
        "evaluated",
        "evaluated",
    ]


def test_unchanged_workspace_invalidates_no_evidence(contract: Contract, workspace: Path) -> None:
    previous = verify(contract, workspace).receipt
    result = verify(contract, workspace, previous)
    assert result.receipt["impact"]["changed_artifacts"] == []
    assert result.receipt["impact"]["invalidated_rules"] == []
    assert result.receipt["summary"]["reused"] == 0
    assert result.receipt["summary"]["evaluated"] == 3


def test_resealed_previous_receipt_cannot_fake_current_pass(
    contract: Contract, workspace: Path
) -> None:
    (workspace / "report.json").write_text('{"answer":"wrong"}')
    genuine = verify(contract, workspace).receipt
    body = {key: value for key, value in copy.deepcopy(genuine).items() if key != "receipt_id"}
    body["evidence"][2]["status"] = "pass"
    body["summary"]["failed"] = 0
    body["summary"]["verdict"] = "pass"
    forged_but_self_consistent = seal_receipt(body)
    result = verify(contract, workspace, forged_but_self_consistent)
    assert not result.passed
    assert result.receipt["evidence"][2]["status"] == "fail"


def test_rejects_previous_for_different_contract(
    contract: Contract, contract_dict: dict[str, Any], workspace: Path
) -> None:
    previous = verify(contract, workspace).receipt
    contract_dict["contract_id"] = "other"
    with pytest.raises(LabReceiptError, match="different contract"):
        verify(contract_from_dict(contract_dict), workspace, previous)


def test_rejects_previous_for_different_engine(contract: Contract, workspace: Path) -> None:
    previous = copy.deepcopy(verify(contract, workspace).receipt)
    previous["engine"]["version"] = "9"
    with pytest.raises(LabReceiptError, match="different verification engine"):
        verify(contract, workspace, previous)


def test_observe_marks_symlink_unsafe(contract: Contract, workspace: Path) -> None:
    (workspace / "source.txt").unlink()
    (workspace / "target").write_text("private")
    (workspace / "source.txt").symlink_to(workspace / "target")
    item = observe(workspace, contract.artifacts[0])
    assert item.state == "unsafe_path"
    assert item.digest is None and item.data is None


def test_observe_marks_oversize(contract_dict: dict[str, Any], workspace: Path) -> None:
    contract_dict["artifacts"][0]["max_bytes"] = 2
    item = observe(workspace, contract_from_dict(contract_dict).artifacts[0])
    assert item.state == "too_large"


def test_receipt_round_trip(contract: Contract, workspace: Path, tmp_path: Path) -> None:
    result = verify(contract, workspace)
    path = tmp_path / "receipt.json"
    path.write_bytes(receipt_bytes(result.receipt))
    assert load_receipt(path) == result.receipt


def test_receipt_tamper_is_detected(contract: Contract, workspace: Path, tmp_path: Path) -> None:
    receipt = verify(contract, workspace).receipt
    receipt["summary"]["verdict"] = "fail"
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(LabReceiptError, match="self-digest"):
        load_receipt(path)


def test_receipt_rejects_recognized_secret(tmp_path: Path) -> None:
    body = {
        "schema_version": "1",
        "contract": {},
        "engine": {},
        "artifacts": [],
        "evidence": [],
        "summary": {},
        "impact": {},
        "note": "ghp_" + "x" * 36,
    }
    path = tmp_path / "receipt.json"
    path.write_bytes(receipt_bytes(seal_receipt(body)))
    with pytest.raises(LabReceiptError, match="recognized secret"):
        load_receipt(path)
